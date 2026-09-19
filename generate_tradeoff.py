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

configs = [
  {"k": 5, "time_bucket": 10, "area_mode": "enb_tokenised", "epsilon": None},
  {"k": 10, "time_bucket": 10, "area_mode": "enb_tokenised", "epsilon": 2.0},
  {"k": 10, "time_bucket": 10, "area_mode": "enb_tokenised", "epsilon": 1.0},
  {"k": 20, "time_bucket": 60, "area_mode": "province", "epsilon": 0.1}
]

grid_results = []

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
    
    # We need: pct_suppressed, coverage, u1_pct_within_5pct, a6_accuracy_pct, a6_bound_pct
    
    # Coverage is U2 pct_subscribers_covered
    coverage = util.get("U2", {}).get("pct_subscribers_covered", 0)
    
    # u1_pct_within_5pct is U1 headline_pct_within_5pct
    u1_pct_within_5pct = util.get("U1", {}).get("headline_pct_within_5pct", 0)
    
    # Suppressed = primary_suppressed_cells + secondary_suppressed_cells vs total raw cells?
    # Actually release_stats_aggregate has n_cells_input and n_cells_output
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
    releasable = False

    for attack in risk.get("attacks", []):
        if attack.get("id") == "A6":
            # For this pipeline, we just grab the first worst_case_grid point
            pts = attack.get("aggregate", {}).get("worst_case_grid", [])
            if pts:
                a6_acc = pts[0].get("attacker_accuracy_pct", 100.0)
                a6_bound = pts[0].get("theoretical_bound_pct", 100.0)
                
            crit_stat = attack.get("aggregate", {}).get("criterion_status", "fail")
            criteria["no_inference"] = crit_stat

        elif attack.get("id") == "A1":
            # A1 sets no_record_isolation
            crit_stat = attack.get("record", {}).get("criterion_status", "fail")
            criteria["no_record_isolation"] = crit_stat
            
        elif attack.get("id") == "A2":
            # A2 sets no_linkage
            crit_stat = attack.get("record", {}).get("criterion_status", "fail")
            criteria["no_linkage"] = crit_stat
            
    # Contextual releasability: all three must be pass or residual
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

# Save original yaml so we don't clobber it permanently
orig_yaml = load_yaml()

try:
    for c in configs:
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

finally:
    # restore
    save_yaml(orig_yaml)
    # run one last time to restore original state
    print("Restoring original data state...")
    run_pipeline()

with open("outputs/tradeoff_grid.json", "w") as f:
    json.dump(_round_floats(grid_results), f, indent=2)

print("tradeoff_grid.json generated!")
