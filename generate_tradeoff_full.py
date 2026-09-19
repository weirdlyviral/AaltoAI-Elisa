# NOTE: this rewrites config/release.yaml for each grid point and yaml.safe_dump
# strips its comments. Restore it with `git checkout config/release.yaml` after
# a run. Produces outputs/tradeoff_grid.json, which the Trade-off Explorer reads.
import json
import yaml
import subprocess
import os


def _round_floats(obj):
    """Raw float repr (51.959999999999994) trips the leak guard's long-digit
    rule, so round before writing. Mirrors safety.round_float."""
    if isinstance(obj, dict):
        return {k: _round_floats(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_round_floats(v) for v in obj]
    if isinstance(obj, float):
        return round(obj, 6)
    return obj
import itertools
from copy import deepcopy

k_vals = [5, 10, 20]
tb_vals = [15, 60]
area_vals = ["enb_tokenised", "province"]
eps_vals = [0.5, 1.0, 2.0]

configs = []
for k, tb, am, eps in itertools.product(k_vals, tb_vals, area_vals, eps_vals):
    configs.append({"k": k, "time_bucket": tb, "area_mode": am, "epsilon": eps})

def load_yaml(path="config/release.yaml"):
    with open(path, "r") as f:
        return yaml.safe_load(f)

def save_yaml(data, path="config/release.yaml"):
    with open(path, "w") as f:
        yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False)

def run_pipeline():
    subprocess.run([".venv/bin/python", "-m", "src.anonymise"], check=True)
    subprocess.run([".venv/bin/python", "-m", "src.utility"], check=True)
    subprocess.run([".venv/bin/python", "-m", "src.evaluate"], check=True)

def get_metrics():
    with open("outputs/utility_eval.json", "r") as f:
        util = json.load(f)
    with open("outputs/risk_eval.json", "r") as f:
        risk = json.load(f)
    with open("outputs/release_stats_aggregate.json", "r") as f:
        stats = json.load(f)
    
    coverage = util.get("U2", {}).get("pct_subscribers_covered", 0)
    u1_pct_within_5pct = util.get("U1", {}).get("headline_pct_within_5pct", 0)
    
    input_cells = stats.get("n_cells_input", 1)
    output_cells = stats.get("n_cells_output", 0)
    pct_suppressed = 100.0 * (1 - (output_cells / max(input_cells, 1)))

    a6_acc = 100.0
    a6_bound = 100.0
    criteria = {
        "no_record_isolation": "fail",
        "no_linkage": "fail",
        "no_inference": "fail"
    }

    for attack in risk.get("attacks", []):
        if attack.get("id") == "A6":
            pts = attack.get("aggregate", {}).get("worst_case_grid", [])
            if pts:
                a6_acc = pts[0].get("attacker_accuracy_pct", 100.0)
                a6_bound = pts[0].get("theoretical_bound_pct", 100.0)
            crit_stat = attack.get("aggregate", {}).get("criterion_status", "fail")
            criteria["no_inference"] = crit_stat

        elif attack.get("id") == "A1":
            crit_stat = attack.get("record", {}).get("criterion_status", "fail")
            criteria["no_record_isolation"] = crit_stat
            
        elif attack.get("id") == "A2":
            crit_stat = attack.get("record", {}).get("criterion_status", "fail")
            criteria["no_linkage"] = crit_stat
            
    releasable = True
    for v in criteria.values():
        if v not in ("pass", "residual"):
            releasable = False

    return {
        "pct_suppressed": pct_suppressed,
        "coverage": coverage,
        "u1_pct_within_5pct": u1_pct_within_5pct,
        "a6_accuracy_pct": a6_acc,
        "a6_bound_pct": a6_bound
    }, criteria, releasable


# Load existing grid to continue or start fresh
grid_path = "outputs/tradeoff_grid.json"
grid_results = []
if os.path.exists(grid_path):
    with open(grid_path, "r") as f:
        grid_results = json.load(f)

# Filter configs that aren't already generated
existing_configs = [g["config"] for g in grid_results]
pending_configs = [c for c in configs if c not in existing_configs]

print(f"Total configs: {len(configs)}. Pending: {len(pending_configs)}.")

orig_yaml = load_yaml()

try:
    for c in pending_configs:
        print(f"Running config: {c}")
        cyaml = load_yaml()
        cyaml["k"] = c["k"]
        cyaml["time_bucket_minutes"] = c["time_bucket"]
        cyaml["area_mode"] = c["area_mode"]
        cyaml["dp_epsilon"] = c["epsilon"]
        
        save_yaml(cyaml)
        run_pipeline()
        metrics, criteria, releasable = get_metrics()
        
        grid_results.append({
            "config": c,
            "metrics": metrics,
            "criteria": criteria,
            "releasable": releasable
        })
        
        # Write progressively
        with open(grid_path, "w") as f:
            json.dump(_round_floats(grid_results), f, indent=2)
finally:
    # restore
    save_yaml(orig_yaml)
    run_pipeline()

print("Full tradeoff grid generated!")
