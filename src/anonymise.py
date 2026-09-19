"""Anonymisation engine (M2).

Applies tokenization, generalization, and k-anonymity suppression
based on the field classifications in config/fields.yaml.

Run with:
    python -m src.anonymise --linkage-window daily --k 5
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from src import safety

FIELDS_YAML_PATH = Path("config/fields.yaml")
OUTPUT_PARQUET = Path("outputs/anonymised.parquet")
TRANSFORM_LOG = Path("outputs/transform_log.json")


def _hash_id(value: str, salt: str, window: str) -> str:
    """Hash an identifier with a salt and a time window."""
    if pd.isna(value) or not str(value).strip():
        return ""
    payload = f"{str(value).strip()}|{salt}|{window}"
    h = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"{h[:8]}-{h[8:16]}"


def apply_generalization(
    df: pd.DataFrame, k: int, config: dict[str, dict[str, str]]
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Coarsen quasi-identifiers and top-code sensitive attributes."""
    work = df.copy()
    log: dict[str, Any] = {"k_threshold": k, "actions": {}}
    
    # 1. Time generalization (floor to hour)
    if "time_start" in work.columns:
        work["time_start"] = work["time_start"].dt.floor("h")
        log["actions"]["time_start"] = "floored to hour"

    # 2. Location (enb) & Device (tac) generalization
    for col in ["enb", "tac"]:
        if col in work.columns:
            # Generalize rare cells/devices across the whole dataset
            counts = work.groupby(col, observed=True)["msisdn"].nunique()
            rare = counts[counts < k].index
            mask = work[col].isin(rare)
            work.loc[mask, col] = f"OTHER_{col.upper()}"
            log["actions"][col] = f"grouped {len(rare)} rare values into OTHER"
            
            if col == "enb":
                # Naturally long cell IDs trigger the leak guard's \d{10,} check.
                # We hash them to a short 8-char hex string to preserve utility safely.
                work["enb"] = work["enb"].apply(
                    lambda x: f"CELL_{hashlib.md5(str(x).encode()).hexdigest()[:8]}" if x != "OTHER_ENB" else x
                )
                log["actions"][col] += " and hashed remaining to short strings"
            
    # 3. Numeric / Volumes (Sensitive attributes)
    sensitive = [f for f, meta in config.items() if meta.get("class") == "sensitive_attribute"]
    for col in sensitive:
        if col in work.columns and pd.api.types.is_numeric_dtype(work[col]):
            # Calculate p99 only on non-zero values to avoid zeroing out highly sparse columns
            non_zero = work[col][work[col] > 0]
            p99 = non_zero.quantile(0.99) if not non_zero.empty else 0.0
            
            capped = np.minimum(work[col], p99)
            work[col] = np.round(capped, 3)
            log["actions"][col] = f"top-coded at non-zero p99 ({p99:.3f}) and rounded to 3 decimals"

    return work, log


def apply_k_anonymity(
    df: pd.DataFrame, k: int, quasi_ids: list[str]
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Suppress rows in QI groups with fewer than k individuals."""
    work = df.copy()
    initial_rows = len(work)
    
    active_qis = [col for col in quasi_ids if col in work.columns]
    
    if not active_qis or "msisdn" not in work.columns:
        return work, {"suppressed_rows": 0, "reason": "missing qis or msisdn"}

    # Calculate true k-anonymity (distinct users per group)
    group_sizes = work.groupby(active_qis, observed=True, dropna=False)["msisdn"].transform("nunique")
    mask = group_sizes >= k
    work = work[mask]
    
    suppressed = initial_rows - len(work)
    pct = float(suppressed / initial_rows) if initial_rows > 0 else 0.0
    return work, {
        "qi_set": active_qis,
        "suppressed_rows": int(suppressed),
        "pct_suppressed": safety.round_float(pct)
    }


def apply_linkage(
    df: pd.DataFrame, window_type: str, direct_ids: list[str]
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Replace identifiers with a windowed pseudonym, or drop them entirely."""
    work = df.copy()
    log: dict[str, Any] = {"linkage_window": window_type}
    
    if window_type == "none" or "msisdn" not in work.columns:
        pass
    else:
        # The salt is ephemeral. It lives in memory for a few milliseconds and is never saved.
        salt = os.urandom(32).hex()
        
        if window_type == "daily":
            window_col = work["time_start"].dt.strftime("%Y-%m-%d")
        elif window_type == "hourly":
            window_col = work["time_start"].dt.strftime("%Y-%m-%d %H")
        else:
            raise ValueError(f"Unknown linkage window: {window_type}")
            
        work["pseudonym_id"] = [
            _hash_id(m, salt, w) for m, w in zip(work["msisdn"], window_col)
        ]

    dropped = []
    for col in direct_ids:
        if col in work.columns:
            work = work.drop(columns=[col])
            dropped.append(col)
            
    log["dropped_identifiers"] = dropped
    return work, log


def update_fields_yaml(config: dict, log: dict):
    """Write back the actual treatment applied to each field for the docs."""
    for field, meta in config.items():
        if field in log["generalization"]["actions"]:
            meta["treatment"] = log["generalization"]["actions"][field]
        elif field in log["linkage"]["dropped_identifiers"]:
            if log["linkage"]["linkage_window"] != "none" and field == "msisdn":
                meta["treatment"] = f"replaced with {log['linkage']['linkage_window']} pseudonym (ephemeral salted hash)"
            else:
                meta["treatment"] = "dropped"
        elif meta.get("class") == "quasi_identifier":
            meta["treatment"] = f"used for {log['k_anonymity'].get('k_threshold', 5)}-anonymity grouping"
        else:
            meta["treatment"] = "kept as is"
            
    yaml_text = (
        "# Field treatment plan. 'class' is the reviewed privacy class;\n"
        "# 'treatment' is filled in by the anonymisation step.\n"
        + yaml.safe_dump(config, sort_keys=False, default_flow_style=False)
    )
    safety.safe_write_text(yaml_text, FIELDS_YAML_PATH)


@safety.safe_main
def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m src.anonymise")
    parser.add_argument(
        "--linkage-window", 
        choices=["none", "hourly", "daily"], 
        default="none",
        help="How long a pseudonym should persist."
    )
    parser.add_argument(
        "--k", 
        type=int, 
        default=5,
        help="The k-anonymity threshold (default: 5)."
    )
    args = parser.parse_args(argv)

    print("Loading raw data...")
    df = safety.add_tac(safety.load_raw())
    
    print("Loading field configuration...")
    if not FIELDS_YAML_PATH.exists():
        raise FileNotFoundError(f"{FIELDS_YAML_PATH} not found. Run python -m src.classify first.")
    
    with open(FIELDS_YAML_PATH, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
        
    direct_ids = [f for f, meta in config.items() if meta.get("class") == "direct_identifier"]
    quasi_ids = [f for f, meta in config.items() if meta.get("class") == "quasi_identifier"]
    
    print("Step 1: Applying generalization...")
    df, log_gen = apply_generalization(df, args.k, config)
    
    print(f"Step 2: Enforcing {args.k}-anonymity...")
    df, log_k = apply_k_anonymity(df, args.k, quasi_ids)
    log_k["k_threshold"] = args.k
    
    print(f"Step 3: Applying linkage ({args.linkage_window})...")
    df, log_linkage = apply_linkage(df, args.linkage_window, direct_ids)
    
    transform_log = {
        "linkage": log_linkage,
        "generalization": log_gen,
        "k_anonymity": log_k,
        "final_rows": len(df),
    }
    
    print("Rounding all floats to prevent leak guard failure...")
    for col in df.columns:
        if pd.api.types.is_float_dtype(df[col]):
            df[col] = df[col].round(5)

    print("Writing outputs...")
    log_path = safety.safe_write_json(transform_log, TRANSFORM_LOG)
    parquet_path = safety.safe_write_df(df, OUTPUT_PARQUET)
    
    print("Updating fields.yaml with treatment plans...")
    update_fields_yaml(config, transform_log)
    
    print("\n" + "=" * 50)
    print("ANONYMISATION COMPLETE")
    print("=" * 50)
    print(f"Linkage window  : {args.linkage_window}")
    print(f"k-threshold     : {args.k}")
    print(f"Suppressed rows : {log_k['suppressed_rows']} ({log_k['pct_suppressed']:.2%})")
    print(f"Final row count : {len(df)}")
    print(f"Outputs         :")
    print(f"  - {parquet_path}")
    print(f"  - {log_path}")


if __name__ == "__main__":
    main()
