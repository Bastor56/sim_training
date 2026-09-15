// Orchestrator: assembles the three inspectable pieces of the request
// (system prompt, user prompt, tool definition), owns the one loop-back
// arrow in the architecture (validation -> client, on invalid output only),
// and logs the raw response alongside the parsed result on every attempt so
// a failure can be diagnosed after the fact without re-running the request.
//
// Deliberately NOT using the Anthropic API's native output_config/JSON-schema
// structured-output mode: if the provider enforced the schema itself, our
// Zod validation below would never catch anything in live use, which works
// against the lab's actual point (feeling where the model does and doesn't
// follow a schema). The contract is validated in our code, per the lab's
// tech-stack line, not upstream.
//
// Note what's deliberately absent: the caller's policy number. It's known
// out-of-band (an authenticated session, a CRM record) before the claim
// narrative is ever captured, not something a claimant recites in free
// text — so it never enters the prompt and the model never sees it. The
// caller combines the known policy number with this function's toolInput
// (the peril the model identified) when it actually runs the tool; see
// handler.ts and index.ts.
//
// Beginner map of this file: this is the "brain" of the agentic loop.
// It doesn't call the API directly (client.ts does that) and it doesn't
// check the output itself (validate.ts does that) — its whole job is to
// build prompts, call the client, hand the response to the validator, and
// decide whether to stop (success), retry (once), or give up (throw).

import pino from "pino";
// `import type` here means we only need Anthropic's TypeScript types
// (like the shape of a Message), not any of its runtime code — this file
// never constructs an Anthropic client itself.
import type Anthropic from "@anthropic-ai/sdk";
// Renamed on import (`as defaultCallModel`) so that later in this file we
// can accept an alternate implementation as a function parameter (used for
// testing and for the deliberately-broken demo in demo-malformed.ts)
// without shadowing the name.
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

// Piece 1 of 3: the system prompt. Built once per extractClaim call (same
// reference date across both attempts) rather than a fixed string: without
// "today," the model has no basis for resolving a partial or relative date
// like "Sept 13th" or "yesterday" and will guess an arbitrary year.
// This is the "system prompt" — instructions that set the model's role and
// the rules it must follow for the whole conversation, as opposed to the
// "user prompt" below, which carries the actual claim being processed.
// Passing `today` in (instead of calling `new Date()` inline here) means
// both the first attempt and the retry attempt see the exact same date,
// even if a retry happens a few seconds later.
function buildSystemPrompt(today: Date): string {
  // `.toISOString()` gives e.g. "2026-09-15T00:00:00.000Z"; `.slice(0, 10)`
  // keeps just the "2026-09-15" date portion.
  const todayIso = today.toISOString().slice(0, 10);
  // A template literal (backticks) building one long prompt string. Every
  // line here is a direct instruction to the model — this is where the
  // "contract" the model must follow is spelled out in plain English, and
  // it should match, field for field, what ClaimSchema in schema.ts
  // actually checks for.
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

// Piece 2 of 3: the user prompt, built per request from the raw claim text.
// The "user prompt" is the actual content for this turn — here, just the
// claimant's free-text description, wrapped in triple-quotes so the model
// can clearly tell where the claim text starts and ends. `.trim()` strips
// any accidental leading/trailing whitespace from the input.
function buildUserPrompt(claimText: string): string {
  return `Claim description:\n"""\n${claimText.trim()}\n"""`;
}

// Builds the SECOND user prompt, used only on a retry after the first
// attempt's output failed validation. It reuses buildUserPrompt for the
// original claim text, then appends the specific validation failure
// (`failure.message`) and, when available, the model's own broken output
// (`failure.rawText`) — showing the model exactly what it got wrong is far
// more effective than just asking it to "try again."
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

// Piece 3 of 3: the tool definition, imported as-is from the schema layer
// (CHECK_POLICY_COVERAGE_TOOL) rather than redefined here.

// Describes everything about ONE attempt, kept around for logging/
// debugging: which attempt number it was, the complete raw API response,
// and the validation result computed from it.
export interface AttemptLog {
  attempt: number;
  rawResponse: Anthropic.Message;
  result: ValidationResult;
}

// What extractClaim returns on success: the validated claim fields, the
// validated tool-call input (the peril to check coverage for), and the
// full history of every attempt it took to get there (useful for
// debugging/auditing even when it succeeded on the first try).
export interface OrchestrationResult {
  claim: Claim;
  toolInput: CheckPolicyCoverageInput;
  attempts: AttemptLog[];
}

// A custom Error subclass (`extends Error`) so callers can use
// `instanceof ClaimExtractionError` (see index.ts) to distinguish "the
// model never produced valid output" from any other kind of failure. It
// also carries the full `attempts` array so the caller can inspect exactly
// what went wrong, not just read a message string.
export class ClaimExtractionError extends Error {
  constructor(
    message: string,
    // `public readonly` in a constructor parameter is TypeScript shorthand
    // for "declare this as a public, read-only property on the class AND
    // assign the constructor argument to it" — equivalent to writing
    // `this.attempts = attempts` in the body.
    public readonly attempts: AttemptLog[],
  ) {
    super(message);
    this.name = "ClaimExtractionError";
  }
}

// One initial attempt plus exactly one retry, per the lab's requirement —
// never more.
const MAX_ATTEMPTS = 2;

// The heart of the agentic loop. `callModelFn` defaults to the real
// client.ts implementation, but can be swapped out (dependency injection)
// for tests or for demo-malformed.ts's deliberately-unreliable model.
export async function extractClaim(
  claimText: string,
  callModelFn: typeof defaultCallModel = defaultCallModel,
): Promise<OrchestrationResult> {
  // Accumulates a log entry for every attempt made, successful or not.
  const attempts: AttemptLog[] = [];
  // Built once, outside the loop, so both attempts share the same "today."
  const systemPrompt = buildSystemPrompt(new Date());
  // `let` because this gets REPLACED with a different prompt (including
  // the failure explanation) if the first attempt fails and we loop again.
  let userPrompt = buildUserPrompt(claimText);

  // Runs at most twice: attempt 1 (the normal try) and, only if needed,
  // attempt 2 (the single retry).
  for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt++) {
    // Make the actual API call — this is the only place in this function
    // that talks to the model.
    const rawResponse = await callModelFn({
      systemPrompt,
      userPrompt,
      tool: CHECK_POLICY_COVERAGE_TOOL,
    });

    // Hand the raw response to the validator — this function never
    // inspects rawResponse's contents itself, it delegates that entirely
    // to validate.ts, keeping this file focused on orchestration/flow
    // control.
    const result = validateModelResponse(rawResponse);
    attempts.push({ attempt, rawResponse, result });

    // Log every attempt — success or failure — with both the raw response
    // and the parsed result, so a failure can be diagnosed later from logs
    // alone, without needing to reproduce it live.
    logger.info(
      { attempt, raw: rawResponse, result },
      result.valid
        ? "model response validated"
        : "model response failed validation",
    );

    // Success: stop looping immediately and return the validated data.
    if (result.valid) {
      return { claim: result.claim, toolInput: result.toolInput, attempts };
    }

    // Failure: build a new user prompt that includes the specific
    // validation error and the model's own broken output, then loop
    // around to try again (if attempts remain).
    userPrompt = buildRetryUserPrompt(claimText, result);
  }

  // If we reach this line, the loop ran MAX_ATTEMPTS times and never
  // returned — every attempt failed validation. `attempts[attempts.length
  // - 1]` grabs the last (most recent) attempt; the trailing `!` is a
  // TypeScript "non-null assertion," telling the compiler "trust me, this
  // array is definitely not empty here" (true, since the loop always
  // pushes at least one entry before this line can run).
  const lastAttempt = attempts[attempts.length - 1]!;
  // We know this cast is safe: if we got here, the loop never hit the
  // `result.valid` early-return, so the last result must be a
  // ValidationFailure, not a ValidationSuccess.
  const lastResult = lastAttempt.result as ValidationFailure;

  logger.error({ attempts }, "claim extraction failed after retry");

  // Surface a clean, typed failure to the caller (index.ts) instead of
  // returning a half-valid object or letting a raw parsing exception leak
  // out. `lastResult.stage` is the specific ValidationStage code from
  // validate.ts, embedded in the message for quick diagnosis.
  throw new ClaimExtractionError(
    `Claim extraction failed after ${MAX_ATTEMPTS} attempts. Last error (${lastResult.stage}): ${lastResult.message}`,
    attempts,
  );
}
