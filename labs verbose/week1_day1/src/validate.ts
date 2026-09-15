// Validation: takes the raw model response and checks it against the schema
// layer's contracts before anything downstream touches it. Never throws —
// every outcome, success or failure, is a plain discriminated result, so a
// malformed response is data the orchestrator can retry or log, not an
// exception it has to catch.

import type Anthropic from "@anthropic-ai/sdk";
import type { z } from "zod";
import {
  ClaimSchema,
  CHECK_POLICY_COVERAGE_TOOL,
  CheckPolicyCoverageInputSchema,
  type Claim,
  type CheckPolicyCoverageInput,
} from "./schema.js";

// A union of short string codes, one per place validation can fail. Having
// this as its own type (rather than just a free-form message) lets calling
// code branch on WHICH stage failed if it wants to, not just parse a
// sentence.
export type ValidationStage =
  | "no_text_block" // the response had no plain-text content at all
  | "json_parse" // the text wasn't valid JSON
  | "claim_schema" // the JSON parsed, but didn't match ClaimSchema's shape
  | "no_tool_call" // the model never called check_policy_coverage
  | "wrong_tool_name" // the model called a different tool than expected
  | "tool_schema"; // the tool call's arguments didn't match the input schema

// The two possible outcomes of validation are modeled as a TypeScript
// "discriminated union": both interfaces share a `valid` field, but with
// different literal values (`true` vs `false`). Once you check
// `result.valid`, TypeScript automatically narrows which other fields are
// available — this is the same pattern used for CheckPolicyCoverageOutput
// in schema.ts.
export interface ValidationSuccess {
  valid: true;
  claim: Claim;
  toolInput: CheckPolicyCoverageInput;
}

export interface ValidationFailure {
  valid: false;
  stage: ValidationStage;
  // Human-readable and safe to feed straight back into a retry prompt.
  message: string;
  // Optional: the raw text the model produced, when there was any — useful
  // both for logging and for showing the model its own broken output in a
  // retry prompt (see orchestrator.ts's buildRetryUserPrompt).
  rawText?: string;
}

export type ValidationResult = ValidationSuccess | ValidationFailure;

// Zod validation errors come back as a list of individual "issues" (one
// per field that failed); this turns that list into one readable sentence,
// e.g. "peril: Invalid enum value; loss_date: must be an ISO date".
function formatZodError(error: z.ZodError): string {
  return error.issues
    .map((issue) => `${issue.path.join(".") || "(root)"}: ${issue.message}`)
    .join("; ");
}

// The main validation function. It walks through every requirement in
// order and returns as soon as ANY of them fails — this is sometimes
// called a "guard clause" style: handle the failure case immediately and
// return, rather than nesting deeper into more and more if-blocks.
export function validateModelResponse(
  response: Anthropic.Message,
): ValidationResult {
  // A Claude API response's `content` is an array of "blocks" — a single
  // response can mix plain text blocks and tool_use blocks together. Here
  // we look for the first block whose `type` is "text". The `(block):
  // block is Anthropic.TextBlock =>` part is a TypeScript "type predicate"
  // — it tells TypeScript that once `.find` returns a match, that value is
  // specifically a TextBlock (not just some generic block), so its `.text`
  // property is safe to access below.
  const textBlock = response.content.find(
    (block): block is Anthropic.TextBlock => block.type === "text",
  );
  // Two ways this can fail: no text block was found at all, OR it was
  // found but empty/whitespace-only (`.trim()` strips whitespace so a
  // string of just spaces still counts as "no text").
  if (!textBlock || !textBlock.text.trim()) {
    return {
      valid: false,
      stage: "no_text_block",
      message:
        "The response did not include a text block containing the claim JSON.",
    };
  }

  // Step 1 of validating the text block: is it even parseable as JSON at
  // all? A model might return something that looks close to JSON but has
  // a syntax error (trailing comma, unescaped quote, markdown fences
  // wrapped around it, etc.) — that would throw here.
  let parsedJson: unknown;
  try {
    parsedJson = JSON.parse(textBlock.text);
  } catch (err) {
    return {
      valid: false,
      stage: "json_parse",
      message: `The claim JSON could not be parsed: ${(err as Error).message}`,
      rawText: textBlock.text,
    };
  }

  // Step 2: now that we have SOME parsed JSON value, does it actually match
  // the Claim shape (right fields, right types, right enum values)? Note
  // this is a completely separate failure mode from "invalid JSON" above —
  // `{"foo": "bar"}` parses fine but would fail here.
  const claimResult = ClaimSchema.safeParse(parsedJson);
  if (!claimResult.success) {
    return {
      valid: false,
      stage: "claim_schema",
      message: `The claim JSON did not match the required schema: ${formatZodError(claimResult.error)}`,
      rawText: textBlock.text,
    };
  }

  // The claim JSON was valid — now check the OTHER thing the model was
  // asked to do this turn: call the check_policy_coverage tool. Again we
  // search `response.content` for a block of a particular type, this time
  // "tool_use".
  const toolUseBlock = response.content.find(
    (block): block is Anthropic.ToolUseBlock => block.type === "tool_use",
  );
  if (!toolUseBlock) {
    return {
      valid: false,
      stage: "no_tool_call",
      message: `The response did not call the required "${CHECK_POLICY_COVERAGE_TOOL.name}" tool.`,
      rawText: textBlock.text,
    };
  }
  // Even if SOME tool was called, make sure it's the specific one we
  // declared — a model could theoretically hallucinate a tool name, or
  // (in an app with multiple tools available) call the wrong one.
  if (toolUseBlock.name !== CHECK_POLICY_COVERAGE_TOOL.name) {
    return {
      valid: false,
      stage: "wrong_tool_name",
      message: `Expected a call to "${CHECK_POLICY_COVERAGE_TOOL.name}" but got "${toolUseBlock.name}".`,
      rawText: textBlock.text,
    };
  }

  // Finally, check that the ARGUMENTS the model passed to the tool call
  // (toolUseBlock.input, a raw JS object from the API) match
  // CheckPolicyCoverageInputSchema — i.e. that `peril` is present and is
  // one of the allowed enum values.
  const toolInputResult = CheckPolicyCoverageInputSchema.safeParse(
    toolUseBlock.input,
  );
  if (!toolInputResult.success) {
    return {
      valid: false,
      stage: "tool_schema",
      message: `The "${CHECK_POLICY_COVERAGE_TOOL.name}" call had invalid input: ${formatZodError(toolInputResult.error)}`,
      rawText: textBlock.text,
    };
  }

  // Every check passed: return a success result carrying both validated
  // pieces (the claim object and the tool's input) that the orchestrator
  // and index.ts can now safely use.
  return {
    valid: true,
    claim: claimResult.data,
    toolInput: toolInputResult.data,
  };
}
