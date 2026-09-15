// Validation: takes the raw model response and checks it against the schema
// layer's contracts. Never throws — every outcome, success or failure, is a
// plain discriminated result.

import type Anthropic from "@anthropic-ai/sdk";
import type { z } from "zod";
import {
  ClaimSchema,
  CHECK_POLICY_COVERAGE_TOOL,
  CheckPolicyCoverageInputSchema,
  type Claim,
  type CheckPolicyCoverageInput,
} from "./schema.js";

export type ValidationStage =
  | "no_text_block"
  | "json_parse"
  | "claim_schema"
  | "no_tool_call"
  | "wrong_tool_name"
  | "tool_schema";

export interface ValidationSuccess {
  valid: true;
  claim: Claim;
  toolInput: CheckPolicyCoverageInput;
}

export interface ValidationFailure {
  valid: false;
  stage: ValidationStage;
  message: string;
  rawText?: string;
}

export type ValidationResult = ValidationSuccess | ValidationFailure;

function formatZodError(error: z.ZodError): string {
  return error.issues
    .map((issue) => `${issue.path.join(".") || "(root)"}: ${issue.message}`)
    .join("; ");
}

export function validateModelResponse(
  response: Anthropic.Message,
): ValidationResult {
  const textBlock = response.content.find(
    (block): block is Anthropic.TextBlock => block.type === "text",
  );
  if (!textBlock || !textBlock.text.trim()) {
    return {
      valid: false,
      stage: "no_text_block",
      message:
        "The response did not include a text block containing the claim JSON.",
    };
  }

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

  const claimResult = ClaimSchema.safeParse(parsedJson);
  if (!claimResult.success) {
    return {
      valid: false,
      stage: "claim_schema",
      message: `The claim JSON did not match the required schema: ${formatZodError(claimResult.error)}`,
      rawText: textBlock.text,
    };
  }

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
  if (toolUseBlock.name !== CHECK_POLICY_COVERAGE_TOOL.name) {
    return {
      valid: false,
      stage: "wrong_tool_name",
      message: `Expected a call to "${CHECK_POLICY_COVERAGE_TOOL.name}" but got "${toolUseBlock.name}".`,
      rawText: textBlock.text,
    };
  }

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

  return {
    valid: true,
    claim: claimResult.data,
    toolInput: toolInputResult.data,
  };
}
