// Client layer: owns the model API call and the configuration.

import Anthropic from "@anthropic-ai/sdk";

// Sonnet chosen due to simplicity of task: bounded extraction + one tool call.
// Haiku failed in testing. Opus buys nothing over Sonnet here.
const MODEL = "claude-sonnet-5";

// Set to 1 as all Claude models after Opus 4.6 have deprecated temperature (the
// SDK rejects every value except 1.0). I'd have chosen 0 for this task otherwise.
const TEMPERATURE = 1;

// 1024 provides ~5x headroom over output tokens in testing without creating room
// for excessive output length/ padding.
const MAX_TOKENS = 1024;

let cachedClient: Anthropic | undefined;

function getClient(): Anthropic {
  if (!cachedClient) {
    // Reads ANTHROPIC_API_KEY from the environment.
    cachedClient = new Anthropic();
  }
  return cachedClient;
}

export interface CallModelParams {
  systemPrompt: string;
  userPrompt: string;
  tool: Anthropic.Tool;
}

export async function callModel({
  systemPrompt,
  userPrompt,
  tool,
}: CallModelParams): Promise<Anthropic.Message> {
  const anthropic = getClient();
  return anthropic.messages.create({
    model: MODEL,
    temperature: TEMPERATURE,
    max_tokens: MAX_TOKENS,
    system: systemPrompt,
    messages: [{ role: "user", content: userPrompt }],
    tools: [tool],
  });
}
