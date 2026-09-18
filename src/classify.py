"""LLM-assisted field classification with a human in the loop.

Reads only ``outputs/profile.json`` (aggregates) and
``docs/dataset_description.txt`` - never the raw data. Asks the LLM to propose a
privacy class per field, then lets a human reviewer accept or override each
proposal before anything is written.

Run with::

    python -m src.classify                  # interactive review
    python -m src.classify --non-interactive  # accept every proposal (reviewer "auto")
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from src import safety

PROFILE_PATH = Path("outputs/profile.json")
DESCRIPTION_PATH = Path("docs/dataset_description.txt")
CLASSIFICATION_PATH = Path("outputs/classification.json")
FIELDS_YAML_PATH = Path("config/fields.yaml")

VALID_CLASSES = (
    "direct_identifier",
    "quasi_identifier",
    "sensitive_attribute",
    "non_identifying",
)

EXPECTED_FIELDS = (
    "time_start",
    "msisdn",
    "imsi",
    "imei",
    "tp_dl_avg",
    "tp_ul_avg",
    "tp_dl_filtered_avg",
    "cont_rtt_radio_avg",
    "cont_rtt_internet_avg",
    "initial_rtt_radio_avg",
    "tcp_retrans_byte_ratio_downlink_avg",
    "tcp_retrans_byte_ratio_uplink_avg",
    "http_response_time_avg",
    "http_sr_avg",
    "data_GB_sum",
    "im_video_GB_sum",
    "im_audio_GB_sum",
    "tethering_data_GB_dl_sum",
    "radio_access_type",
    "province",
    "application_category",
    "enb",
    "tac",
)

MAX_RATIONALE_WORDS = 40
MAX_TREATMENT_WORDS = 25
#: Category labels shown per categorical column - enough to judge separating
#: power without shipping the whole distribution into the prompt.
TOP_CATEGORIES = 10

SYSTEM_PROMPT = (
    "You are a data protection engineer classifying fields of a mobile network "
    "performance dataset for a privacy-preserving anonymisation pipeline. "
    "You answer with JSON only."
)


class ValidationFailure(ValueError):
    """The model's answer did not satisfy the output contract."""


# --------------------------------------------------------------------------- #
# Prompt construction
# --------------------------------------------------------------------------- #


def profile_digest(profile: dict) -> dict[str, Any]:
    """Compact the profile so the prompt carries signal, not bulk."""
    digest: dict[str, Any] = {
        "n_rows": profile.get("n_rows"),
        "structure": profile.get("structure"),
        "columns": {},
    }
    for name, stats in profile.get("columns", {}).items():
        entry = {
            key: stats.get(key)
            for key in ("dtype", "null_rate", "n_distinct")
            if key in stats
        }
        for key in ("min_length", "max_length", "mode_length", "share_all_digits"):
            if key in stats:
                entry[key] = stats[key]
        for key in ("min", "p50", "p99", "max", "share_zero"):
            if key in stats:
                entry[key] = stats[key]
        counts = stats.get("value_counts")
        if counts:
            top = list(counts.items())[:TOP_CATEGORIES]
            entry["top_values"] = dict(top)
            entry["n_values_shown"] = len(top)
        for key in ("rows_per_enb", "distinct_msisdn_per_enb", "n_enb_with_lt5_msisdn"):
            if key in stats:
                entry[key] = stats[key]
        digest["columns"][name] = entry
    return digest


def build_prompt(profile: dict, description: str, error: str | None = None) -> str:
    fields = "\n".join(f"- {name}" for name in EXPECTED_FIELDS)
    prompt = f"""Classify every field of the dataset below into exactly one privacy class.

Allowed classes (choose exactly one per field):
- direct_identifier: on its own identifies a person or their device/SIM.
- quasi_identifier: does not identify alone, but combined with other fields or
  outside knowledge it can single out a person.
- sensitive_attribute: not identifying, but revealing about the person if linked.
- non_identifying: technical measurement with negligible re-identification value.

DATASET DESCRIPTION
-------------------
{description}

AGGREGATE PROFILE (no raw records; counts and distributions only)
----------------------------------------------------------------
{json.dumps(profile_digest(profile), indent=2)}

FIELDS TO CLASSIFY ({len(EXPECTED_FIELDS)} in total, every one is required)
{fields}

OUTPUT CONTRACT
---------------
Return a JSON array only. No prose, no markdown fences. One object per field:
{{
  "field": "<one of the field names above>",
  "class": "<one of: {', '.join(VALID_CLASSES)}>",
  "rationale": "<at most {MAX_RATIONALE_WORDS} words>",
  "proposed_treatment": "<at most {MAX_TREATMENT_WORDS} words>",
  "confidence": <number between 0 and 1>
}}
Include all {len(EXPECTED_FIELDS)} fields exactly once. Do not invent fields."""

    if error:
        prompt += (
            "\n\nYour previous answer was rejected by the validator. "
            f"Fix this and answer again:\n{error}"
        )
    return prompt


# --------------------------------------------------------------------------- #
# Parsing and validation
# --------------------------------------------------------------------------- #


def strip_fences(text: str) -> str:
    """Remove ``` / ```json fences the model may wrap its answer in."""
    stripped = text.strip()
    match = re.search(r"```(?:json)?\s*(.*?)\s*```", stripped, flags=re.DOTALL)
    if match:
        stripped = match.group(1).strip()
    start, end = stripped.find("["), stripped.rfind("]")
    if start != -1 and end > start:
        stripped = stripped[start : end + 1]
    return stripped


def _trim_words(text: str, limit: int) -> str:
    words = str(text).split()
    return str(text).strip() if len(words) <= limit else " ".join(words[:limit]) + " ..."


def parse_and_validate(raw: str) -> list[dict[str, Any]]:
    """Parse the model answer and enforce the output contract."""
    try:
        payload = json.loads(strip_fences(raw))
    except json.JSONDecodeError as exc:
        raise ValidationFailure(f"Answer was not valid JSON: {exc.msg}") from exc

    if not isinstance(payload, list):
        raise ValidationFailure("Top-level value must be a JSON array.")

    proposals: dict[str, dict[str, Any]] = {}
    problems: list[str] = []
    for item in payload:
        if not isinstance(item, dict):
            problems.append("Every array element must be an object.")
            continue
        name = str(item.get("field", "")).strip()
        if name not in EXPECTED_FIELDS:
            problems.append(f"Unknown field name: {name!r}.")
            continue
        if name in proposals:
            problems.append(f"Field {name!r} appears more than once.")
            continue
        klass = str(item.get("class", "")).strip()
        if klass not in VALID_CLASSES:
            problems.append(f"Field {name!r} has invalid class {klass!r}.")
            continue
        try:
            confidence = float(item.get("confidence"))
        except (TypeError, ValueError):
            problems.append(f"Field {name!r} has a non-numeric confidence.")
            continue
        if not 0.0 <= confidence <= 1.0:
            problems.append(f"Field {name!r} has confidence outside [0, 1].")
            continue
        proposals[name] = {
            "field": name,
            "class": klass,
            # Word limits are trimmed rather than rejected: they affect
            # readability only, not the correctness of the classification.
            "rationale": _trim_words(item.get("rationale", ""), MAX_RATIONALE_WORDS),
            "proposed_treatment": _trim_words(
                item.get("proposed_treatment", ""), MAX_TREATMENT_WORDS
            ),
            "confidence": safety.round_float(confidence),
        }

    missing = [name for name in EXPECTED_FIELDS if name not in proposals]
    if missing:
        problems.append(f"Missing field(s): {', '.join(missing)}.")
    if problems:
        raise ValidationFailure(" ".join(problems))

    return [proposals[name] for name in EXPECTED_FIELDS]


def request_classification(profile: dict, description: str) -> list[dict[str, Any]]:
    """Ask the LLM, retrying once with the validation error appended."""
    error: str | None = None
    for attempt in (1, 2):
        prompt = build_prompt(profile, description, error)
        answer = safety.llm_gateway(prompt, "field_classification", system=SYSTEM_PROMPT)
        try:
            return parse_and_validate(answer)
        except ValidationFailure as exc:
            if attempt == 2:
                raise
            error = str(exc)
            print(f"Validation failed, retrying once: {safety.scrub(error)}")
    raise ValidationFailure("unreachable")  # pragma: no cover


# --------------------------------------------------------------------------- #
# Review
# --------------------------------------------------------------------------- #


def review(proposals: list[dict[str, Any]], interactive: bool) -> tuple[list[dict[str, Any]], str]:
    """Walk a human through every proposal (or auto-accept them all)."""
    if not interactive:
        reviewer = "auto"
    else:
        reviewer = input("Reviewer initials: ").strip() or "unknown"
        print(
            "\nFor each field: press Enter to accept, or type a new class to override.\n"
            f"Classes: {', '.join(VALID_CLASSES)}\n"
        )

    decided: list[dict[str, Any]] = []
    for index, proposal in enumerate(proposals, start=1):
        final_class = proposal["class"]
        override_reason = None

        if interactive:
            print("-" * 70)
            print(f"[{index}/{len(proposals)}] {proposal['field']}")
            print(f"  proposed class    : {proposal['class']} (confidence {proposal['confidence']})")
            print(f"  rationale         : {proposal['rationale']}")
            print(f"  proposed treatment: {proposal['proposed_treatment']}")
            while True:
                answer = input("  accept [Enter] or new class: ").strip()
                if not answer:
                    break
                if answer in VALID_CLASSES:
                    final_class = answer
                    override_reason = input("  reason (one line): ").strip() or "no reason given"
                    break
                print(f"  '{answer}' is not a valid class. Choose one of: {', '.join(VALID_CLASSES)}")

        decided.append(
            {
                "field": proposal["field"],
                "proposed_class": proposal["class"],
                "final_class": final_class,
                "overridden": final_class != proposal["class"],
                "override_reason": override_reason,
                "rationale": proposal["rationale"],
                "proposed_treatment": proposal["proposed_treatment"],
                "confidence": proposal["confidence"],
                "reviewer": reviewer,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )
    return decided, reviewer


# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #


def write_outputs(decided: list[dict[str, Any]], reviewer: str) -> tuple[Path, Path]:
    classification = safety.safe_write_json(
        {
            "reviewer": reviewer,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "n_fields": len(decided),
            "fields": decided,
        },
        CLASSIFICATION_PATH,
    )

    fields = {
        entry["field"]: {"class": entry["final_class"], "treatment": "TBD"} for entry in decided
    }
    yaml_text = (
        "# Field treatment plan. 'class' is the reviewed privacy class;\n"
        "# 'treatment' is filled in by the anonymisation step.\n"
        + yaml.safe_dump(fields, sort_keys=False, default_flow_style=False)
    )
    fields_yaml = safety.safe_write_text(yaml_text, FIELDS_YAML_PATH)
    return classification, fields_yaml


def print_summary(decided: list[dict[str, Any]]) -> None:
    width = max(len(entry["field"]) for entry in decided)
    print("\n" + "=" * (width + 46))
    print("FIELD CLASSIFICATION")
    print("=" * (width + 46))
    print(f"{'field':<{width}}  {'final class':<20} {'conf':>5}  overridden")
    print("-" * (width + 46))
    for entry in decided:
        flag = "yes" if entry["overridden"] else ""
        print(
            f"{entry['field']:<{width}}  {entry['final_class']:<20} "
            f"{entry['confidence']:>5}  {flag}"
        )
    counts: dict[str, int] = {}
    for entry in decided:
        counts[entry["final_class"]] = counts.get(entry["final_class"], 0) + 1
    print("-" * (width + 46))
    print("  ".join(f"{klass}: {count}" for klass, count in sorted(counts.items())))


@safety.safe_main
def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m src.classify")
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Accept every proposal without review (reviewer is recorded as 'auto').",
    )
    args = parser.parse_args(argv)

    if not PROFILE_PATH.exists():
        raise FileNotFoundError(f"{PROFILE_PATH} not found - run python -m src.profile first.")

    profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    description = DESCRIPTION_PATH.read_text(encoding="utf-8")

    proposals = request_classification(profile, description)
    decided, reviewer = review(proposals, interactive=not args.non_interactive)
    classification, fields_yaml = write_outputs(decided, reviewer)

    print_summary(decided)
    print(f"\nwritten: {classification}")
    print(f"written: {fields_yaml}")


if __name__ == "__main__":
    main()
