# Judge calibration sheet

For each case, write your own verdict (correct / partial / incorrect) on the **Human verdict** line *before* reading the judge's. The judge's rules (prompts/judge_v1.md): every reference fact present and matching = correct; nothing contradicted but a required fact missing = partial; any contradiction, wrong product, or a decline when the reference has an answer = incorrect. Extra detail is fine if it doesn't contradict.

## haiku (20260926-182305_haiku_A): 10 cases

### haiku #1: q015 (paraphrase)

**Question:** If I shut down my membership and there's money left over, how do I get it?

**Reference answer:** By official check mailed within 7 business days to the address on file.

**Assistant's answer:** Under the Account Closure Procedure v1.4, after any pending items review is complete, your remaining balance will be disbursed by official check mailed within 7 business days to the address on file. At your request, the funds can instead be transferred to another Harbor member's account (with that member's consent), or paid out in cash in branch if the balance is under $2,500.

**Human verdict:** Correct  (reason: Response includes required reference fact with additional non-contradictory relevant information)

<details><summary>Judge's verdict</summary>

**partial**: Core fact (official check within 7 business days to address on file) matches, but the extra alternatives (transfer, cash payout) are additions not confirmable against the reference, though they don't contradict; however the reference doesn't mention a pending items review condition which is extra but not contradicting, so verdict is partial due to unverifiable added conditions not confirmed as matching reference.

</details>

### haiku #2: q022 (scanned_table)

**Question:** What is the current rate on a 30-year fixed mortgage?

**Reference answer:** 6.375% (APR 6.521%).

**Assistant's answer:** The current rate on a 30-year fixed mortgage is 6.375% APR (6.521%), effective September 1, 2026, under the Mortgage and Home Equity Rate Notice v2026-09. This rate assumes a loan amount of $350,000, a loan-to-value ratio of 80% or less, a credit score of 740 or higher, and a 45-day rate lock.

**Human verdict:** Incorrect  (reason: Assistant swapped the labels, incorrectly stating the rate and the APR)

<details><summary>Judge's verdict</summary>

**incorrect**: Assistant swapped the labels, stating 6.375% is the APR and 6.521% is the rate, contradicting the reference where 6.375% is the rate and 6.521% is the APR.

</details>

### haiku #3: q034 (multi_chunk)

**Question:** On a lost-card call where the member reports unauthorized transactions, what must the agent do and what should the member be told about the new card?

**Reference answer:** Block the card in CardCenter, transfer to the Fraud Response Team at ext. 4417, and tell the member the replacement arrives in 7 to 10 business days.

**Assistant's answer:** When a member reports unauthorized transactions on a lost card, the agent must: (1) review recent transactions from the last 10 days with the member to identify unauthorized ones, (2) complete the compliance disclosure (read aloud verbatim) explaining the member will not be responsible for unauthorized transactions after the call and that Harbor will investigate, (3) then transfer the call to the Fraud Response Team at extension 4417 using a warm transfer, summarizing the case for the analyst. Additionally, per the Card Dispute Procedure, the agent must block the card immediately and order a replacement if fraud is suspected. The member should be told (verbatim per the script) that they will not be responsible for unauthorized transactions made after the call, that their liability for transactions before the call depends on how quickly they reported the loss (per their Electronic Fund Transfer Agreement), and that Harbor will investigate and contact them in writing with results.

**Human verdict:** Incorrect  (reason: Response includes some useful additional information; however, it excludes the delivery time frame present in the reference answer)

<details><summary>Judge's verdict</summary>

**incorrect**: Assistant omits the required 7-10 business day replacement card arrival timeframe stated in the reference.

</details>

### haiku #4: q035 (multi_chunk)

**Question:** When is a consumer loan payment treated as late and what is the late fee?

**Reference answer:** Late if not received within 15 days of the due date; fee is 5% of the payment or $25.00, whichever is less.

**Assistant's answer:** Under the Loan Late Payment and Collections Policy v1.6, a consumer loan payment is treated as late when it is not received by the due date (as detailed in Section 3 of the policy). The late fee is 5% of the scheduled payment amount or $25.00, whichever is less. Only one late fee is charged per scheduled payment, and late fees are not charged on loans enrolled in an approved hardship program while the member is meeting the program terms.

**Human verdict:** Incorrect  (reason: Response incorrectly omits grace period)

<details><summary>Judge's verdict</summary>

**incorrect**: Assistant states payment is late if not received by the due date, omitting/contradicting the required 15-day grace period from the reference.

</details>

### haiku #5: q001 (exact_term)

**Question:** When does an agent complete Form HCU-DSP-114?

**Reference answer:** During the initial contact, for every card dispute.

**Assistant's answer:** An agent completes Form HCU-DSP-114 during the initial contact with a member to report a card dispute. This happens whether the contact is by phone, in branch, or through secure message, under the Card Dispute Procedure v Rev 5.

**Human verdict:** Correct  (reason: Response includes required fact with additional non-contradictory relevant information)

<details><summary>Judge's verdict</summary>

**correct**: Assistant confirms form is completed during initial contact for card disputes, matching the reference; extra channel/version details don't contradict it.

</details>

### haiku #6: q008 (paraphrase)

**Question:** If I'm fighting a charge, how fast do I get money put back while you look into it?

**Reference answer:** Within 10 business days of Harbor receiving the notice.

**Assistant's answer:** Under the Card Dispute Procedure v Rev 5, provisional credit for the disputed amount is posted within 10 business days of receiving your dispute notice if the investigation hasn't been completed by then. If your account was opened less than 30 days before the first disputed transaction, provisional credit is posted within 20 business days. You'll be notified of the provisional credit within two business days of it being posted.

**Human verdict:** Correct  (reason: Response includes required fact with additional non-contradictory relevant information)

<details><summary>Judge's verdict</summary>

**correct**: Assistant states the same core fact of 10 business days for provisional credit, matching the reference, with extra non-contradictory details.

</details>

### haiku #7: q016 (scanned_table)

**Question:** How much does a stop payment order cost?

**Reference answer:** $30.00 per request.

**Assistant's answer:** A stop payment order costs $30.00 per request and is valid for 6 months, under the Schedule of Fees and Charges for Retail Accounts version 2026.

**Human verdict:** Correct  (reason: Response includes required fact with additional non-contradictory relevant information)

<details><summary>Judge's verdict</summary>

**correct**: The core fact, $30.00 per request, matches the reference; additional details do not contradict it.

</details>

### haiku #8: q023 (scanned_table)

**Question:** What is the introductory HELOC rate and how long does it last?

**Reference answer:** 5.99% for the first 12 months.

**Assistant's answer:** The introductory HELOC rate is 5.99% and it lasts for the first 12 months, under the Mortgage and Home Equity Rate Notice v2026-09.

**Human verdict:** Correct  (reason: Response includes required fact with additional non-contradictory relevant information)

<details><summary>Judge's verdict</summary>

**correct**: States 5.99% for the first 12 months, matching the reference; extra version detail does not contradict.

</details>

### haiku #9: q029 (version_trap)

**Question:** How many overdraft fees can Harbor charge me in a single day under the current policy?

**Reference answer:** Three per business day.

**Assistant's answer:** Under the Overdraft Policy v3, Harbor can charge you up to three (3) overdraft fees per business day. Each Courtesy Pay item is charged $29, for a maximum of three items per business day. Additionally, if you use Overdraft Transfer Protection, there is one $5.00 transfer fee per business day regardless of how many items the transfer covers.

**Human verdict:** Correct  (reason: Response includes required fact with additional non-contradictory relevant information)

<details><summary>Judge's verdict</summary>

**correct**: States three overdraft fees per business day, matching the reference, with extra consistent detail.

</details>

### haiku #10: q037 (duplicate_source)

**Question:** How much is an outgoing international wire from a personal account?

**Reference answer:** $45.00 per wire plus intermediary charges.

**Assistant's answer:** An outgoing international wire from a personal (Retail) account is $45.00 per wire, plus any intermediary or beneficiary bank charges deducted from the transferred amount, under the Wire Transfer Policy Rev 2026-02.

**Human verdict:** Correct  (reason: Response includes required fact with additional non-contradictory relevant information)

<details><summary>Judge's verdict</summary>

**correct**: States the $45.00 per wire fee plus intermediary charges, matching the reference.

</details>

## sonnet (20260928-075104_sonnet_B): 10 cases

### sonnet #1: q015 (paraphrase)

**Question:** If I shut down my membership and there's money left over, how do I get it?

**Reference answer:** By official check mailed within 7 business days to the address on file.

**Assistant's answer:** Under the Account Closure Procedure v1.4: if there are no pending items (outstanding checks, ACH debits or card disputes), your remaining balance can be disbursed the next business day. If there are pending items, the account goes into a 30-day review period before final disbursement. After that, the remaining balance is sent to you as an official check mailed within 7 business days to your address on file. If you prefer, you can instead have the funds transferred to another Harbor member's account (with that member's consent) or, if the balance is under $2,500, take it as cash in branch. Dividends are paid through the date of closure. Note: if your account is overdrawn at closure, closure won't be completed — under the Overdraft Policy v3.0 you'll be referred for recovery instead.

**Human verdict:** Correcy  (reason: Response includes required fact with additional non-contradictory relevant information)

<details><summary>Judge's verdict</summary>

**partial**: The assistant includes the correct core fact (official check mailed within 7 business days to address on file) but adds many additional unverified conditions (30-day review, next-business-day disbursement, cash option, overdraft referral) not confirmed against the reference, which only states the simple check method without these extra procedural details.

</details>

### sonnet #2: q020 (scanned_table)

**Question:** What is the lowest APR on a 48-month new car loan with top-tier credit?

**Reference answer:** 4.49% APR (Tier A+, 37-60 months).

**Assistant's answer:** For a new vehicle loan in the 37-60 month range (which covers 48 months) with Tier A+ credit (740+), the base rate is 4.49% APR. This can be reduced by 0.25% for automatic payments from a Harbor checking account, plus an additional 0.10% for a Premier Checking relationship — but discounts cannot bring the rate below a 3.99% APR floor. So the lowest possible APR is 4.14% (4.49% minus 0.35% in discounts), per the Auto Loan Product Comparison, version 2026-09.

**Human verdict:** Partial  (reason: Response includes required fact but with information that contradicts the reference answer)

<details><summary>Judge's verdict</summary>

**partial**: Assistant correctly states the base 4.49% APR for Tier A+ 37-60 months but adds extra discount details not in the reference, implying a lower final rate (4.14%) that isn't confirmed by the reference answer.

</details>

### sonnet #3: q034 (multi_chunk)

**Question:** On a lost-card call where the member reports unauthorized transactions, what must the agent do and what should the member be told about the new card?

**Reference answer:** Block the card in CardCenter, transfer to the Fraud Response Team at ext. 4417, and tell the member the replacement arrives in 7 to 10 business days.

**Assistant's answer:** Under the Card Dispute Procedure Rev 5 and the Contact Centre Script: Lost or Stolen Card v2.2, the agent should: 1) block the card immediately and order a replacement since fraud is suspected; 2) review recent transactions (last 10 days) with the member and note any unauthorized ones; 3) read the compliance disclosure verbatim and get a verbal 'yes' acknowledgment, recording it in the call notes; 4) complete Form HCU-DSP-114 (Card Transaction Dispute); and 5) after the disclosure, warm-transfer the call to the Fraud Response Team at extension 4417, summarizing the case for the analyst first. The member should be told that they will not be responsible for unauthorized transactions made after this call, and that for unauthorized debit card transactions made before the call, their liability may depend on how quickly they reported the loss, as explained in their Electronic Fund Transfer Agreement and Disclosure. Harbor will investigate any disputed transactions and contact the member in writing with the results.

**Human verdict:** Incorrect  (reason: Response excludes required fact from reference answer)

<details><summary>Judge's verdict</summary>

**incorrect**: Reference states replacement arrives in 7 to 10 business days, but assistant's answer omits this timeframe entirely and instead discusses liability details not in the reference.

</details>

### sonnet #4: q035 (multi_chunk)

**Question:** When is a consumer loan payment treated as late and what is the late fee?

**Reference answer:** Late if not received within 15 days of the due date; fee is 5% of the payment or $25.00, whichever is less.

**Assistant's answer:** Under the Loan Late Payment and Collections Policy v1.6, a consumer loan payment is considered late if it is not received within 15 calendar days (the grace period) after the due date shown on the billing statement. If the last day of that grace period falls on a weekend or a Federal Reserve holiday, the grace period extends to the next business day. Payments made within the grace period are treated as on-time for fee purposes, though interest still accrues daily on simple-interest loans. The passages provided describe the grace period and communications timeline but do not state the specific dollar amount or percentage of the late fee.

**Human verdict:** Incorrect  (reason: Response excludes required fact from reference answer)

<details><summary>Judge's verdict</summary>

**incorrect**: Assistant fails to state the required late fee amount (5% of payment or $25, whichever is less), instead claiming it's not stated.

</details>

### sonnet #5: q001 (exact_term)

**Question:** When does an agent complete Form HCU-DSP-114?

**Reference answer:** During the initial contact, for every card dispute.

**Assistant's answer:** The agent completes Form HCU-DSP-114 (Card Transaction Dispute) during the initial contact with the member, whether by phone, in branch, or through secure message—this happens as part of the intake steps under the Card Dispute Procedure Rev 5, after verifying the caller and confirming transaction details, and before routing the case to the Card Services dispute queue.

**Human verdict:** Correct  (reason: Response includes required fact from reference with additional non-contradictory relevant information)

<details><summary>Judge's verdict</summary>

**correct**: States the form is completed during the initial contact for card disputes, matching the reference, with added non-contradictory detail.

</details>

### sonnet #6: q008 (paraphrase)

**Question:** If I'm fighting a charge, how fast do I get money put back while you look into it?

**Reference answer:** Within 10 business days of Harbor receiving the notice.

**Assistant's answer:** Under the Card Dispute Procedure (Rev 5), if your investigation isn't finished quickly, Harbor posts provisional credit for the disputed amount within 10 business days of receiving your dispute notice (or within 20 business days if your account was opened less than 30 days before the disputed transaction). You'll be notified of the provisional credit amount and date within 2 business days of it posting. Note: for credit card disputes, provisional credit isn't used - instead the disputed amount is suspended from your balance and excluded from finance charges while the investigation is open.

**Human verdict:** Correct  (reason: Response includes required fact from reference with additional non-contradictory relevant information)

<details><summary>Judge's verdict</summary>

**correct**: Assistant confirms the core 10 business day timeframe for provisional credit matching the reference, with additional non-contradictory details.

</details>

### sonnet #7: q014 (paraphrase)

**Question:** I misplaced my card. How long until the new one shows up in the post?

**Reference answer:** 7 to 10 business days by standard mail.

**Assistant's answer:** A replacement card sent by standard mail typically arrives within 7 to 10 business days after it's ordered. If you need it faster, expedited delivery is available for a $35.00 fee and arrives in 2 business days (standard replacement is $10.00, with the first replacement each year free).

**Human verdict:** Correct  (reason: Response includes required fact from reference with additional non-contradictory relevant information)

<details><summary>Judge's verdict</summary>

**correct**: States the same 7 to 10 business days by standard mail as the reference, with extra non-contradictory detail.

</details>

### sonnet #8: q022 (scanned_table)

**Question:** What is the current rate on a 30-year fixed mortgage?

**Reference answer:** 6.375% (APR 6.521%).

**Assistant's answer:** As of the Mortgage and Home Equity Rate Notice effective September 1, 2026, the 30-Year Fixed mortgage rate is 6.375% (APR 6.521%, 0 points). This rate assumes a loan amount of $350,000, loan-to-value of 80% or less, credit score of 740 or higher, and a 45-day rate lock for an owner-occupied, single-family primary residence. Rates may change daily without notice.

**Human verdict:** Correct  (reason: Response includes required fact from reference with additional non-contradictory relevant information)

<details><summary>Judge's verdict</summary>

**correct**: States the same rate 6.375% and APR 6.521% as the reference, with extra non-contradictory detail.

</details>

### sonnet #9: q029 (version_trap)

**Question:** How many overdraft fees can Harbor charge me in a single day under the current policy?

**Reference answer:** Three per business day.

**Assistant's answer:** Under the Overdraft Policy v3.0, Harbor charges a $29 fee per item paid through Courtesy Pay, up to a maximum of 3 items per business day (so up to $87 in per-item overdraft fees). No overdraft fee applies if the account is overdrawn by $25.00 or less at day's end. Separately, if you use Overdraft Transfer Protection, only one $5.00 transfer fee is charged per business day regardless of how many items it covers.

**Human verdict:** Correct  (reason: Response includes required fact from reference with additional non-contradictory relevant information)

<details><summary>Judge's verdict</summary>

**correct**: States the maximum is 3 overdraft fees per business day, matching the reference, with consistent extra detail.

</details>

### sonnet #10: q037 (duplicate_source)

**Question:** How much is an outgoing international wire from a personal account?

**Reference answer:** $45.00 per wire plus intermediary charges.

**Assistant's answer:** An outgoing international wire from a Retail (personal) account costs $45.00 per wire, plus any intermediary or beneficiary bank charges deducted from the transferred amount, under the Wire Transfer Policy (Rev 2026-02).

**Human verdict:** Correct  (reason: Response includes required fact from reference with additional non-contradictory relevant information)

<details><summary>Judge's verdict</summary>

**correct**: States the same $45.00 per wire fee plus intermediary charges as the reference, with no contradicting details.

</details>

## opus (20260928-075936_opus_C): 10 cases

### opus #1: q033 (multi_chunk)

**Question:** What are the key steps and timelines for closing a member's account?

**Reference answer:** Signed Form HCU-ACL-220 from every owner; 30-day review if items are pending; balance mailed by official check within 7 business days.

**Assistant's answer:** Under Harbor's Account Closure Procedure v1.4 (MS-PRO-012, effective June 1, 2026), closing a retail share or checking account works like this:

Before starting: the request must come from an account owner, and on joint accounts every owner must consent. We'll review linked services that will fail (direct deposits, automatic loan payments, bill pay payees, P2P enrollments) so you can redirect them. Note that closing the Primary Share Account ends membership, and it can't be closed while you have an open loan 
inch it must be paid in full first.

Steps:
1. Identity verification 
sic two forms of ID in branch, or the three-factor authentication script by phone.
2. A signed Form HCU-ACL-220 (Account Closure Request) from every owner.
3. Review of pending items, holds and scheduled transfers, noted on the form.
4. Cancel debit cards, stop recurring transfers, remove bill pay payees.
5. Account moved to Closing status and disbursement method recorded.
6. Deposit Operations completes the pending items review.
7. Remaining balance disbursed and account set to Closed.
8. Closure confirmation letter sent; form retained in the member file.

Timelines: phone requests are accepted only for single-owner accounts, and the signed form must be returned by mail or secure upload before step 5. After the pending-items review period, the balance is disbursed by official check mailed within 7 business days to the address on file; alternatively it can be transferred to another Harbor member's account with their consent, or paid in cash in branch if the balance is under $2,500. Dividends are paid through the date of closure. If the account is overdrawn, the closure is not completed 
sic it's referred under the Overdraft Policy with a recovery case. The form and confirmation letter are kept for five years after closure.

One part I can't confirm from the material I have: the exact length of the pending-items review period in Section 4.

**Human verdict:** Incorrect  (reason: Response excludes required fact from reference answer)

<details><summary>Judge's verdict</summary>

**incorrect**: The assistant explicitly fails to state the 30-day review period, which is a required fact from the reference, instead saying it cannot confirm it.

</details>

### opus #2: q034 (multi_chunk)

**Question:** On a lost-card call where the member reports unauthorized transactions, what must the agent do and what should the member be told about the new card?

**Reference answer:** Block the card in CardCenter, transfer to the Fraud Response Team at ext. 4417, and tell the member the replacement arrives in 7 to 10 business days.

**Assistant's answer:** On a lost/stolen card call where unauthorized transactions are reported, under the Contact Centre Script: Lost or Stolen Card v2.2 the agent must: note the transactions the member doesn't recognize (after reading the last 10 days of activity), read the Step 5 compliance disclosure verbatim, wait for a verbal "yes" and record the acknowledgment in the call notes, then warm-transfer the call to the Fraud Response Team at extension 4417, summarising the case for the analyst before connecting the member. The disclosure tells the member they are not responsible for unauthorized transactions made after the call, that liability for unauthorized debit card transactions before the call may depend on how quickly the loss was reported (per the Electronic Fund Transfer Agreement and Disclosure), and that Harbor will investigate and write to them with the results. Under the Card Dispute Procedure Rev 5, the agent also verifies the caller with the three-factor script, confirms the transaction details, blocks the card immediately and orders a replacement where fraud is suspected, completes Form HCU-DSP-114 during the initial contact, and routes the case to the Card Services dispute queue; disputes should be reported within 60 days of the statement date on which the transaction first appeared. What the member should be told about the new card itself (for example delivery timing or activation) is not covered by the material I have.

**Human verdict:** Partial  (reason: Response excludes required fact from reference answer)

<details><summary>Judge's verdict</summary>

**partial**: Assistant covers blocking and Fraud Response Team transfer correctly but explicitly fails to state the required 7–10 business day replacement card delivery time.

</details>

### opus #3: q001 (exact_term)

**Question:** When does an agent complete Form HCU-DSP-114?

**Reference answer:** During the initial contact, for every card dispute.

**Assistant's answer:** Under the Card Dispute Procedure (Rev 5), the agent completes Form HCU-DSP-114 (Card Transaction Dispute) during the initial contact for every dispute \u2014 whether you call, visit a branch, or send a secure message. In the step order, it's completed after verifying you, confirming the transaction details, and blocking/replacing the card if fraud is suspected; the agent then reads the dispute acknowledgment disclosure and routes the case to the Card Services dispute queue. The completed form is kept for at least two years from resolution.

**Human verdict:** Correct  (reason: Response includes required fact from reference with additional non-contradictory relevant information)

<details><summary>Judge's verdict</summary>

**correct**: Both state the form is completed during initial contact for every card dispute; extra procedural detail does not contradict the reference.

</details>

### opus #4: q006 (exact_term)

**Question:** What is the early withdrawal penalty on a Share Certificate with a term longer than 12 months?

**Reference answer:** 180 days of dividends.

**Assistant's answer:** For a Share Certificate with a term longer than 12 months, the early withdrawal penalty is 180 days of dividends (terms of 12 months or less are 90 days). This is under the Share Certificate Account Disclosure, version DEP-DSC-017. The penalty is calculated on the amount withdrawn at the dividend rate in effect on the certificate, and it can reduce your principal if the dividends earned are less than the penalty. Note that early withdrawals of principal are only allowed as a full withdrawal. The penalty is waived if an owner dies or is declared legally incompetent by a court, and you also have a 10-day grace period after maturity to withdraw without penalty.

**Human verdict:** Correct  (reason: Response includes required fact from reference with additional non-contradictory relevant information)

<details><summary>Judge's verdict</summary>

**correct**: States 180 days of dividends for terms over 12 months, matching the reference, with additional consistent detail.

</details>

### opus #5: q010 (paraphrase)

**Question:** How much can I add each day by snapping photos of cheques with my phone?

**Reference answer:** $5,000 per day.

**Assistant's answer:** Under the Mobile and Online Banking Help guidance, the standard mobile cheque deposit limit is $5,000 per day per member, with a rolling 30-day limit of $15,000. If your account has been open less than 90 days, your daily limit is $1,500. Deposits made before 6:00 p.m. Eastern Time on a business day are generally available the next business day, though some may be held longer (we'll let you know). Endorse the back with your signature and "For mobile deposit at Harbor CU only", and keep the paper cheque for 30 days before destroying it.

**Human verdict:** Correct  (reason: Response includes required fact from reference with additional non-contradictory relevant information)

<details><summary>Judge's verdict</summary>

**correct**: States $5,000 per day matching the reference, with additional non-contradictory details.

</details>

### opus #6: q014 (paraphrase)

**Question:** I misplaced my card. How long until the new one shows up in the post?

**Reference answer:** 7 to 10 business days by standard mail.

**Assistant's answer:** A replacement card sent by standard mail typically arrives within 7 to 10 business days (Contact Centre Script: Lost or Stolen Card, version 2.2). It goes to the address we have on file " we can't change the mailing address on this call, as that needs separate verification. If you need it faster, expedited delivery arrives in 2 business days for $35.00; standard replacement is $10.00, with your first replacement each year free (Schedule of Fees and Charges: Retail Accounts, version 2026). You can add the new card to your mobile wallet as soon as it's activated.

**Human verdict:** Correct  (reason: Response includes required fact from reference with additional non-contradictory relevant information)

<details><summary>Judge's verdict</summary>

**correct**: States the same 7 to 10 business days by standard mail as the reference, with extra non-contradictory details.

</details>

### opus #7: q018 (scanned_table)

**Question:** What APY does a 24-month certificate pay on a $60,000 deposit?

**Reference answer:** 4.05% APY.

**Assistant's answer:** A 24-month share certificate with a $60,000 deposit falls in the $50,000+ tier, so it pays 4.05% APY. This is from the Q3 2026 Deposit Rate Sheet (version Q3 2026), with rates effective July 1, 2026 through September 30, 2026.

**Human verdict:** Correct  (reason: Response includes required fact from reference with additional non-contradictory relevant information)

<details><summary>Judge's verdict</summary>

**correct**: States 4.05% APY matching the reference, with extra consistent detail.

</details>

### opus #8: q022 (scanned_table)

**Question:** What is the current rate on a 30-year fixed mortgage?

**Reference answer:** 6.375% (APR 6.521%).

**Assistant's answer:** Under the Mortgage and Home Equity Rate Notice (version 2026-09, effective September 1, 2026), the 30-Year Fixed rate is 6.375% with an APR of 6.521% and 0.000 points. That quote assumes an owner-occupied, single-family primary residence, a loan amount of $350,000, a loan-to-value of 80% or less, a credit score of 740 or higher, and a 45-day rate lock. Rates can change daily without notice, so please confirm before you lock.

**Human verdict:** Correct  (reason: Response includes required fact from reference with additional non-contradictory relevant information)

<details><summary>Judge's verdict</summary>

**correct**: States the same rate (6.375%) and APR (6.521%) as the reference, with extra non-contradicting detail.

</details>

### opus #9: q026 (reading_order)

**Question:** When does the new Carrow Bay branch open?

**Reference answer:** Monday, October 19, 2026.

**Assistant's answer:** The new Carrow Bay branch at 88 Wharf Street opens to members on Monday, October 19, 2026, according to the Harbor Currents Member Newsletter (Summer 2026 edition). It will have a drive-up lane, a 24-hour deposit-taking ATM, and two private offices for loan and financial wellness appointments.

**Human verdict:** Correct  (reason: Response includes required fact from reference with additional non-contradictory relevant information)

<details><summary>Judge's verdict</summary>

**correct**: Assistant states the same opening date, Monday, October 19, 2026, matching the reference, with extra non-contradictory detail.

</details>

### opus #10: q030 (version_trap)

**Question:** What does Harbor currently charge for an Overdraft Transfer Protection transfer from savings?

**Reference answer:** $5.00 per transfer, once per day.

**Assistant's answer:** Under the Overdraft Policy v3.0 (effective 2026-01-01), an Overdraft Transfer Protection transfer from your linked Primary Share (savings) account costs $5.00 per transfer, and only one transfer fee is charged per business day no matter how many items that transfer covers. (This fee was reduced in version 3.0 and is now charged once per day.) The Retail Schedule of Fees and Charges 2026 confirms these fees are set out in the Overdraft Policy.

**Human verdict:** Correct  (reason: Response includes required fact from reference with additional non-contradictory relevant information)

<details><summary>Judge's verdict</summary>

**correct**: States $5.00 per transfer, once per day, matching the reference; extra policy details do not contradict it.

</details>

