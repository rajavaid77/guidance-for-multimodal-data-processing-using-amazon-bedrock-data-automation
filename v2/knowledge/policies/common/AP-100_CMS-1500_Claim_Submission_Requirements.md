# AP-100 CMS-1500 Claim Submission and Data Requirements
Applies to: all AnyHealth plans · Synthetic demo policy · Form version: NUCC 1500 (02-12)

## Required items
| Item | Requirement | If missing or invalid |
|---|---|---|
| 1 | Mark GROUP HEALTH PLAN or OTHER for AnyHealth commercial plans. MEDICARE marked on an AnyHealth claim indicates a possible Medicare primary / MSP situation and must be verified (AP-120). | Pend, CARC 16 / RARC MA04 |
| 1a | Insured ID exactly as on the member card | Deny, CARC 31 |
| 2, 3 | Patient name and date of birth; sex | Pend, CARC 16 / RARC MA27 (name) or N329 (DOB) |
| 4, 7, 11, 11a, 11c | Insured name, address, group number, DOB, plan name | Pend, CARC 16 |
| 11d | Must be YES or NO | Pend, CARC 16 |
| 12, 13 | Signature or "Signature on File" | Pend, CARC 16 / RARC MA130 |
| 21 | At least one ICD-10-CM code; ICD indicator 0 | Deny line, CARC 16 / RARC M76 |
| 24A | From/To dates of service for every line; To date not before From date | Deny line, CARC 16 / RARC M59 |
| 24B | Valid 2-digit place of service code (e.g. 11 office, 02/10 telehealth, 12 home, 22 outpatient hospital). Alphabetic values are invalid. | Deny line, CARC 16 / RARC M77 |
| 24D | Valid CPT/HCPCS code; up to 4 modifiers | Deny line, CARC 16 / RARC M51 |
| 24E | Diagnosis pointer letters A-L referencing item 21 lines that are filled in; the first letter is the primary diagnosis for the line; maximum 4 letters | Deny line, CARC 16 / RARC M81 |
| 24F | Charge per line | Deny line, CARC 16 |
| 24G | Days or units, numeric, at least 1 | Pend line, CARC 16 / RARC M53 |
| 24J | Rendering provider NPI when the rendering provider differs from the billing provider | Pend, CARC 16 / RARC N290 |
| 28 | Total charge equals the sum of line charges (24F) | Pend, CARC 16 / RARC M54 |
| 31 | Signature of physician or supplier with date | Pend, CARC 16 / RARC MA130 |
| 33, 33a | Billing provider name, address and 10-digit NPI that passes the check digit | Deny claim, CARC 16 / RARC N257 |

## Shaded supplemental area of item 24
Use the shaded upper row of a service line only for supplemental information: NDC (qualifier N4 + 11-digit NDC +
unit qualifier, e.g. "N4 00186071801 UN1.000"), anesthesia time (qualifier ZZ or 7), or item descriptions for
unlisted/miscellaneous codes. Values in the shaded row are never service-line data.

## Claim frequency and corrections
Corrected claims use item 22 resubmission code 7 (replacement) or 8 (void) with the original reference number.
Without code 7 or 8, a claim that repeats lines already processed is treated as a duplicate (AP-130).
