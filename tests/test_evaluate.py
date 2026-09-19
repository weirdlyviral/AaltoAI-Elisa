"""Tests for the M3 attack suite.

Synthetic data only. These assert that each attack actually measures something:
an attack that returns a constant would fail here.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src import anonymise, evaluate, safety

BUCKET = pd.Timestamp("2027-04-30 16:00:00")


@pytest.fixture(autouse=True)
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    secure = tmp_path / "secure"
    (secure / "tmp").mkdir(parents=True)
    monkeypatch.setenv("SECURE_DIR", str(secure))
    saved = set(safety._REGISTRY)
    safety._REGISTRY.clear()
    yield secure
    safety._REGISTRY.clear()
    safety._REGISTRY.update(saved)


def make_cells(counts: list[int], province: str = "P0") -> pd.DataFrame:
    """One (time_bucket, province) slice with the given true cell counts."""
    return pd.DataFrame(
        {
            "time_bucket": [BUCKET] * len(counts),
            "province": [province] * len(counts),
            "radio_access_type": ["5G"] * len(counts),
            "application_category": [f"App{i}" for i in range(len(counts))],
            "true_count": counts,
        }
    )


# --------------------------------------------------------------------------- #
# A5 - differencing
# --------------------------------------------------------------------------- #


def test_a5_lone_suppressed_cell_is_recovered_exactly_when_undefended():
    """No noise, no secondary suppression: subtraction reveals the hidden cell."""
    cells = make_cells([40, 25, 12, 6])  # only the 6 falls below the threshold

    sim = evaluate._simulate_aggregate(
        cells, minimum=10, epsilon=None, scale=None, secondary=False, seed=42
    )
    attempted, recovered, lone = evaluate.attempt_differencing(
        sim, ["time_bucket", "province"], tolerance=2
    )

    assert attempted == 1
    assert lone == 1
    assert recovered == 1, "the undefended attack must succeed, or the test proves nothing"


def test_a5_secondary_suppression_blocks_the_recovery():
    """The same slice, with secondary suppression: two unknowns, one equation."""
    cells = make_cells([40, 25, 12, 6])

    sim = evaluate._simulate_aggregate(
        cells, minimum=10, epsilon=None, scale=None, secondary=True, seed=42
    )
    attempted, recovered, lone = evaluate.attempt_differencing(
        sim, ["time_bucket", "province"], tolerance=2
    )

    assert attempted == 2, "the smallest survivor (12) is suppressed too"
    assert lone == 0, "no slice loses exactly one cell any more"
    assert recovered == 0


def test_a5_noise_alone_also_degrades_the_recovery():
    cells = make_cells([40, 25, 12, 6])

    sim = evaluate._simulate_aggregate(
        cells, minimum=10, epsilon=1.0, scale=11.0, secondary=False, seed=7
    )
    _, recovered, _ = evaluate.attempt_differencing(
        sim, ["time_bucket", "province"], tolerance=2
    )

    assert recovered == 0, "Laplace(11) noise puts the estimate outside +/-2"


def test_simulate_aggregate_suppresses_on_the_published_count():
    cells = make_cells([40, 25, 12, 6])
    sim = evaluate._simulate_aggregate(
        cells, minimum=10, epsilon=None, scale=None, secondary=False, seed=42
    )

    assert sim.loc[sim["true_count"] == 6, "suppressed"].all()
    assert not sim.loc[sim["true_count"] == 40, "suppressed"].any()


# --------------------------------------------------------------------------- #
# A6 - membership inference
# --------------------------------------------------------------------------- #


def test_a6_attacker_is_certain_without_noise():
    with_target = np.array([50.0, 30.0, 20.0])
    without_target = with_target - 1.0
    rng = np.random.default_rng(42)

    correct, trials = evaluate.membership_game(with_target, without_target, None, 200, rng)

    assert correct / trials == 1.0, "with no noise the count reveals membership exactly"


def test_a6_accuracy_falls_toward_guessing_as_epsilon_shrinks():
    with_target = np.array([50.0, 30.0, 20.0])
    without_target = with_target - 1.0

    def accuracy(scale: float) -> float:
        rng = np.random.default_rng(42)
        correct, trials = evaluate.membership_game(
            with_target, without_target, scale, 4000, rng
        )
        return correct / trials

    tight = accuracy(40.0)   # very small epsilon
    loose = accuracy(2.0)    # large epsilon

    assert loose > tight, "less noise must help the attacker"
    assert tight < 0.60, "heavy noise must push the attacker toward random guessing"
    assert 0.40 < tight


def test_a6_never_beats_the_differential_privacy_bound():
    """A measured accuracy above e^eps/(1+e^eps) means the scale is wrong.

    This is the check that caught evaluate.py reading a contribution bound of 1
    while the release used 11.
    """
    cells = 5
    with_target = np.full(cells, 50.0)
    without_target = with_target - 1.0
    epsilon = 1.0
    scale = 11.0

    rng = np.random.default_rng(42)
    correct, trials = evaluate.membership_game(with_target, without_target, scale, 5000, rng)
    accuracy = correct / trials
    bound = float(np.exp(epsilon) / (1 + np.exp(epsilon)))

    assert accuracy <= bound + 0.02, f"{accuracy:.3f} exceeds the DP bound {bound:.3f}"


# --------------------------------------------------------------------------- #
# Contribution bounding
# --------------------------------------------------------------------------- #


def test_contribution_bound_prefers_the_configured_value():
    prepared = pd.DataFrame({anonymise.SUBSCRIBER: ["a", "b"]})

    assert evaluate.contribution_bound(prepared, {"max_cells_per_subscriber": 11}) == 11


def test_contribution_bound_is_derived_when_absent_and_never_defaults_to_one():
    """Falling back to 1 would understate the Laplace scale by the bound itself."""
    rows = []
    for subscriber in range(20):
        for cell in range(6):
            rows.append(
                {
                    anonymise.SUBSCRIBER: f"s{subscriber}",
                    "time_bucket": BUCKET,
                    "province": "P0",
                    "radio_access_type": "5G",
                    "application_category": f"App{cell}",
                }
            )
    prepared = pd.DataFrame(rows)

    bound = evaluate.contribution_bound(prepared, {})

    assert bound == 6, "each subscriber touches 6 distinct cells"
    assert bound != 1


# --------------------------------------------------------------------------- #
# Output hygiene
# --------------------------------------------------------------------------- #


def test_eval_index_never_reaches_an_output(tmp_path: Path):
    """Only aggregates derived from the subscriber map may be written."""
    safety._REGISTRY.add("358401234567")
    results = [
        {
            "id": "A1",
            "name": "Row uniqueness",
            "criterion": "singling_out",
            "attacker_knowledge": "QI values",
            "baseline_raw": "-",
            "record": {"pct_rows_in_groups_of_1": 0.0, "n_groups": 12},
            "interpretation": "measured",
        }
    ]
    payload = {"seed": safety.SEED, "attacks": results}

    path = safety.safe_write_json(payload, tmp_path / "risk_eval.json")

    text = path.read_text()
    assert "358401234567" not in text
    assert anonymise.SUBSCRIBER not in text, "the internal subscriber key must not appear"
    assert safety.check_file(path) == []


def test_report_is_written_through_a_safe_writer(tmp_path: Path):
    """docs/risk_assessment.md must not be written with a bare open()."""
    source = Path("src/evaluate.py").read_text()

    assert "safety.safe_write_text(render_report" in source
    assert "open(RISK_DOC_PATH" not in source


def test_every_attack_is_actually_computed():
    """Guards against an attack regressing to a hardcoded constant."""
    import ast

    tree = ast.parse(Path("src/evaluate.py").read_text())
    runners = {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name.startswith("run_a")
    }
    assert set(runners) == {"run_a1", "run_a2", "run_a3", "run_a4", "run_a5", "run_a6"}
    for name, node in runners.items():
        computing = [n for n in node.body if not isinstance(n, (ast.Return, ast.Expr))]
        assert computing, f"{name} returns a constant - it measures nothing"
