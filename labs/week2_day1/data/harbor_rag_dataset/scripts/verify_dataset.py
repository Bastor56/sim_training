#!/usr/bin/env python3
"""Self-check for the Harbor Credit Union RAG dataset.

Dependencies: Python 3.8+ standard library and PyMuPDF (import fitz / pymupdf).
Usage: python3 scripts/verify_dataset.py [dataset_root]
Exits 0 when every check passes, 1 otherwise.
"""
import csv
import json
import os
import re
import sys
import unicodedata
from collections import Counter, defaultdict

try:
    import pymupdf as fitz  # PyMuPDF >= 1.24
except ImportError:
    import fitz  # older PyMuPDF

ROOT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), '..'))
CORPUS = os.path.join(ROOT, 'corpus')
GT_DIR = os.path.join(ROOT, 'eval', 'ground_truth_text')
KEY = os.path.join(ROOT, '_answer_key')

SCANNED = ['fee_schedule_2026', 'deposit_rate_sheet_2026q3', 'auto_loan_comparison', 'mortgage_heloc_rate_notice']
CP1252_DOC = 'privacy_notice'
MOJIBAKE_DOC = 'debit_card_limits'
MOJIBAKE_SEQS = ['\u00e2\u20ac', '\u00c3\u00a9']  # "â€" (smart punctuation) and "Ã©" (é)
EXACT_DUP = ('member_faq', 'member_faq_copy')
EMPTY_DOC = 'branch_locations'
CORRUPT_DOC = 'rate_sheet_2026q2'
EXPECTED_TYPES = {'exact_term': 6, 'paraphrase': 9, 'scanned_table': 8, 'figure': 2, 'reading_order': 2,
                  'version_trap': 4, 'multi_chunk': 4, 'duplicate_source': 2, 'tenant_filter': 2,
                  'encoding': 2, 'pii_adjacent': 1, 'unanswerable': 3}

PII_PATTERNS = {
    'ssn': re.compile(r'\b9\d{2}-\d{2}-\d{4}\b'),
    'member_number': re.compile(r'\bHCU-\d{6}\b'),
    'account_number': re.compile(r'\b7730-\d{4}-\d{4}\b'),
    'phone': re.compile(r'\(?\b555\)?[ .-]?\d{3}-\d{4}\b|\b555-01\d{2}\b'),
    'email': re.compile(r'[\w.+-]+@[\w-]+(\.[\w-]+)*\.(com|org)\b', re.I),
    'dob': re.compile(r'DOB:?\s*\d{2}/\d{2}/\d{4}'),
    'street_address': re.compile(r'\b\d{1,5}( [A-Z][a-z]+){1,3} (Lane|Street|Road|Court|Drive|Way|Avenue), [A-Z][a-z]+( [A-Z][a-z]+)?, ME 0\d{4}\b'),
}

_TRANS = {0x2018: "'", 0x2019: "'", 0x201A: "'", 0x2032: "'", 0x201C: '"', 0x201D: '"', 0x201E: '"', 0x2033: '"',
          0x2013: '-', 0x2014: '-', 0x2012: '-', 0x2212: '-', 0x2011: '-', 0x2026: '...'}


def norm(s):
    s = unicodedata.normalize('NFKC', s).translate(_TRANS).lower()
    return ' '.join(s.split())


def matches(quote, text, rule):
    nq, nt = norm(quote), norm(text)
    if rule == 'substring':
        return nq in nt
    if rule == 'all_tokens':
        return all(tok in nt for tok in nq.split())
    raise ValueError('unknown match rule %r' % rule)


# ---------------------------------------------------------------- mini YAML
# Parses the subset written by the generator: block mappings, block sequences
# of scalars or mappings ("- key: value"), JSON double-quoted strings, flow
# lists of scalars, ints, true/false/null, [] and comment lines.

def _scalar(tok):
    tok = tok.strip()
    if tok.startswith('"'):
        return json.loads(tok)
    if tok.startswith('['):
        inner = tok[1:-1].strip()
        if not inner:
            return []
        return json.loads('[' + inner + ']') if inner.startswith('"') or inner[0].isdigit() else [x.strip() for x in inner.split(',')]
    if tok in ('null', '~', ''):
        return None
    if tok == 'true':
        return True
    if tok == 'false':
        return False
    if re.fullmatch(r'-?\d+', tok):
        return int(tok)
    return tok


def load_yaml(path):
    lines = []
    for raw in open(path, encoding='utf-8').read().splitlines():
        if not raw.strip() or raw.lstrip().startswith('#'):
            continue
        lines.append((len(raw) - len(raw.lstrip(' ')), raw.strip()))
    pos = [0]

    def split_kv(text):
        k, _, v = text.partition(':')
        return k.strip(), v.strip()

    def parse_block(indent):
        if pos[0] >= len(lines):
            return None
        ind, text = lines[pos[0]]
        if text.startswith('- ') or text == '-':
            return parse_seq(ind)
        return parse_map(ind)

    def parse_map(indent, first=None):
        out = {}
        if first is not None:
            k, v = split_kv(first)
            out[k] = _scalar(v) if v else parse_block(indent + 1)
        while pos[0] < len(lines):
            ind, text = lines[pos[0]]
            if ind != indent or text.startswith('- '):
                break
            pos[0] += 1
            k, v = split_kv(text)
            if v:
                out[k] = _scalar(v)
            else:
                nxt = lines[pos[0]] if pos[0] < len(lines) else None
                out[k] = parse_block(nxt[0]) if nxt and nxt[0] >= indent else None
        return out

    def parse_seq(indent):
        out = []
        while pos[0] < len(lines):
            ind, text = lines[pos[0]]
            if ind != indent or not text.startswith('-'):
                break
            pos[0] += 1
            item = text[1:].strip()
            if re.match(r'^[A-Za-z_][\w]*:( |$)', item):
                # mapping item; continuation keys are indented by indent + 2
                out.append(parse_map(indent + 2, first=item))
            else:
                out.append(_scalar(item))
        return out

    return parse_block(0)


# ---------------------------------------------------------------- checks
failures = []


def check(cond, msg):
    if not cond:
        failures.append(msg)
    return cond


def main():
    meta = list(csv.DictReader(open(os.path.join(KEY, 'document_metadata.csv'), encoding='utf-8', newline='')))
    by_id = {r['doc_id']: r for r in meta}
    path_of = {d: os.path.join(CORPUS, r['filename']) for d, r in by_id.items()}

    # 1. metadata <-> corpus
    listed = {r['filename'] for r in meta}
    present = {f for f in os.listdir(CORPUS) if os.path.isfile(os.path.join(CORPUS, f))}
    for f in sorted(listed - present):
        check(False, '[1] listed in metadata but missing from corpus: %s' % f)
    for f in sorted(present - listed):
        check(False, '[1] in corpus but not listed in metadata: %s' % f)
    exp = list(csv.DictReader(open(os.path.join(KEY, 'ingestion_expectations.csv'), encoding='utf-8', newline='')))
    check({r['filename'] for r in exp} == listed, '[1] ingestion_expectations.csv filenames differ from metadata')
    for r in exp:
        check(r['expected_decision'] in ('cleaned', 'quarantined', 'dropped'), '[1] bad decision for %s' % r['filename'])
    for d, r in by_id.items():
        if r['superseded_by']:
            check(r['superseded_by'] in by_id, '[1] %s superseded_by unknown doc %s' % (d, r['superseded_by']))

    # 2. scanned PDFs have no text layer
    for d in SCANNED:
        doc = fitz.open(path_of[d])
        txt = ''.join(p.get_text() for p in doc)
        check(doc.page_count >= 1, '[2] %s has no pages' % d)
        check(txt.strip() == '', '[2] %s has an extractable text layer (%d chars)' % (d, len(txt.strip())))
        check(all(not p.get_fonts() for p in doc), '[2] %s embeds fonts' % d)
        doc.close()

    # 3. encodings
    raw = open(path_of[CP1252_DOC], 'rb').read()
    try:
        raw.decode('utf-8')
        check(False, '[3] %s decodes as UTF-8 (should not)' % CP1252_DOC)
    except UnicodeDecodeError:
        pass
    try:
        cp = raw.decode('cp1252')
        check(any(c in cp for c in '\u2019\u201c\u2014\u00a9\u00e9'), '[3] %s lacks cp1252 special characters' % CP1252_DOC)
    except UnicodeDecodeError:
        check(False, '[3] %s does not decode as cp1252' % CP1252_DOC)
    moj = open(path_of[MOJIBAKE_DOC], 'rb').read().decode('utf-8')
    moj_count = sum(moj.count(s) for s in MOJIBAKE_SEQS)
    check(moj_count >= 10, '[3] %s has only %d mojibake sequences' % (MOJIBAKE_DOC, moj_count))

    # 4. duplicate, empty, corrupt
    a, b = (open(path_of[x], 'rb').read() for x in EXACT_DUP)
    check(a == b, '[4] %s and %s are not byte-identical' % EXACT_DUP)
    check(os.path.getsize(path_of[EMPTY_DOC]) == 0, '[4] %s is not 0 bytes' % EMPTY_DOC)
    corrupt_ok = False
    try:
        doc = fitz.open(path_of[CORRUPT_DOC])
        if doc.page_count == 0:
            corrupt_ok = True
        else:
            try:
                for p in doc:
                    p.get_text()
            except Exception:
                corrupt_ok = True
    except Exception:
        corrupt_ok = True
    check(corrupt_ok, '[4] %s opens cleanly (should fail)' % CORRUPT_DOC)

    # ground truth
    gt = {}
    for f in os.listdir(GT_DIR):
        if f.endswith('.txt'):
            gt[f[:-4]] = open(os.path.join(GT_DIR, f), encoding='utf-8').read()
    for d in gt:
        check(d in by_id, '[5] ground truth for unknown doc_id %s' % d)
    content_docs = [r['doc_id'] for r in exp if r['expected_decision'] != 'quarantined' and os.path.getsize(path_of[r['doc_id']]) > 400]
    for d in content_docs:
        check(d in gt, '[5] content doc %s has no ground_truth_text' % d)
    for d, t in gt.items():
        for name, pat in PII_PATTERNS.items():
            if name == 'email' and '@' in t:
                hits = [m.group(0) for m in pat.finditer(t)]
                check(not hits, '[6] ground truth %s still contains %s: %s' % (d, name, hits[:3]))
            elif name != 'email':
                check(not pat.search(t), '[6] ground truth %s still contains %s' % (d, name))
    norm_gt = {d: norm(t) for d, t in gt.items()}

    def check_quote(where, loc, all_locs):
        d, q, rule = loc.get('doc_id'), loc.get('quote', ''), loc.get('match')
        if not check(d in by_id, '[5] %s: unknown doc_id %s' % (where, d)):
            return
        if not check(d in gt, '[5] %s: no ground truth for %s' % (where, d)):
            return
        check(rule in ('substring', 'all_tokens'), '[5] %s: bad match rule %r' % (where, rule))
        check(matches(q, gt[d], rule), '[5] %s: quote not found in %s under %s: %r' % (where, d, rule, q))
        if rule == 'substring':
            n = len(q.split())
            check(5 <= n <= 20, '[5] %s: substring quote has %d words: %r' % (where, n, q))
            found_in = {x for x, t in norm_gt.items() if norm(q) in t}
            extra = found_in - set(all_locs)
            check(not extra, '[5] %s: quote also appears in unlisted docs %s: %r' % (where, sorted(extra), q))
        for name, pat in PII_PATTERNS.items():
            check(not pat.search(q), '[6] %s: quote contains %s pattern: %r' % (where, name, q))

    # facts
    facts = load_yaml(os.path.join(KEY, 'facts.yaml'))['facts']
    fact_ids = [f['fact_id'] for f in facts]
    check(38 <= len(facts) <= 45, '[5] %d facts (expected 38-45)' % len(facts))
    check(len(set(fact_ids)) == len(fact_ids), '[5] duplicate fact_ids')
    facts_per_doc = Counter()
    for f in facts:
        locs = f.get('locations') or []
        check(locs, '[5] fact %s has no locations' % f['fact_id'])
        ids = [l['doc_id'] for l in locs]
        for l in locs:
            check_quote('fact %s' % f['fact_id'], l, ids)
        for l in f.get('distractors') or []:
            check(l['doc_id'] in gt and matches(l['quote'], gt[l['doc_id']], l['match']),
                  '[5] fact %s distractor not found in %s: %r' % (f['fact_id'], l['doc_id'], l['quote']))
        for d in set(ids):
            facts_per_doc[d] += 1

    # 5. golden set
    gs = load_yaml(os.path.join(ROOT, 'eval', 'golden_set.yaml'))
    qs = gs['queries']
    check(len(qs) == 45, '[7] %d queries (expected 45)' % len(qs))
    check(len({q['id'] for q in qs}) == len(qs), '[5] duplicate query ids')
    targeted = set()
    for q in qs:
        where = 'query %s' % q['id']
        ids = [e['doc_id'] for e in q['expected']]
        targeted.update(ids)
        if q['type'] == 'unanswerable':
            check(q['expected'] == [], '[5] %s: unanswerable query has expected passages' % where)
        else:
            check(q['expected'], '[5] %s: no expected passages' % where)
        for e in q['expected']:
            # multi_chunk lists different passages of one doc, so uniqueness is judged per listed doc set
            check_quote(where, e, ids)
        for fid in q.get('fact_ids') or []:
            check(fid in fact_ids, '[5] %s: unknown fact_id %s' % (where, fid))
        if q['type'] == 'multi_chunk':
            check(2 <= len(q['expected']) <= 4, '[5] %s: multi_chunk needs 2-4 passages' % where)
        if q['type'] == 'duplicate_source':
            check(len(set(ids)) >= 2, '[5] %s: duplicate_source must list both copies' % where)
        if q['type'] in ('scanned_table', 'figure'):
            check(all(e['match'] == 'all_tokens' for e in q['expected']), '[5] %s: table/figure quotes must be all_tokens' % where)

    # every non-defective content doc is targeted
    for r in exp:
        if r['expected_decision'] == 'cleaned' and not by_id[r['doc_id']]['superseded_by'] and r['doc_id'] not in targeted:
            check(False, '[5] cleaned content doc %s is not targeted by any query' % r['doc_id'])

    # 7. type counts
    tc = Counter(q['type'] for q in qs)
    for t, n in EXPECTED_TYPES.items():
        check(tc.get(t, 0) == n, '[7] type %s has %d queries (expected %d)' % (t, tc.get(t, 0), n))
    for t in tc:
        check(t in EXPECTED_TYPES, '[7] unexpected query type %s' % t)

    # 8. summary
    def ext(fn):
        e = os.path.splitext(fn)[1].lower().lstrip('.')
        return e
    fmt = Counter()
    for d, r in by_id.items():
        e = ext(r['filename'])
        if e == 'pdf':
            e = 'pdf (scanned)' if d in SCANNED else ('pdf (corrupt)' if d == CORRUPT_DOC else 'pdf (digital)')
        fmt[e] += 1

    print('Harbor RAG dataset verification')
    print('root: %s' % ROOT)
    print()
    print('Files per format')
    for k, v in sorted(fmt.items()):
        print('  %-16s %3d' % (k, v))
    print('  %-16s %3d' % ('TOTAL', sum(fmt.values())))
    print()
    print('Facts per doc (location docs; %d facts total)' % len(facts))
    for d in sorted(by_id):
        if facts_per_doc[d]:
            print('  %-30s %3d' % (d, facts_per_doc[d]))
    print()
    print('Queries per type (%d total)' % len(qs))
    for t in EXPECTED_TYPES:
        print('  %-18s %3d  (expected %d)' % (t, tc.get(t, 0), EXPECTED_TYPES[t]))
    print()
    n_quotes = sum(len(q['expected']) for q in qs)
    print('Checked %d golden quotes, %d fact locations, %d ground-truth files.' % (
        n_quotes, sum(len(f['locations']) for f in facts), len(gt)))
    print('Mojibake sequences in %s: %d' % (MOJIBAKE_DOC, moj_count))
    print()
    if failures:
        print('FAILED: %d problem(s)' % len(failures))
        for f in failures:
            print('  - ' + f)
        sys.exit(1)
    print('ALL CHECKS PASSED')


if __name__ == '__main__':
    main()
