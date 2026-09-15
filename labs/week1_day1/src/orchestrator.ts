// Orchestrator: assembles the three pieces of the request: system prompt,
// user prompt, and tool definition. Owns the loop back to the client on
// invalid output and logs the raw response alongside the parsed result
// on every attempt.

import pino from "pino";
import type Anthropic from "@anthropic-ai/sdk";
import { callModel as defaultCallModel } from "./client.js";
import {
  validateModelResponse,
  type ValidationFailure,
  type ValidationResult,
} from "./validate.js";
import {
  CHECK_POLICY_COVERAGE_TOOL,
  type Claim,
  type CheckPolicyCoverageInput,
} from "./schema.js";

const logger = pino({ name: "fnol-orchestrator" });

// System prompt
function buildSystemPrompt(today: Date): string {
  const todayIso = today.toISOString().slice(0, 10);
  return `You are a first-notice-of-loss (FNOL) intake assistant for a property & casualty insurer.

Today's date is ${todayIso}. Use it to resolve relative or partial dates in the claim (e.g. "yesterday," "last Tuesday," "Sept 13th" with no year given) into an absolute date.

Given an unstructured claim description, do two things in a single turn:

1. Respond with a single JSON object as your text output, matching exactly this shape:
   {
     "loss_date": string in YYYY-MM-DD format, or null if the description does not state or clearly imply a date,
     "peril": one of "fire" | "water" | "wind" | "hail" | "theft" | "vandalism" | "liability" | "collision" | "flood" | "other",
     "estimated_severity": one of "minor" | "moderate" | "severe" | "total_loss" — your best-effort read of how serious the described loss is,
     "coverage_flag": true or false — your own preliminary judgment on whether a loss like this is plausibly covered, based only on the peril and whatever the claim text says. Do not wait for a tool result to set this.
   }
   Output only that JSON object as your text response: no markdown fences, no commentary before or after it.

2. Call the check_policy_coverage tool exactly once, passing the peril you identified, so the caller's policy can be checked for coverage of that specific peril.`;
}

// User prompt, built per request from the raw claim text
function buildUserPrompt(claimText: string): string {
  return `Claim description:\n"""\n${claimText.trim()}\n"""`;
}

function buildRetryUserPrompt(
  claimText: string,
  failure: ValidationFailure,
): string {
  const previousText = failure.rawText
    ? `\n\nYour previous response text was:\n"""\n${failure.rawText}\n"""`
    : "";
  return (
    `${buildUserPrompt(claimText)}\n\n` +
    `Your previous response was invalid: ${failure.message}${previousText}\n\n` +
    `Produce a corrected response that fixes this specific issue and satisfies all requirements above.`
  );
}

// Tool definition, imported as-is from the schema layer
export interface AttemptLog {
  attempt: number;
  rawResponse: Anthropic.Message;
  result: ValidationResult;
}

export interface OrchestrationResult {
  claim: Claim;
  toolInput: CheckPolicyCoverageInput;
  attempts: AttemptLog[];
}

export class ClaimExtractionError extends Error {
  constructor(
    message: string,
    public readonly attempts: AttemptLog[],
  ) {
    super(message);
    this.name = "ClaimExtractionError";
  }
}

// One initial attempt plus exactly one retry on invalid output.
const MAX_ATTEMPTS = 2;

export async function extractClaim(
  claimText: string,
  callModelFn: typeof defaultCallModel = defaultCallModel,
): Promise<OrchestrationResult> {
  const attempts: AttemptLog[] = [];
  const systemPrompt = buildSystemPrompt(new Date());
  let userPrompt = buildUserPrompt(claimText);

  for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt++) {
    const rawResponse = await callModelFn({
      systemPrompt,
      userPrompt,
      tool: CHECK_POLICY_COVERAGE_TOOL,
    });

    const result = validateModelResponse(rawResponse);
    attempts.push({ attempt, rawResponse, result });

    logger.info(
      { attempt, raw: rawResponse, result },
      result.valid
        ? "model response validated"
        : "model response failed validation",
    );

    if (result.valid) {
      return { claim: result.claim, toolInput: result.toolInput, attempts };
    }

    userPrompt = buildRetryUserPrompt(claimText, result);
  }

  const lastAttempt = attempts[attempts.length - 1]!;
  const lastResult = lastAttempt.result as ValidationFailure;

  logger.error({ attempts }, "claim extraction failed after retry");

  throw new ClaimExtractionError(
    `Claim extraction failed after ${MAX_ATTEMPTS} attempts. Last error (${lastResult.stage}): ${lastResult.message}`,
    attempts,
  );
}
