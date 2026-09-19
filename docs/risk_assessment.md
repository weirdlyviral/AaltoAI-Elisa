# Risk Assessment

## Threat Model
- **Recipient:** Elisa product team. No raw-data access, no hashing keys, no enb→token mapping, no auxiliary identity data (relative approach, EDPS v SRB).
- **Worst-case attacker (reported alongside):** knows some true (enb, time) points about a target, public enb→province geography, and in the aggregate differencing test, the true slice totals.

## Results Headline
| Attack | Baseline | Record Release | Aggregate Release (ε=1) |
|---|---|---|---|
| Row uniqueness | 36% of subscribers own at least one unique row | 0.00% rows in groups of size 1, 0.00% in groups < 10 (distinct subscribers), expected identification probability = 0.0249 | - |
| Trajectory attack | 4 known points uniquely identify 99.6% among eligible subscribers | unlinkable by design (no persistent identifier) | - |
| Homogeneity | N/A | 0% of groups homogeneous | - |
| Outliers | N/A | 0 heavy users in groups < k | - |
| Differencing on aggregates | N/A | - | 0% of suppressed cells recovered within ±2 subscribers with secondary suppression |
| Membership inference on aggregates | 100% accuracy without DP | - | accuracy ≈ 50.0% (bounded by 73.1%) at epsilon 1.0 |

## What DP Covers
QoE medians/p10/p90 and volume sums are NOT covered by DP; they are protected by the ≥10 threshold, winsorising and top-coding.
