// Handler layer: executes the function the model asks for. Takes the peril
// the orchestrator validated and the customer's known policy number (sourced
// out-of-band - e.g. via auth session or separate field) to do a supabase
// lookup and return a typed result.

import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import { z } from "zod";
import {
  PerilSchema,
  PolicyNumberSchema,
  PolicyStatusSchema,
  type Peril,
  type CheckPolicyCoverageOutput,
} from "./schema.js";

let cachedClient: SupabaseClient | undefined;

function getSupabaseClient(): SupabaseClient {
  if (!cachedClient) {
    const url = process.env.SUPABASE_URL;
    const serviceRoleKey = process.env.SUPABASE_SERVICE_ROLE_KEY;
    if (!url || !serviceRoleKey) {
      throw new Error(
        "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in the environment for check_policy_coverage to run.",
      );
    }
    cachedClient = createClient(url, serviceRoleKey);
  }
  return cachedClient;
}

const PolicyRowSchema = z.object({
  status: PolicyStatusSchema,
  coverage_limits: z.partialRecord(PerilSchema, z.number().nonnegative()),
});

export async function checkPolicyCoverage(
  policyNumber: string,
  peril: Peril,
): Promise<CheckPolicyCoverageOutput> {
  const policyNumberResult = PolicyNumberSchema.safeParse(policyNumber);
  if (!policyNumberResult.success) {
    throw new Error(`Invalid policy number "${policyNumber}": must match POL-XXXXXX`);
  }

  const supabase = getSupabaseClient();

  const { data, error } = await supabase
    .from("policies")
    .select("status, coverage_limits")
    .eq("policy_number", policyNumberResult.data)
    .maybeSingle();

  if (error) {
    throw new Error(`check_policy_coverage query failed: ${error.message}`);
  }

  if (!data) {
    return { found: false };
  }

  const row = PolicyRowSchema.parse(data);
  return {
    found: true,
    status: row.status,
    limit: row.coverage_limits[peril] ?? null,
  };
}
