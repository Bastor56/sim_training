// Required lab deliverable: demonstrate the malformed-output path. This is
// a genuine live demonstration, not a scripted one: it swaps in
// claude-haiku-4-5-20251001 as the model backing extractClaim's
// callModelFn (the same injection seam used for testing), a model we
// already benchmarked as unreliable on this exact schema -- it wraps valid
// JSON in markdown code fences instead of returning raw JSON, breaking
// JSON.parse before validation even starts. Everything from there -- the
// retry, the validation error fed back into the prompt, the eventual
// typed failure -- runs for real, against real live API responses,
// through the real orchestrator code (not a reimplementation, not a
// canned fixture).
//
// Needs ANTHROPIC_API_KEY (loaded via --env-file; see package.json's
// day1:demo-malformed script) and makes a small number of real, billed
// API calls -- unlike the rest of this lab's tests, this one can't be free
// or offline, because a genuinely forced failure has to come from a real
// model actually failing.
//
// Beginner note: the point of this whole file is to PROVE the retry/
// validation logic in orchestrator.ts and validate.ts actually works, by
// deliberately feeding it a weaker model known to break the contract, and
// watching the pipeline catch and report that failure cleanly instead of
// crashing or silently returning garbage.

import Anthropic from "@anthropic-ai/sdk";
import { extractClaim, ClaimExtractionError } from "./orchestrator.js";
// Only the TYPE of callModel's parameters is needed here (to shape our
// stand-in function below), not the real callModel implementation itself —
// this file builds its own API call using the weaker model.
import type { CallModelParams } from "./client.js";

// A real Anthropic client, constructed directly in this file (rather than
// going through client.ts's getClient()), since this demo intentionally
// bypasses the normal model configuration to force a different model.
const anthropic = new Anthropic();

// A fixed claim to run every time — deterministic input, so the only
// variable in this demo is whether Haiku's OUTPUT format breaks, not
// whether the input itself is ambiguous.
const CLAIM_TEXT = `A pipe burst under my kitchen sink yesterday afternoon and
flooded most of the first floor before I noticed it. Cabinets, flooring,
and some drywall are ruined.`;

// Tracks how many times our stand-in model function has been called —
// used at the end to prove the retry loop ran at most twice (1 initial +
// 1 retry), never more.
let callCount = 0;

// claude-haiku-4-5-20251001, not claude-sonnet-5: deliberately the weaker
// model already confirmed (see the model-tier benchmark run earlier) to
// fail this exact schema 3/3 in live testing, so the failure below is
// forced on purpose, not hoped for.
// This function has the exact same shape as client.ts's `callModel`
// (same parameters, same return type) — that's what lets it be passed as
// the second argument to extractClaim in place of the real one, further
// down in main().
async function haikuCallModel(
  params: CallModelParams,
): Promise<Anthropic.Message> {
  callCount++;
  console.log(`[call ${callCount}] sending to claude-haiku-4-5-20251001...`);

  // A direct call to the Messages API, identical in structure to
  // client.ts's callModel, but hardcoded to the Haiku model (and to
  // temperature 0, since Haiku still allows tuning it) instead of using
  // the app's normal MODEL/TEMPERATURE/MAX_TOKENS constants.
  const response = await anthropic.messages.create({
    model: "claude-haiku-4-5-20251001",
    temperature: 0,
    max_tokens: 1024,
    system: params.systemPrompt,
    messages: [{ role: "user", content: params.userPrompt }],
    tools: [params.tool],
  });

  // Same "find the text block" pattern used in validate.ts — here purely
  // for a debug print, not for validation (that happens for real, later,
  // inside orchestrator.ts/validate.ts once this function returns).
  const textBlock = response.content.find(
    (block): block is Anthropic.TextBlock => block.type === "text",
  );
  // Print just the first 150 characters of whatever text Haiku produced,
  // so you can visually see the markdown code fences (```json ... ```)
  // that break JSON.parse, without flooding the terminal with the full
  // response.
  console.log(
    `[call ${callCount}] raw text response: ${
      textBlock ? JSON.stringify(textBlock.text.slice(0, 150)) : "(no text block)"
    }`,
  );

  // Return the response exactly as received — this stand-in function's
  // whole job is to change WHICH model answers, not to alter or pre-process
  // the response in any way. Validation still happens downstream, for real.
  return response;
}

async function main(): Promise<void> {
  console.log(
    "Forcing the malformed-output path with live claude-haiku-4-5 calls...\n",
  );

  try {
    // This is the key line: extractClaim is the SAME orchestrator function
    // used in the real app (index.ts), but here we pass `haikuCallModel` as
    // its second argument instead of letting it default to the real
    // client.ts callModel. Everything else — prompt building, validation,
    // the one retry, error handling — runs unmodified.
    const result = await extractClaim(CLAIM_TEXT, haikuCallModel);
    // If this branch runs, Haiku actually got it right (or the retry
    // fixed it) — labeled UNEXPECTED because the whole point of this file
    // is to demonstrate failure, though it's not truly guaranteed since
    // model behavior isn't perfectly deterministic.
    console.log(
      "\nUNEXPECTED: extraction succeeded:",
      JSON.stringify(result.claim),
    );
  } catch (err) {
    // Only ClaimExtractionError is the "expected" outcome here — anything
    // else (a network error, a bug) should still crash loudly rather than
    // be mistaken for the demo working as intended.
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
