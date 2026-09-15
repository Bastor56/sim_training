// Handler layer: executes the one function the model asked for. Never talks
// to the model — takes the peril the orchestrator already validated (the
// model's tool_use argument) plus the caller's known policy number (sourced
// out-of-band, never from the model — see orchestrator.ts), does the real
// work (a Supabase lookup), and returns a typed result to the caller. This
// is the only file in the app that touches the database.

// Supabase is a hosted Postgres database with a JS client library.
// `createClient` builds a connection you can query with; `SupabaseClient`
// is just its TypeScript type, imported with `type` since we only need it
// for type-checking, not at runtime.
import { createClient, type SupabaseClient } from "@supabase/supabase-js";
// Zod is a schema-validation library: you describe the shape data SHOULD
// have, and it checks real data against that shape at runtime (something
// TypeScript's own types can't do, since they vanish after compilation).
import { z } from "zod";
import {
  PerilSchema,
  PolicyNumberSchema,
  PolicyStatusSchema,
  type Peril,
  type CheckPolicyCoverageOutput,
} from "./schema.js";

// Same lazy-singleton pattern as client.ts: build the Supabase client once,
// reuse it on every subsequent call in this process.
let cachedClient: SupabaseClient | undefined;

function getSupabaseClient(): SupabaseClient {
  if (!cachedClient) {
    const url = process.env.SUPABASE_URL;
    // check_policy_coverage is a trusted, server-side-only call: it always
    // uses the service role key (which bypasses the policies table's RLS by
    // design), never the anon key. See
    // supabase/migrations/..._create_policies.sql.
    // Beginner note: RLS = "Row Level Security," a Postgres/Supabase
    // feature that restricts which rows a query can see. The "service
    // role key" is a privileged credential that skips those restrictions —
    // appropriate here because this code runs on a trusted server, not in
    // a user's browser.
    const serviceRoleKey = process.env.SUPABASE_SERVICE_ROLE_KEY;
    // Fail loudly and immediately if the required environment variables
    // are missing, rather than letting a confusing error surface later
    // deep inside the Supabase library.
    if (!url || !serviceRoleKey) {
      throw new Error(
        "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in the environment for check_policy_coverage to run.",
      );
    }
    cachedClient = createClient(url, serviceRoleKey);
  }
  return cachedClient;
}

// What a `policies` row actually looks like coming back over the wire —
// validated separately from CheckPolicyCoverageOutputSchema, which
// describes the { found, ... } shape this handler produces, not the raw
// table row.
// z.object(...) describes an object with named fields, each with its own
// schema. z.partialRecord builds a dictionary-like object where keys are
// constrained to PerilSchema's enum values and each value must be a
// non-negative number (a coverage dollar limit) — but not every peril has
// to be present.
const PolicyRowSchema = z.object({
  status: PolicyStatusSchema,
  coverage_limits: z.partialRecord(PerilSchema, z.number().nonnegative()),
});

// This is the actual "tool" function: it's what runs when the orchestrator
// decides to act on the model's check_policy_coverage tool call. Notice it
// takes plain, already-validated arguments — it has no idea a language
// model was ever involved.
export async function checkPolicyCoverage(
  policyNumber: string,
  peril: Peril,
): Promise<CheckPolicyCoverageOutput> {
  // Defensive validation at this boundary: policyNumber arrives from the
  // caller's own context (auth session, CRM), not from the model, but it's
  // still external input to this function and worth checking before it
  // reaches a query.
  // `safeParse` (as opposed to `parse`) returns a result object instead of
  // throwing, so we can decide how to handle a bad value ourselves.
  const policyNumberResult = PolicyNumberSchema.safeParse(policyNumber);
  if (!policyNumberResult.success) {
    throw new Error(`Invalid policy number "${policyNumber}": must match POL-XXXXXX`);
  }

  const supabase = getSupabaseClient();

  // A typical Supabase query, chained like a sentence:
  // "from the policies table, select these two columns, where
  // policy_number equals this value, and give me at most one row (or
  // null if there isn't one)."
  const { data, error } = await supabase
    .from("policies")
    .select("status, coverage_limits")
    .eq("policy_number", policyNumberResult.data)
    .maybeSingle();

  // Supabase reports failures via an `error` field rather than throwing —
  // this is a common pattern in JS database clients, so we check for it
  // explicitly and convert it into a thrown Error ourselves.
  if (error) {
    throw new Error(`check_policy_coverage query failed: ${error.message}`);
  }

  // No error, but also no matching row: the policy number simply doesn't
  // exist in the table. This is a normal, expected outcome — not an error —
  // so it's represented as a typed `{ found: false }` result rather than
  // a thrown exception.
  if (!data) {
    return { found: false };
  }

  // `.parse` (not `.safeParse`) here — if the database ever returns a row
  // shaped differently than expected, we WANT this to throw loudly, since
  // that would mean our own data is corrupt, not that a user gave bad
  // input.
  const row = PolicyRowSchema.parse(data);
  return {
    found: true,
    status: row.status,
    // `?? null`: if this specific peril isn't a key in coverage_limits at
    // all, report that as "no limit on file" rather than crashing on an
    // undefined lookup.
    limit: row.coverage_limits[peril] ?? null,
  };
}
