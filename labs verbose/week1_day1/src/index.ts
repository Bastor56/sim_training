// Entry point: wires orchestrator -> handler for one real claim, end to
// end. This is the lab's "one hop" — prompt in, structured object out,
// the single tool executed, result returned to the caller (here, stdout) —
// with the retry-on-invalid-output loop-back living entirely inside
// orchestrator.extractClaim.
//
// The policy number is supplied here, not extracted from the claim text:
// in a real intake channel this would come from an authenticated session
// or CRM record, not be recited by the claimant. See orchestrator.ts.

// "pino" is a fast, structured logging library. Instead of console.log
// (plain text), it writes JSON log lines — much easier to search/filter
// once you have thousands of them in a real system.
import pino from "pino";
// Pull in the two things this file needs from the orchestrator module:
// - extractClaim: the function that talks to the model and returns a
//   validated claim (this is the "agentic" part — see orchestrator.ts).
// - ClaimExtractionError: a custom Error subclass thrown when the model
//   never produces valid output, even after a retry.
import { extractClaim, ClaimExtractionError } from "./orchestrator.js";
// The handler is the "tool" layer: it does the real work (a database
// lookup) that the model asked for. It never talks to the model itself.
import { checkPolicyCoverage } from "./handler.js";

// Create one named logger instance for this file. The `name` field shows
// up in every log line so you can tell which part of the app logged it.
const logger = pino({ name: "fnol-intake" });

// A realistic example claim, used only if the user doesn't pass their own
// text on the command line. Written in first person, the way a claimant
// might actually describe a loss over the phone or in a web form.
const SAMPLE_CLAIM = `Hi, I'm calling to report a claim. A pipe burst under my kitchen sink
yesterday afternoon and flooded most of the first floor before I noticed it.
Cabinets, flooring, and some drywall are ruined. I'd guess it's a pretty
serious mess, not sure if everything's covered.`;

// A fallback policy number, matching the POL-XXXXXX format enforced by
// PolicyNumberSchema in schema.ts.
const SAMPLE_POLICY_NUMBER = "POL-100234";

// The main async function. `async` means this function can use `await`
// inside it to pause until a Promise (an eventual result, like an API
// call) resolves, without blocking the rest of the program.
async function main(): Promise<void> {
  // process.argv is Node's list of command-line arguments:
  //   argv[0] = path to the node binary
  //   argv[1] = path to this script
  //   argv[2] = first argument the user typed (the claim text, if any)
  //   argv[3] = second argument (the policy number, if any)
  // The `??` operator ("nullish coalescing") falls back to the sample
  // value only when the left side is null/undefined — so an empty string
  // argument would NOT trigger the fallback, only a missing one would.
  const claimText = process.argv[2] ?? SAMPLE_CLAIM;
  const policyNumber = process.argv[3] ?? SAMPLE_POLICY_NUMBER;

  // Declared with `let` (not `const`) because it's assigned inside the
  // try block below, not at declaration time.
  let extraction;
  try {
    // This is the actual "agent" call: send the claim text to Claude,
    // let it extract structured fields AND call the check_policy_coverage
    // tool, retrying once internally if the output doesn't validate.
    // `await` pauses this function here until that whole process finishes.
    extraction = await extractClaim(claimText);
  } catch (err) {
    // `instanceof` checks whether `err` is specifically a
    // ClaimExtractionError (as opposed to some other unexpected crash,
    // like a network failure) — we only want to handle THAT case
    // specially here.
    if (err instanceof ClaimExtractionError) {
      // Log a structured error (machine-readable) ...
      logger.error({ err }, "claim intake failed: model output never validated");
      // ... and also print a human-readable message to stderr for
      // whoever is running this from a terminal.
      console.error(`\nFailed to process claim: ${err.message}`);
      // Setting exitCode (rather than calling process.exit) lets any
      // pending I/O (like the logger flushing) finish before the process
      // actually exits.
      process.exitCode = 1;
      // Stop this function early — there's no extraction to continue with.
      return;
    }
    // Any other kind of error is unexpected — re-throw it so it isn't
    // silently swallowed. It will be caught by the .catch() at the very
    // bottom of this file.
    throw err;
  }

  // At this point `extraction` is guaranteed to be a successful result.
  // extraction.toolInput.peril is the peril the model identified (e.g.
  // "water") — this is the argument the model supplied to the
  // check_policy_coverage tool. Now we actually RUN that tool: combine
  // the model-identified peril with the policy number we already knew
  // (never something the model itself was given — see orchestrator.ts).
  const policyCoverage = await checkPolicyCoverage(
    policyNumber,
    extraction.toolInput.peril,
  );

  // Print the final combined result as nicely formatted JSON (the `2`
  // means "indent with 2 spaces") so a human reading the terminal output
  // can see the policy number, the model's structured claim extraction,
  // and the real coverage lookup result all together.
  console.log(
    JSON.stringify(
      { policyNumber, claim: extraction.claim, policyCoverage },
      null,
      2,
    ),
  );
}

// Kick off main(). Since main() is async, it returns a Promise; `.catch`
// here is a safety net for any error that wasn't already handled inside
// main() (for example, a bug, or an error thrown by checkPolicyCoverage).
main().catch((err) => {
  logger.error({ err }, "unhandled error");
  console.error(err);
  process.exitCode = 1;
});
