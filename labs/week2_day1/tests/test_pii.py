import unittest

from config import DEFAULT_PARAMS
from models import Block, Decision, Document
from pii import scrub_document, scrub_text

PARAMS = DEFAULT_PARAMS["scrub"]


def scrub(text: str) -> str:
    return scrub_text(text, PARAMS)[0]


class HarborFormatTests(unittest.TestCase):
    """Each structured format, including the gaps Presidio has out of the box."""

    def test_member_number_fully_redacted(self):
        # Out of the box Presidio only half-matched this (as a driver's licence).
        self.assertEqual(scrub("Member #: HCU-004821."), "Member #: [REDACTED-MEMBER].")

    def test_account_number(self):
        self.assertEqual(scrub("Acct: 7730-0012-4471"), "Acct: [REDACTED-ACCOUNT]")

    def test_ssn_in_the_never_issued_9xx_range(self):
        self.assertEqual(scrub("SSN (verified): 912-45-6789"), "SSN (verified): [REDACTED-SSN]")

    def test_phone_formats(self):
        self.assertEqual(scrub("Phone: (555) 555-0142 or 555-0187"), "Phone: [REDACTED-PHONE] or [REDACTED-PHONE]")

    def test_email_is_one_span_not_email_plus_url(self):
        self.assertEqual(scrub("Email: m.vega81@example.com |"), "Email: [REDACTED-EMAIL] |")

    def test_dob_keeps_its_label(self):
        self.assertEqual(scrub("DOB: 03/22/1981"), "DOB: [REDACTED-DOB]")

    def test_address_wins_over_person_inside_it(self):
        # NER tags "Birch Lane" as a person; the address match must swallow it.
        self.assertEqual(scrub("Address: 88 Birch Lane, Westmere, ME 04602"), "Address: [REDACTED-ADDRESS]")

    def test_member_full_name(self):
        self.assertEqual(scrub("Member: Marisol Vega | Member #:"), "Member: [REDACTED-NAME] | Member #:")


class NotPiiTests(unittest.TestCase):
    def test_harbor_contact_details_survive(self):
        text = "Call 1-800-4-HARBOR ext. 4417 or visit the Carrow Bay branch at 88 Wharf Street."
        self.assertEqual(scrub(text), text)

    def test_staff_initial_and_surname_survive(self):
        self.assertEqual(scrub("Agent: J. Okafor (ext. 4302)"), "Agent: J. Okafor (ext. 4302)")

    def test_branch_name_is_not_a_person(self):
        self.assertEqual(scrub("Member Service Supervisor, Port Alden Branch"),
                         "Member Service Supervisor, Port Alden Branch")

    def test_form_numbers_and_product_names_survive(self):
        text = "Complete Form HCU-DSP-114; the Courtesy Pay limit is $500; HELOC rate is 5.99%."
        self.assertEqual(scrub(text), text)


class ScrubLogTests(unittest.TestCase):
    def test_log_holds_hashes_never_values(self):
        doc = Document(doc_id="x", source_filename="x.txt", source_sha256="", format="txt", catalog={},
                       blocks=[Block(type="paragraph", text="Member: Dana Whitfield, SSN 912-45-6789.")],
                       decision=Decision(status="cleaned", reason="no defects found"))
        scrub_document(doc, PARAMS)
        self.assertNotIn("Dana Whitfield", doc.text)
        self.assertEqual({s["type"] for s in doc.pii_spans}, {"NAME", "SSN"})
        for span in doc.pii_spans:
            self.assertEqual(set(span), {"type", "start", "end", "value_sha256", "block"})
            self.assertEqual(len(span["value_sha256"]), 64)
        self.assertNotIn("912-45-6789", str(doc.pii_spans))
        self.assertIn("redacted 2 PII values (name 1, ssn 1)", doc.decision.reason)


if __name__ == "__main__":
    unittest.main()
