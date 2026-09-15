// Schema layer: The source of truth for the model's structured output and
// the one declated tool

import { z } from "zod";
import type Anthropic from "@anthropic-ai/sdk";

// --- Shared domain vocabulary ------------------------------------------

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
export const PerilSchema = z.enum(PERILS);
export type Peril = z.infer<typeof PerilSchema>;
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

export const ESTIMATED_SEVERITIES = [
  "minor",
  "moderate",
  "severe",
  "total_loss",
] as const;
export const EstimatedSeveritySchema = z.enum(ESTIMATED_SEVERITIES);
export type EstimatedSeverity = z.infer<typeof EstimatedSeveritySchema>;

export const ClaimSchema = z.object({
  loss_date: z
    .string()
    .regex(/^\d{4}-\d{2}-\d{2}$/, "must be an ISO date (YYYY-MM-DD)")
    .nullable(),
  peril: PerilSchema,
  estimated_severity: EstimatedSeveritySchema,
  coverage_flag: z.boolean(),
});
export type Claim = z.infer<typeof ClaimSchema>;

// --- check_policy_coverage tool ------------------------------------------

export const CheckPolicyCoverageInputSchema = z.object({
  peril: PerilSchema,
});
export type CheckPolicyCoverageInput = z.infer<
  typeof CheckPolicyCoverageInputSchema
>;

// Output
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
// and a docstring
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
        enum: [...PERILS],
        description: "The peril identified in the claim description.",
      },
    },
    required: ["peril"],
  },
};
