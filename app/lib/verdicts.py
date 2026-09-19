"""Explicit verdict rules for the three EDPB criteria.

The measurements live in ``outputs/risk_eval.json``. Turning a measurement
into pass / residual / fail is a judgement, so the judgement is written down
here as executable rules rather than typed into a slide. The same rules are
stated in prose in ``docs/risk_assessment.md``.

    FAIL      an individual is identifiable with probability greater than
              1/k, or an attack beats its baseline by more than the
              differential-privacy bound allows.
    RESIDUAL  the criterion holds, but with a named weakness.
    PASS      neither of the above.

Two releases are scored separately, because they are different artefacts:

    record     row-level, k-anonymous, no differential privacy
    aggregate  cell counts only — the release we actually recommend

and each under two attacker models:

    contextual   the defined recipient: an Elisa product team with no raw
                 access, no keys and no auxiliary identity data
    simplified   an attacker granted capabilities the recipient does not
                 have, used as an upper bound

On the aggregate release No Linkage is a PASS by construction: the release
contains no records, so there is nothing to link, and the subscriber key was
destroyed rather than hashed. The trajectory figure (A2) is not a verdict on
that release — it is the counterfactual that explains why linkage was removed,
and it is reported as such. Linkage-shaped risk against the aggregate lives
under No Inference, where A5 (differencing) and A6 (membership) measure it.
"""
from __future__ import annotations

from typing import Any

PASS = "pass"
RESIDUAL = "residual"
FAIL = "fail"

CRITERIA = ("no_record_isolation", "no_linkage", "no_inference")
CRITERION_LABELS = {
    "no_record_isolation": "No Record Isolation",
    "no_linkage": "No Linkage",
    "no_inference": "No Inference",
}
RELEASES = ("record", "aggregate")
RELEASE_LABELS = {"record": "Record", "aggregate": "Aggregate — what we ship"}
APPROACHES = ("contextual", "simplified")


def _attack(risk_eval: dict | None, attack_id: str) -> dict:
    for attack in (risk_eval or {}).get("attacks", []):
        if attack.get("id") == attack_id:
            return attack
    return {}


def _combine(findings: list[dict]) -> dict:
    """Worst finding wins; the reasons travel with it."""
    statuses = [finding["status"] for finding in findings]
    if FAIL in statuses:
        status = FAIL
    elif RESIDUAL in statuses:
        status = RESIDUAL
    else:
        status = PASS
    driving = [f for f in findings if f["status"] == status] or findings
    return {
        "status": status,
        "why": driving[0]["why"] if driving else "",
        "evidence": [f["evidence"] for f in findings if f.get("evidence")],
    }


def _ok(why: str, evidence: str | None = None) -> dict:
    return {"status": PASS, "why": why, "evidence": evidence}


def _weak(why: str, evidence: str | None = None) -> dict:
    return {"status": RESIDUAL, "why": why, "evidence": evidence}


def _broken(why: str, evidence: str | None = None) -> dict:
    return {"status": FAIL, "why": why, "evidence": evidence}


def _pct(value: Any, decimals: int = 1) -> str:
    return "—" if value is None else f"{value:.{decimals}f}%"


# --------------------------------------------------------------------------- #
# Record release
# --------------------------------------------------------------------------- #


def _record_isolation(risk_eval: dict | None, k: int, approach: str) -> dict:
    a1 = _attack(risk_eval, "A1").get("record", {})
    a4 = _attack(risk_eval, "A4").get("record", {}).get("qi_plus_volume", {})

    probability = a1.get("expected_identification_probability")
    threshold = 1.0 / k if k else None
    findings = []

    if probability is not None and threshold is not None and probability > threshold:
        findings.append(
            _broken(
                f"Expected identification probability {probability:.3f} exceeds 1/k ({threshold:.3f}).",
                f"A1: {probability:.3f} vs 1/k = {threshold:.3f}",
            )
        )
    else:
        findings.append(
            _ok(
                "Every quasi-identifier group holds at least k distinct subscribers, so no "
                "record can be isolated on the published attributes.",
                f"A1: {_pct(a1.get('pct_rows_in_groups_of_1'))} of rows unique, "
                f"identification probability {probability:.3f}"
                if probability is not None
                else "A1",
            )
        )

    if approach == "simplified":
        below_k = a4.get("pct_rows_below_k")
        if below_k:
            findings.append(
                _broken(
                    "An attacker who also knows the target's rough data volume pushes "
                    f"{_pct(below_k, 2)} of rows into groups smaller than k, so those "
                    "individuals are identifiable with probability above 1/k.",
                    f"A4: {_pct(below_k, 2)} of rows below k when volume is known",
                )
            )
    return _combine(findings)


def _record_linkage(risk_eval: dict | None, approach: str) -> dict:
    return _combine(
        [
            _ok(
                "The record release carries no subscriber key, hash or pseudonym, so two "
                "rows cannot be attributed to the same person.",
                "A2: no key in the release",
            )
        ]
    )


def _record_inference(risk_eval: dict | None, approach: str) -> dict:
    a3 = _attack(risk_eval, "A3").get("record", {})
    attributes = a3.get("attributes", {})
    disclosed = [
        name
        for name, stats in attributes.items()
        if (stats.get("pct_subscribers_with_attribute_disclosed") or 0) > 0
    ]
    findings = []
    if disclosed:
        findings.append(
            _weak(
                "Some groups are homogeneous on a revealing attribute: "
                + ", ".join(sorted(disclosed)),
                "A3: attributes disclosed in homogeneous groups",
            )
        )
    else:
        findings.append(
            _ok(
                "No quasi-identifier group is homogeneous on the revealing value of any "
                "sensitive attribute.",
                "A3: 0% of subscribers have an attribute disclosed",
            )
        )

    if approach == "simplified":
        homogeneous_on_false = max(
            (stats.get("pct_groups_homogeneous") or 0) for stats in attributes.values()
        ) if attributes else 0
        if homogeneous_on_false:
            findings.append(
                _weak(
                    f"{homogeneous_on_false:.0f}% of groups are homogeneous on the negative "
                    "value — a far weaker disclosure, but still an inference.",
                    f"A3: {homogeneous_on_false:.0f}% of groups homogeneous on 'false'",
                )
            )
    return _combine(findings)


# --------------------------------------------------------------------------- #
# Aggregate release
# --------------------------------------------------------------------------- #


def _aggregate_isolation(risk_eval: dict | None, k: int, approach: str) -> dict:
    return _combine(
        [
            _ok(
                "The aggregate release contains no records at all — the smallest published "
                f"unit is a cell of at least k = {k} distinct subscribers — so there is "
                "nothing to isolate.",
                f"Every published cell clears k = {k} on the noisy count",
            )
        ]
    )


def _aggregate_linkage(risk_eval: dict | None, approach: str) -> dict:
    return _combine(
        [
            _ok(
                "No records exist to link and the subscriber key was destroyed, not hashed. "
                "Linkage-shaped risk against this release is measured under No Inference "
                "(A5 differencing, A6 membership).",
                "Structural: counts only, no key retained",
            )
        ]
    )


def _aggregate_inference(risk_eval: dict | None, epsilon: float | None, approach: str) -> dict:
    a5 = _attack(risk_eval, "A5").get("aggregate", {})
    a6 = _attack(risk_eval, "A6").get("aggregate", {})
    findings = []

    if approach == "contextual":
        findings.append(
            _ok(
                "Neither aggregate attack is attemptable by the defined recipient: "
                "differencing needs the true slice totals and membership inference needs "
                "every other subscriber's data.",
                "A5 and A6: not attemptable contextually",
            )
        )
        return _combine(findings)

    recovered = next(
        (
            row.get("pct_recovered")
            for row in a5.get("worst_case_grid", [])
            if row.get("dp_epsilon") == epsilon and row.get("secondary_suppression")
        ),
        None,
    )
    if recovered:
        findings.append(
            _broken(
                f"{_pct(recovered)} of suppressed cells can be recovered by subtraction.",
                f"A5: {_pct(recovered)} recovered",
            )
        )
    else:
        findings.append(
            _ok(
                "Secondary suppression holds: no suppressed cell can be recovered by "
                "subtracting its neighbours.",
                "A5: 0.0% of suppressed cells recovered",
            )
        )

    point = next(
        (row for row in a6.get("worst_case_grid", []) if row.get("dp_epsilon") == epsilon),
        {},
    )
    accuracy = point.get("attacker_accuracy_pct")
    bound = point.get("theoretical_bound_pct")
    if accuracy is not None and bound is not None:
        if accuracy > bound:
            findings.append(
                _broken(
                    f"Membership inference reaches {_pct(accuracy)}, beyond the "
                    f"{_pct(bound)} the privacy budget allows.",
                    f"A6: {_pct(accuracy)} vs bound {_pct(bound)}",
                )
            )
        elif accuracy > 50.0:
            findings.append(
                _weak(
                    f"Membership inference reaches {_pct(accuracy)} against a 50% coin flip — "
                    f"a real edge, but inside the {_pct(bound)} the budget allows.",
                    f"A6: {_pct(accuracy)} vs 50% baseline, bound {_pct(bound)}",
                )
            )
        else:
            findings.append(
                _ok(
                    "Membership inference does no better than guessing.",
                    f"A6: {_pct(accuracy)}",
                )
            )
    return _combine(findings)


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #

SCORERS = {
    ("record", "no_record_isolation"): lambda risk, k, eps, approach: _record_isolation(risk, k, approach),
    ("record", "no_linkage"): lambda risk, k, eps, approach: _record_linkage(risk, approach),
    ("record", "no_inference"): lambda risk, k, eps, approach: _record_inference(risk, approach),
    ("aggregate", "no_record_isolation"): lambda risk, k, eps, approach: _aggregate_isolation(risk, k, approach),
    ("aggregate", "no_linkage"): lambda risk, k, eps, approach: _aggregate_linkage(risk, approach),
    ("aggregate", "no_inference"): lambda risk, k, eps, approach: _aggregate_inference(risk, eps, approach),
}


def score_all(risk_eval: dict | None, k: int = 10, epsilon: float | None = 1.0) -> list[dict]:
    """Every (criterion x release x approach) verdict, with its reasoning."""
    rows = []
    for criterion in CRITERIA:
        row: dict[str, Any] = {"criterion": criterion, "label": CRITERION_LABELS[criterion]}
        for release in RELEASES:
            for approach in APPROACHES:
                scorer = SCORERS[(release, criterion)]
                row[f"{release}_{approach}"] = scorer(risk_eval, k, epsilon, approach)
        rows.append(row)
    return rows


def counterfactual_linkage(risk_eval: dict | None) -> dict | None:
    """A2's trajectory figure, framed as why linkage was removed rather than
    as a verdict on a release that has no linkable records."""
    a2 = _attack(risk_eval, "A2")
    if not a2:
        return None
    worst = a2.get("record", {}).get("worst_case", {}).get("results", [])
    four = next((row for row in worst if row.get("p") == 4), {})
    unique = four.get("pct_unique_if_rows_were_linkable")
    if unique is None:
        return None
    return {
        "headline": f"if rows were linkable, {unique:.1f}% unique at 4 points",
        "detail": (
            "That is the counterfactual we designed against, not a property of either "
            "release. Neither release keeps a subscriber key, so the attack has nothing "
            "to join on — which is exactly why the key was destroyed rather than hashed."
        ),
        "pct_unique_if_linkable": unique,
    }
