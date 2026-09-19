# Privacy Safety Thresholds

To evaluate the privacy-utility tradeoff dynamically, the Anonymity Assessment Studio utilizes specific safety thresholds for each of the core adversarial attacks. A configuration is considered "Releasable" for a given metric only if the measured risk falls below these predefined boundaries.

These thresholds are established based on the EDPB (European Data Protection Board) guidelines on anonymization, which mandate protections against Singling Out, Linkability, and Inference.

## Threshold Definitions

| Attack Metric | Threshold | EDPB Category | Rationale |
| :--- | :--- | :--- | :--- |
| **A1 Row Uniqueness (Record)** | **<= 10.0%** | Singling Out | A1 measures the probability of isolating a single subscriber's journey in the record-level release. The 10% threshold ensures that even in the worst-case, attackers face significant uncertainty (1-in-10 odds) when attempting to isolate a user in the crowd. |
| **A2 Trajectory Linkage (Record)** | **<= 10.0%** | Linkability | A2 evaluates the success rate of linking an external dataset to the released trajectories. We enforce a strict 10% ceiling to ensure that tokenized trajectories cannot be reliably stitched back together to track subscriber movement. |
| **A3 Homogeneity (Aggregate)** | **<= 25.0%** | Inference | A3 measures the risk of an attacker inferring sensitive attributes from highly homogeneous aggregate cells (e.g., "everyone in this cell has the same attribute"). We permit up to 25% homogeneity risk, relying on Differential Privacy noise to obscure exact counts. |
| **A5 Differencing (Aggregate)** | **<= 30.0%** | Linkability / Inference | A5 assesses the risk of recovering suppressed cells by taking the mathematical difference between overlapping aggregate queries. The 30% limit ensures that secondary suppression and DP noise effectively block precise reconstruction of missing cells. |
| **A6 Inference Accuracy (Aggregate)** | **<= 60.0%** | Inference | A6 is a Membership Inference attack that tests an attacker's ability to guess if a specific target is present in the dataset. Since 50% represents random guessing, clamping accuracy below 60% mathematically guarantees that the dataset provides near-zero inference advantage. |

## Dynamic Releasability
In the **Trade-off Explorer** dashboard, these thresholds drive the green/red coloring of the spectrum. When analyzing a specific risk metric, the Releasable Status dynamically evaluates against the specific threshold for that metric, decoupling it from the global "worst-case" flag.

## Relationship to the verdict rules

These thresholds are **not** the same rule system as the EDPB verdicts shown in the
story scoreboard, which live in `app/lib/verdicts.py` and are restated in
`docs/risk_assessment.md`:

- **These thresholds** are fixed percentage ceilings per attack. They drive the
  green/red colouring of the Trade-off Explorer, where the point is to compare
  configurations against each other.
- **The verdict rules** are relative: FAIL if an individual is identifiable with
  probability greater than 1/k, or if an attack beats its baseline by more than
  the differential-privacy bound allows; RESIDUAL if a criterion holds with a
  named weakness; PASS otherwise. They score the deployed release.

The two can disagree on a given configuration — for example a 60% ceiling on A6 is
a looser test than "inside the epsilon bound". When they disagree, the verdict
rules are the ones quoted in the risk assessment, and the reason for the
difference should be stated rather than smoothed over.
