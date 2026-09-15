// Schema layer: the single source of truth for what "valid" means, for both
// the model's structured output (the claim response contract) and the one
// declared tool (check_policy_coverage). Nothing outside this file should
// redefine these shapes.

import { z } from "zod";
// `import type` pulls in ONLY the TypeScript type information from the SDK
// (erased entirely at compile time) — we're not using any of the SDK's
// runtime code in this file, just borrowing its `Anthropic.Tool` type to
// describe our tool definition below.
import type Anthropic from "@anthropic-ai/sdk";

// --- Shared domain vocabulary ------------------------------------------

// A fixed taxonomy, not a free string: an unconstrained peril field would
// validate against almost anything the model emits, which defeats the point
// of validating structured output at all.
// `as const` locks this array down to its exact literal values (instead of
// widening to `string[]`), which is what lets z.enum below build a precise
// union type of exactly these strings.
export const PERILS = [
  "fire",
  "water",
  "wind",
  "hail",
  "theft",
  "vandalism",
  "liability",
  "collision",
  "flood",
  "other",
] as const;
// z.enum(...) builds a Zod schema that only accepts one of these exact
// strings — anything else fails validation.
export const PerilSchema = z.enum(PERILS);
// z.infer<typeof X> derives a plain TypeScript type from a Zod schema, so
// the runtime check (PerilSchema) and the compile-time type (Peril) can
// never drift apart — they're generated from the same definition.
export type Peril = z.infer<typeof PerilSchema>;

// Matches the seed data convention in supabase/seed.sql (POL-XXXXXX). The
// policy number is known out-of-band (the intake channel's authenticated
// session, a CRM record, an agent's screen) — it is never extracted from or
// exposed to the model. This schema exists purely to validate that known
// value at the boundary where it enters the pipeline (see orchestrator.ts).
// A regular expression: ^ and $ anchor to start/end of the string, "POL-"
// must appear literally, followed by exactly 6 digits (\d{6}).
export const POLICY_NUMBER_PATTERN = /^POL-\d{6}$/;
export const PolicyNumberSchema = z
  .string()
  .regex(POLICY_NUMBER_PATTERN, "must match POL-XXXXXX");

export const POLICY_STATUSES = [
  "active",
  "lapsed",
  "cancelled",
  "pending",
] as const;
export const PolicyStatusSchema = z.enum(POLICY_STATUSES);
export type PolicyStatus = z.infer<typeof PolicyStatusSchema>;

// --- Claim response contract --------------------------------------------
// What the model's structured output must satisfy. estimated_severity is a
// bucket rather than a dollar figure: a raw number extracted from
// unstructured text would be false precision the model is just inventing.
// No policy_number field: that's known context supplied to the pipeline,
// not something extracted from the claim narrative.

export const ESTIMATED_SEVERITIES = [
  "minor",
  "moderate",
  "severe",
  "total_loss",
] as const;
export const EstimatedSeveritySchema = z.enum(ESTIMATED_SEVERITIES);
export type EstimatedSeverity = z.infer<typeof EstimatedSeveritySchema>;

// This is the full contract for the JSON object the model must produce as
// its TEXT response (separate from, and in addition to, the tool call it
// also has to make — see CHECK_POLICY_COVERAGE_TOOL below). Every field
// here mirrors one line of the instructions in orchestrator.ts's system
// prompt — the prompt tells the model what to produce, and this schema is
// how we check it actually did.
export const ClaimSchema = z.object({
  // Nullable rather than a forced guess: the source text may only give a
  // relative or absent date ("last week," no date at all).
  loss_date: z
    .string()
    .regex(/^\d{4}-\d{2}-\d{2}$/, "must be an ISO date (YYYY-MM-DD)")
    .nullable(),
  peril: PerilSchema,
  estimated_severity: EstimatedSeveritySchema,
  // The model's own preliminary read on coverage from the claim text alone —
  // not reconciled against the tool result in this single-request pass.
  coverage_flag: z.boolean(),
});
// The TypeScript type for a fully-validated claim object — this is what
// flows through the rest of the app once validate.ts confirms the model's
// raw JSON actually matches this shape.
export type Claim = z.infer<typeof ClaimSchema>;

// --- check_policy_coverage tool ------------------------------------------
// Deliberately narrow: the only argument the model supplies is the peril it
// identified from the claim text — the one thing it's actually in a
// position to judge. The policy number the query also needs is bound
// server-side from known context when the handler executes the call; the
// model never sees or supplies it.

// This schema validates the ARGUMENTS the model passes when it calls the
// tool (as opposed to ClaimSchema above, which validates the model's plain
// text JSON response). Two separate contracts for two separate outputs the
// model produces in the same turn.
export const CheckPolicyCoverageInputSchema = z.object({
  peril: PerilSchema,
});
export type CheckPolicyCoverageInput = z.infer<
  typeof CheckPolicyCoverageInputSchema
>;

// Output: never sent to the model (this design has no second round-trip
// feeding tool results back in) but typed here so handler.ts and its caller
// share one contract instead of inventing their own shapes. `limit: null`
// means this specific peril isn't in the policy's coverage schedule at all,
// independent of whether the policy is currently active.
// z.discriminatedUnion picks between two possible object shapes based on
// the value of one shared field (`found`) — TypeScript then knows that
// wherever `found` is `true`, `status` and `limit` are guaranteed to exist,
// and wherever it's `false`, they don't.
export const CheckPolicyCoverageOutputSchema = z.discriminatedUnion("found", [
  z.object({
    found: z.literal(true),
    status: PolicyStatusSchema,
    limit: z.number().nonnegative().nullable(),
  }),
  z.object({
    found: z.literal(false),
  }),
]);
export type CheckPolicyCoverageOutput = z.infer<
  typeof CheckPolicyCoverageOutputSchema
>;

// The tool declaration handed to the model: name, typed parameter schema,
// and a docstring it can actually route on. This is the exactly-one tool
// required by the lab.
// This is a plain JSON object (following Anthropic's `Tool` shape) — NOT a
// Zod schema — because it's sent directly to the API as part of the
// request. The model reads `description` to decide when/how to call the
// tool, and `input_schema` (JSON Schema format, a different spec from Zod)
// tells it exactly what arguments are valid.
export const CHECK_POLICY_COVERAGE_TOOL: Anthropic.Tool = {
  name: "check_policy_coverage",
  description:
    "Check whether the caller's policy covers a specific peril, and return " +
    "the policy's current status (active, lapsed, cancelled, or pending) " +
    "and the coverage limit for that peril. Call this exactly once, " +
    "passing the peril you identified in the claim description.",
  input_schema: {
    type: "object",
    properties: {
      peril: {
        type: "string",
        // Restating the PERILS list here (in JSON Schema form) is what
        // actually constrains the model at the API level — the model
        // literally cannot pass a value outside this enum for a tool call.
        enum: [...PERILS],
        description: "The peril identified in the claim description.",
      },
    },
    required: ["peril"],
  },
};
