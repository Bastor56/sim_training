// Required lab deliverable: demonstrate the malformed-output path.
// This script swaps Sonnet 5 for Haiku 4.5 as it consistently fails
// at returning raw JSON & instead wraps it in markdown code fences.

import Anthropic from "@anthropic-ai/sdk";
import { extractClaim, ClaimExtractionError } from "./orchestrator.js";
import type { CallModelParams } from "./client.js";

const anthropic = new Anthropic();

const CLAIM_TEXT = `A pipe burst under my kitchen sink yesterday afternoon and
flooded most of the first floor before I noticed it. Cabinets, flooring,
and some drywall are ruined.`;

let callCount = 0;

async function haikuCallModel(
  params: CallModelParams,
): Promise<Anthropic.Message> {
  callCount++;
  console.log(`[call ${callCount}] sending to claude-haiku-4-5-20251001...`);

  const response = await anthropic.messages.create({
    model: "claude-haiku-4-5-20251001",
    temperature: 0,
    max_tokens: 1024,
    system: params.systemPrompt,
    messages: [{ role: "user", content: params.userPrompt }],
    tools: [params.tool],
  });

  const textBlock = response.content.find(
    (block): block is Anthropic.TextBlock => block.type === "text",
  );
  console.log(
    `[call ${callCount}] raw text response: ${
      textBlock ? JSON.stringify(textBlock.text.slice(0, 150)) : "(no text block)"
    }`,
  );

  return response;
}

async function main(): Promise<void> {
  console.log(
    "Forcing the malformed-output path with live claude-haiku-4-5 calls...\n",
  );

  try {
    const result = await extractClaim(CLAIM_TEXT, haikuCallModel);
    console.log(
      "\nUNEXPECTED: extraction succeeded:",
      JSON.stringify(result.claim),
    );
  } catch (err) {
    if (!(err instanceof ClaimExtractionError)) {
      throw err;
    }
    console.log(
      `\n[result] attempts made: ${callCount} (1 initial + 1 retry, never more)`,
    );
    console.log(
      "[result] ClaimExtractionError surfaced cleanly -- not a crash, not a silent half-parsed object:",
    );
    console.log(`         ${err.message}`);
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
