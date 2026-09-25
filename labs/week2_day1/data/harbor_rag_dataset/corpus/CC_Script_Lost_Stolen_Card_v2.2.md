# Contact Centre Script: Lost or Stolen Card

_Script ID: CC-SCR-007 | Version 2.2 | Last reviewed: March 3, 2026 | Owner: Member Contact Centre | Classification: Internal_

## When to Use This Script

Use this script when a member reports that a Harbor debit or credit card has been lost, stolen, or retained by an ATM, or that they believe someone else knows the card number. Do not use it for disputes about a merchant charge; use the Card Dispute Procedure instead.

## Step 1: Greeting and Authentication

AGENT: "Thank you for calling Harbor Credit Union, this is [AGENT FIRST NAME]. I understand your card may be lost or stolen. I'm going to help you secure it right away. First, I need to verify your identity."

[Complete the three-factor authentication script. If the caller cannot be authenticated, you may still block the card but must not discuss balances or transactions.]

## Step 2: Block the Card

Place an immediate block on the card in CardCenter using status code 41 (lost) or 43 (stolen). Confirm the last four digits of the card with the member before applying the block.

AGENT: "I have blocked the card ending in [LAST FOUR]. It can no longer be used for purchases or ATM withdrawals."

## Step 3: Review Recent Activity

AGENT: "Let's look at the recent transactions together. Please tell me if there are any you don't recognize."

[Read transactions from the last 10 days. If the member identifies any unauthorized transactions, note them and proceed to Step 4. If none, skip to Step 5.]

## Step 4: Fraud Referral

If the member reports unauthorized transactions, transfer the call to the Fraud Response Team at extension 4417 after completing Step 5. Use a warm transfer and summarize the case for the Fraud Response analyst before connecting the member.

## Step 5: Compliance Disclosure (read aloud, verbatim)

AGENT: "Please listen carefully to the following information. Because you have reported your card lost or stolen, you will not be responsible for unauthorized transactions made after this call. For unauthorized debit card transactions made before this call, your liability may depend on how quickly you reported the loss, as explained in your Electronic Fund Transfer Agreement and Disclosure. Harbor will investigate any transactions you dispute and will contact you in writing with the results. Do you understand this information?"

[Wait for a verbal "yes". If the member says no, read the disclosure again. Record the acknowledgment in the call notes.]

## Step 6: Replacement Card

Order a replacement card to the address on file. Do not change the mailing address on this call; address changes require separate verification.

AGENT: "I've ordered your new card. By standard mail, a replacement card typically arrives within 7 to 10 business days. You can add the new card to your mobile wallet as soon as it is activated. If you need it sooner, expedited delivery is available for a fee listed in our Schedule of Fees."

## Step 7: Close the Call

AGENT: "Is there anything else I can help you with today? Thank you for calling Harbor Credit Union."

[Wrap-up code: CARD-LS. Call notes must include the block status code, the disclosure acknowledgment, whether a fraud referral was made, and the replacement delivery method.]
