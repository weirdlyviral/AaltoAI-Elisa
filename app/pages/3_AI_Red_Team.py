"""AI Red Team — automated re-identification testing. Owner: TBD."""
import sys
import json
from pathlib import Path

_APP_DIR = Path(__file__).resolve().parent.parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

import streamlit as st

from lib import components, data, theme
from lib.agent import run_agent

theme.setup_page("AI Red Team", icon="🛡️")
st.write(
    "Test the robustness of the current DP parameters by deploying an autonomous "
    "Red Team AI. It generates re-identification strategies based on defined "
    "attacker knowledge profiles, and executes them against the anonymised aggregate data."
)

st.info("The AI Attacker runs locally. Target evaluation indices are kept in memory only and never sent to the LLM Gateway.")

st.subheader("Attacker Knowledge Templates")
template_options = [
    "Knows target's province, radio type, and 15-minute window",
    "Knows target's specific eNB, radio type, and application category",
]
selected_template = st.selectbox("Select adversary profile", options=template_options)

if st.button("Launch Simulated Attack"):
    with st.spinner("Agent is generating and executing attack strategy..."):
        result = run_agent("red_team", selected_template)
    
    st.subheader("Attack Results")
    st.markdown(result.get("answer", "No answer provided."))
    
    strategy = result.get("strategy", [])
    if strategy:
        st.write("**Agent's Proposed Strategy:**")
        st.code(json.dumps(strategy, indent=2), language="json")
        
    success_rate = result.get("success_rate", 0.0)
    st.metric("Attacker Success Rate", f"{success_rate:.2f}%", help="Percentage of targets uniquely identified out of 200 samples.")
    
    # Compare with M3 handwritten
    risk_eval = data.load_risk_eval()
    if risk_eval:
        a6_acc = None
        for attack in risk_eval.get("attacks", []):
            if attack.get("id") == "A6":
                pts = attack.get("aggregate", {}).get("worst_case_grid", [])
                if pts:
                    a6_acc = pts[0].get("attacker_accuracy_pct")
                break
        if a6_acc is not None:
            st.metric("Baseline (M3 Handwritten A6)", f"{a6_acc:.2f}%")
