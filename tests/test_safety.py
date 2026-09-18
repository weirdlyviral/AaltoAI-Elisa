"""Tests for the safety layer.

Every test builds its own tiny synthetic frame and points SECURE_DIR at a
pytest tmp_path, so no real data is ever touched.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest

from src import safety

# Synthetic identifiers - fabricated, never from the real dataset.
FAKE_MSISDN = "358401234567"
FAKE_IMSI = "244120000000001"
FAKE_IMEI = "356938035643809"
CLEAN_IMEI = "aabbccddeeffgg"


def make_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "time_start": pd.to_datetime(["2026-01-01 10:00:00", "2026-01-01 11:00:00"]),
            "msisdn": pd.Series([FAKE_MSISDN, "358409999999"], dtype="string"),
            "imsi": pd.Series([FAKE_IMSI, "244120000000002"], dtype="string"),
            "imei": pd.Series([FAKE_IMEI, "356938035643810"], dtype="string"),
            "enb": ["ENB1", "ENB2"],
            "data_GB_sum": [1.5, 2.5],
        }
    )


@pytest.fixture(autouse=True)
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Point SECURE_DIR at tmp_path and give each test a fresh registry."""
    secure = tmp_path / "secure"
    (secure / "tmp").mkdir(parents=True)
    monkeypatch.setenv("SECURE_DIR", str(secure))
    monkeypatch.setenv("DATASET_FILE", "raw.parquet")
    saved = set(safety._REGISTRY)
    safety._REGISTRY.clear()
    yield secure
    safety._REGISTRY.clear()
    safety._REGISTRY.update(saved)


def register_fakes() -> None:
    safety.register_identifiers(make_df())


# --------------------------------------------------------------------------- #
# load_raw
# --------------------------------------------------------------------------- #


def test_load_raw_registers_ids_and_keeps_strings(isolated_env: Path):
    raw = isolated_env / "raw.parquet"
    make_df().to_parquet(raw, index=False)

    df = safety.load_raw()

    assert safety.registry_size() == 6  # 2 rows x 3 identifier columns
    assert FAKE_MSISDN in safety._REGISTRY
    assert all(isinstance(v, str) for v in df["msisdn"].tolist())
    assert pd.api.types.is_datetime64_any_dtype(df["time_start"])


def test_load_raw_preserves_leading_zeros_from_csv(isolated_env: Path):
    raw = isolated_env / "lead.csv"
    make_df().assign(msisdn=["0044123456789", "0044123456780"]).to_csv(raw, index=False)

    df = safety.load_raw(raw)

    assert df["msisdn"].iloc[0].startswith("00")


def test_load_raw_refuses_path_outside_secure_dir(tmp_path: Path):
    outside = tmp_path / "elsewhere.csv"
    make_df().to_csv(outside, index=False)

    with pytest.raises(PermissionError):
        safety.load_raw(outside)


# --------------------------------------------------------------------------- #
# scrub
# --------------------------------------------------------------------------- #


def test_scrub_removes_registered_msisdn_in_a_sentence():
    register_fakes()

    out = safety.scrub(f"Subscriber {FAKE_MSISDN} had a bad session on ENB1.")

    assert FAKE_MSISDN not in out
    assert "[REDACTED]" in out
    assert "bad session on ENB1" in out


def test_scrub_masks_unregistered_long_digit_runs():
    out = safety.scrub("trace id 12345678901234 seen")

    assert "[DIGITS]" in out
    assert "12345678901234" not in out


def test_scrub_leaves_ordinary_text_alone():
    assert safety.scrub("p95 rtt = 42.5 ms over 1200 rows") == "p95 rtt = 42.5 ms over 1200 rows"


# --------------------------------------------------------------------------- #
# Findings
# --------------------------------------------------------------------------- #


def test_finding_rejects_unknown_kind():
    with pytest.raises(ValueError):
        safety.Finding("f.csv", "col", "something_else")


def test_finding_repr_never_contains_the_value(tmp_path: Path):
    register_fakes()
    path = tmp_path / "leaky.csv"
    pd.DataFrame({"device": [FAKE_IMEI]}).to_csv(path, index=False)

    findings = safety.check_file(path)

    assert findings
    for finding in findings:
        assert FAKE_IMEI not in repr(finding)
        assert FAKE_IMEI not in str(finding)
        assert FAKE_IMEI not in json.dumps(finding.__dict__)


def test_check_file_flags_registered_imei_in_csv(tmp_path: Path):
    register_fakes()
    path = tmp_path / "leaky.csv"
    pd.DataFrame({"device": [FAKE_IMEI], "enb": ["ENB1"]}).to_csv(path, index=False)

    findings = safety.check_file(path)

    assert [f.kind for f in findings] == ["registered_id"]
    assert findings[0].location == "device"


def test_check_file_returns_empty_for_clean_csv(tmp_path: Path):
    register_fakes()
    path = tmp_path / "clean.csv"
    pd.DataFrame({"device": [CLEAN_IMEI], "rows": [17]}).to_csv(path, index=False)

    assert safety.check_file(path) == []


def test_check_file_flags_text_file_with_line_location(tmp_path: Path):
    register_fakes()
    path = tmp_path / "notes.md"
    path.write_text(f"# Report\nworst subscriber: {FAKE_MSISDN}\n", encoding="utf-8")

    findings = safety.check_file(path)

    assert len(findings) == 1
    assert findings[0].location == "line 2"
    assert FAKE_MSISDN not in repr(findings[0])


def test_check_file_ignores_unsupported_suffix(tmp_path: Path):
    register_fakes()
    path = tmp_path / "blob.bin"
    path.write_text(FAKE_MSISDN, encoding="utf-8")

    assert safety.check_file(path) == []


# --------------------------------------------------------------------------- #
# leak_guard
# --------------------------------------------------------------------------- #


def test_leak_guard_true_when_clean_false_when_leaking(tmp_path: Path, capsys):
    register_fakes()
    out = tmp_path / "outputs"
    out.mkdir()
    (out / "ok.json").write_text(json.dumps({"n_distinct": 5}), encoding="utf-8")

    assert safety.leak_guard(out) is True

    (out / "nested").mkdir()
    (out / "nested" / "bad.json").write_text(json.dumps({"top": FAKE_IMSI}), encoding="utf-8")

    assert safety.leak_guard(out) is False
    captured = capsys.readouterr().out
    assert FAKE_IMSI not in captured
    assert "registered_id" in captured


# --------------------------------------------------------------------------- #
# safe_main
# --------------------------------------------------------------------------- #


def test_safe_main_output_never_contains_the_id(capsys):
    register_fakes()

    @safety.safe_main
    def boom():
        raise ValueError(f"failed while handling subscriber {FAKE_MSISDN}")

    with pytest.raises(SystemExit) as exc:
        boom()

    assert exc.value.code == 1
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert FAKE_MSISDN not in combined
    assert "[REDACTED]" in combined
    assert "ValueError" in combined


# --------------------------------------------------------------------------- #
# Guarded writes
# --------------------------------------------------------------------------- #


def test_safe_write_df_refuses_msisdn_column(tmp_path: Path):
    register_fakes()
    df = pd.DataFrame({"msisdn": ["358401234567"], "rows": [3]})

    with pytest.raises(safety.LeakError) as exc:
        safety.safe_write_df(df, tmp_path / "out.csv")

    assert "msisdn" in str(exc.value)
    assert not (tmp_path / "out.csv").exists()


def test_safe_write_df_accepts_aggregate_frame(tmp_path: Path):
    register_fakes()
    df = pd.DataFrame({"enb": ["ENB1", "ENB2"], "n_rows": [10, 20]})

    target = safety.safe_write_df(df, tmp_path / "agg.csv")

    assert target.exists()
    assert safety.check_file(target) == []


def test_safe_write_df_refuses_registered_value_in_a_plain_column(tmp_path: Path):
    register_fakes()
    df = pd.DataFrame({"label": [FAKE_IMEI], "n": [1]})

    with pytest.raises(safety.LeakError):
        safety.safe_write_df(df, tmp_path / "sneaky.csv")

    assert not (tmp_path / "sneaky.csv").exists()


def test_safe_write_json_round_trip_and_refusal(tmp_path: Path, isolated_env: Path):
    register_fakes()

    target = safety.safe_write_json({"n_distinct": 12, "p50": 1.25}, tmp_path / "ok.json")
    assert json.loads(target.read_text())["n_distinct"] == 12

    with pytest.raises(safety.LeakError):
        safety.safe_write_json({"worst": FAKE_MSISDN}, tmp_path / "bad.json")
    assert not (tmp_path / "bad.json").exists()
    # The staging area must not retain the rejected payload.
    assert list((isolated_env / "tmp").iterdir()) == []


# --------------------------------------------------------------------------- #
# llm_gateway
# --------------------------------------------------------------------------- #


def test_llm_gateway_raises_before_calling_the_client(monkeypatch: pytest.MonkeyPatch):
    register_fakes()
    import openai

    mock_openai = MagicMock()
    monkeypatch.setattr(openai, "OpenAI", mock_openai)
    monkeypatch.setenv("LLM_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_MODEL", "test-model")

    with pytest.raises(safety.LeakError):
        safety.llm_gateway(f"Classify the subscriber {FAKE_MSISDN}", "unit_test")

    mock_openai.assert_not_called()


def test_llm_gateway_raises_on_registered_value_in_system_prompt(monkeypatch: pytest.MonkeyPatch):
    register_fakes()
    import openai

    mock_openai = MagicMock()
    monkeypatch.setattr(openai, "OpenAI", mock_openai)
    monkeypatch.setenv("LLM_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_MODEL", "test-model")

    with pytest.raises(safety.LeakError):
        safety.llm_gateway("Hello", "unit_test", system=f"Context: {FAKE_IMEI}")

    mock_openai.assert_not_called()


def test_llm_gateway_logs_a_clean_call(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    register_fakes()
    import openai

    response = MagicMock()
    response.choices = [MagicMock(message=MagicMock(content="OK"))]
    client = MagicMock()
    client.chat.completions.create.return_value = response
    monkeypatch.setattr(openai, "OpenAI", MagicMock(return_value=client))
    monkeypatch.setenv("LLM_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_MODEL", "test-model")
    log = tmp_path / "llm_calls.jsonl"
    monkeypatch.setattr(safety, "LLM_LOG_PATH", log)

    out = safety.llm_gateway("Reply with OK", "unit_test")

    assert out == "OK"
    record = json.loads(log.read_text().strip())
    assert record["purpose"] == "unit_test"
    assert record["endpoint_host"] == "example.invalid"
    assert record["model"] == "test-model"
    assert len(record["prompt_sha256"]) == 64


# --------------------------------------------------------------------------- #
# wipe_secure_tmp
# --------------------------------------------------------------------------- #


def test_wipe_secure_tmp_reports_names_and_count(isolated_env: Path, capsys):
    tmp = isolated_env / "tmp"
    (tmp / "a.json").write_text("{}", encoding="utf-8")
    (tmp / "b.csv").write_text("x\n1\n", encoding="utf-8")

    removed = safety.wipe_secure_tmp()

    assert removed == 2
    assert list(tmp.iterdir()) == []
    assert "removed 2" in capsys.readouterr().out


# --------------------------------------------------------------------------- #
# Schema normalisation
# --------------------------------------------------------------------------- #


def test_load_raw_parses_epoch_second_time_start(isolated_env: Path):
    """The shipped parquet stores time_start as int64 epoch seconds."""
    raw = isolated_env / "epoch.parquet"
    make_df().assign(time_start=[1809100800, 1809101400]).to_parquet(raw, index=False)

    df = safety.load_raw(raw)

    assert pd.api.types.is_datetime64_any_dtype(df["time_start"])
    assert df["time_start"].min().year == 2027
    assert (df["time_start"].max() - df["time_start"].min()).total_seconds() == 600


def test_load_raw_renames_enb_id_to_enb(isolated_env: Path):
    raw = isolated_env / "alias.parquet"
    make_df().rename(columns={"enb": "enb_id"}).to_parquet(raw, index=False)

    df = safety.load_raw(raw)

    assert "enb" in df.columns
    assert "enb_id" not in df.columns


def test_add_tac_takes_first_eight_imei_chars():
    df = safety.add_tac(make_df())

    assert df["tac"].tolist() == [FAKE_IMEI[:8], "35693803"]
    assert df["tac"].str.len().eq(8).all()


def test_safe_write_text_round_trip_and_refusal(tmp_path: Path):
    register_fakes()

    target = safety.safe_write_text("msisdn:\n  class: direct_identifier\n", tmp_path / "f.yaml")
    assert "direct_identifier" in target.read_text()

    with pytest.raises(safety.LeakError):
        safety.safe_write_text(f"note: {FAKE_IMSI}\n", tmp_path / "bad.yaml")
    assert not (tmp_path / "bad.yaml").exists()
