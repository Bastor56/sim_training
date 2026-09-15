// Client layer: owns the Anthropic API call and the model configuration.
// It knows nothing about parsing, validation, retries, or the tool's real
// implementation — it takes a system prompt, a user prompt, and a tool
// definition as three separate arguments, and returns the raw response
// untouched. Retries (on invalid output) and logging live one layer up, in
// the orchestrator, so this file stays a single, inspectable API call.

// The official Anthropic SDK — this is the library that actually sends
// HTTP requests to Claude's API and gives back typed responses.
import Anthropic from "@anthropic-ai/sdk";

// Sonnet, not Opus or Haiku: this is a bounded extraction-plus-one-tool-call
// task, not open-ended reasoning, so Opus's extra cost buys nothing here —
// but it still needs Sonnet-level instruction-following to hold the claim
// schema reliably, which is exactly the thing Haiku is more likely to drop
// (confirmed empirically: Haiku failed this exact schema 3/3 in testing).
// This string is the exact model ID the API expects — think of it as
// picking which "brain" answers the request.
const MODEL = "claude-sonnet-5";

// Set to 1, the only value this model accepts: Claude models released after
// Opus 4.6 (claude-sonnet-5 included) have deprecated `temperature` — the
// SDK rejects every value except 1.0 with a 400. We'd have wanted 0 for a
// deterministic extraction task, but that lever no longer exists here; 1 is
// set explicitly (rather than omitted) so the deprecation is visible in the
// request instead of silently absent.
// Background for beginners: "temperature" is a knob that controls how
// random/creative a model's output is. 0 = as deterministic as possible
// (same input tends to produce the same output); higher values = more
// varied/creative. It's called out here because this model no longer lets
// you tune it.
const TEMPERATURE = 1;

// The response is a four-field JSON object plus one tool_use call with a
// single enum argument — 1024 tokens is generous headroom without
// inviting the model to pad the response with unrequested narration.
// "Tokens" are the chunks of text (roughly word-pieces) a model reads and
// writes; max_tokens caps how long the model's reply is allowed to be.
const MAX_TOKENS = 1024;

// A module-level variable (outside any function) that persists for the
// lifetime of the process. `undefined` until the first call sets it.
let cachedClient: Anthropic | undefined;

// Lazily creates (and then reuses) a single Anthropic client instance,
// instead of constructing a brand-new one on every API call. This pattern
// is sometimes called a "singleton."
function getClient(): Anthropic {
  if (!cachedClient) {
    // Reads ANTHROPIC_API_KEY from the environment.
    // `new Anthropic()` with no arguments automatically looks for the
    // ANTHROPIC_API_KEY environment variable — you never hardcode the key
    // in source code.
    cachedClient = new Anthropic();
  }
  return cachedClient;
}

// The TypeScript "interface" below defines the shape of the object that
// callModel expects to receive — this is how TypeScript documents and
// enforces a function's inputs at compile time.
export interface CallModelParams {
  systemPrompt: string; // instructions that set the model's role/behavior
  userPrompt: string; // the actual content/question for this turn
  tool: Anthropic.Tool; // the JSON-schema definition of a tool the model may call
}

// The one function this whole file exists to provide: given a system
// prompt, a user prompt, and a tool definition, make exactly one call to
// Claude's Messages API and hand back the raw response untouched (no
// parsing or validation happens here — that's the orchestrator's job).
export async function callModel({
  systemPrompt,
  userPrompt,
  tool,
}: CallModelParams): Promise<Anthropic.Message> {
  const anthropic = getClient();
  // This is the actual network request to Claude. Key pieces:
  // - system: sets the model's role/instructions for the whole conversation
  // - messages: the conversation turns; here just one user turn
  // - tools: a list of tools the model is ALLOWED to call if it decides to
  //   (it doesn't have to use every tool it's given — but our system
  //   prompt tells it to call this one exactly once).
  return anthropic.messages.create({
    model: MODEL,
    temperature: TEMPERATURE,
    max_tokens: MAX_TOKENS,
    system: systemPrompt,
    messages: [{ role: "user", content: userPrompt }],
    tools: [tool],
  });
}
