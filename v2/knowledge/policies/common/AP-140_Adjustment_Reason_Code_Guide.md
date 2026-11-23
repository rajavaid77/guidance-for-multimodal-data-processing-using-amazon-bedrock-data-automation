# AP-140 Claim Adjustment Reason Code (CARC/RARC) Usage Guide
Applies to: all AnyHealth plans · Synthetic demo guide (codes are standard X12 code values; usage is AnyHealth policy)

| Situation | Action | CARC | RARC |
|---|---|---|---|
| Missing or invalid claim data (any AP-100 item) | Deny line or pend | 16 | Item-specific (M51 procedure, M76 diagnosis, M77 POS, M81 pointer, M53 units, MA130 signature, N257 billing NPI) |
| Service not covered by the plan / plan exclusion | Deny | 96 | N130 (consult plan benefit documents) |
| Not medically necessary per medical policy | Deny | 50 | N115 (decision based on medical policy) |
| Diagnosis inconsistent with procedure | Deny | 11 | M76 if diagnosis missing |
| Documentation required (records not received) | Pend | 252 | M127 |
| Prior authorization absent | Deny | 197 | N54 |
| Benefit maximum reached | Deny | 119 | N362 |
| Coverage not in effect on date of service | Deny | 27 | - |
| Patient cannot be identified as our insured | Deny | 31 | - |
| Other payer primary / COB information needed | Pend | 22 | MA04 |
| Exact duplicate | Deny | 18 | - |
| Bundled / included in another service | Deny | 97 | M15 |
| Non-covered place of service (e.g. home visit exclusion) | Deny | 58 | M77 |
