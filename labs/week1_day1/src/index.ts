// index.ts: wires orchestrator to the handler. Sends claim text to orchstrator,
// receives claim + tool input + attemps (or error) back. Sends policy number*
// and identified peril to handler for supabase lookup.

// *The policy number is supplied here (e.g. via auth session or separate
// field).

import pino from "pino";
import { extractClaim, ClaimExtractionError } from "./orchestrator.js";
import { checkPolicyCoverage } from "./handler.js";

const logger = pino({ name: "fnol-intake" });

const SAMPLE_CLAIM = `Hi, I'm calling to report a claim. A pipe burst under my kitchen sink
yesterday afternoon and flooded most of the first floor before I noticed it.
Cabinets, flooring, and some drywall are ruined. I'd guess it's a pretty
serious mess, not sure if everything's covered.`;

const SAMPLE_POLICY_NUMBER = "POL-100234";

async function main(): Promise<void> {
  const claimText = process.argv[2] ?? SAMPLE_CLAIM;
  const policyNumber = process.argv[3] ?? SAMPLE_POLICY_NUMBER;

  let extraction;
  try {
    extraction = await extractClaim(claimText);
  } catch (err) {
    if (err instanceof ClaimExtractionError) {
      logger.error({ err }, "claim intake failed: model output never validated");
      console.error(`\nFailed to process claim: ${err.message}`);
      process.exitCode = 1;
      return;
    }
    throw err;
  }

  const policyCoverage = await checkPolicyCoverage(
    policyNumber,
    extraction.toolInput.peril,
  );

  console.log(
    JSON.stringify(
      { policyNumber, claim: extraction.claim, policyCoverage },
      null,
      2,
    ),
  );
}

main().catch((err) => {
  logger.error({ err }, "unhandled error");
  console.error(err);
  process.exitCode = 1;
});
