import sys
import json
import datetime
from pathlib import Path

_APP_DIR = Path(__file__).resolve().parent.parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

import pandas as pd
import altair as alt
import streamlit as st

from lib import components, data, theme

theme.setup_page("Trade-off Explorer", icon="🎛️")


grid, is_mock = data.load_tradeoff_grid()

if grid is None:
    components.pending("trade-off grid (outputs/tradeoff_grid.json)")
    st.stop()

if is_mock:
    st.warning(
        "⚠️ MOCK DATA — outputs/tradeoff_grid.json does not exist yet. "
        "The numbers below are fabricated placeholders from app/lib/mock_tradeoff_grid.json."
    )

ks = sorted({entry["config"]["k"] for entry in grid})
time_buckets = sorted({entry["config"]["time_bucket"] for entry in grid})
area_modes = sorted({entry["config"]["area_mode"] for entry in grid})

epsilons_raw = sorted({entry["config"]["epsilon"] for entry in grid if entry["config"]["epsilon"] is not None})
epsilons = epsilons_raw + ["None"]


if "slider_k" not in st.session_state: st.session_state.slider_k = ks[0]
if "slider_tb" not in st.session_state: st.session_state.slider_tb = time_buckets[0]
if "slider_am" not in st.session_state: st.session_state.slider_am = area_modes[0]
if "slider_eps" not in st.session_state: st.session_state.slider_eps = epsilons[0]

y_axis_options = {
    "A1 Row Uniqueness (Record)": "a1_uniqueness_pct",
    "A2 Trajectory Linkage (Record)": "a2_linkage_risk_pct",
    "A3 Homogeneity (Aggregate)": "a3_homogeneity_pct",
    "A5 Differencing Recovery (Aggregate)": "a5_differencing_pct",
    "A6 Inference Accuracy (Aggregate)": "a6_accuracy_pct"
}

metric_help_texts = {
    "U1": "Percentage of published cells where the median download speed is within 5% of the raw data. Target is >= 90%.",
    "A1 Row Uniqueness (Record)": "Probability of singling out a user in the record-level release based on unique rows.",
    "A2 Trajectory Linkage (Record)": "Attacker's success rate at linking users via trajectories in the record-level release.",
    "A3 Homogeneity (Aggregate)": "Risk of an attacker inferring sensitive attributes from highly homogeneous aggregate cells.",
    "A5 Differencing Recovery (Aggregate)": "Risk of recovering suppressed cells by differencing overlapping aggregate queries.",
    "A6 Inference Accuracy (Aggregate)": "Membership inference risk on the aggregate data. 50% is random guessing."
}
# A control rail down the left of the page, not a collapsible sidebar: these
# controls are the whole point of the page, so they stay visible beside the
# chart they drive.
control_rail, main_pane = st.columns([1, 3], gap="medium")

with control_rail:
    with st.container(border=True):
        st.markdown(
            "<div class='aas-control-kicker'>RELEASE CONFIGURATION</div>",
            unsafe_allow_html=True,
        )
        st.session_state.slider_k = st.select_slider("k", options=ks, value=st.session_state.slider_k)
        st.session_state.slider_tb = st.select_slider("time bucket (min)", options=time_buckets, value=st.session_state.slider_tb)
        st.session_state.slider_am = st.selectbox("area mode", options=area_modes, index=area_modes.index(st.session_state.slider_am) if st.session_state.slider_am in area_modes else 0)
        st.session_state.slider_eps = st.select_slider("epsilon", options=epsilons, value=st.session_state.slider_eps)

        st.markdown(
            "<div class='aas-control-kicker aas-control-kicker-spaced'>VIEW</div>",
            unsafe_allow_html=True,
        )
        selected_y_label = st.selectbox("Risk metric", options=list(y_axis_options.keys()))
selected_y_key = y_axis_options[selected_y_label]



match = next(
    (
        entry
        for entry in grid
        if entry["config"]["k"] == st.session_state.slider_k
        and entry["config"]["time_bucket"] == st.session_state.slider_tb
        and entry["config"]["area_mode"] == st.session_state.slider_am
        and (entry["config"]["epsilon"] == st.session_state.slider_eps or (entry["config"]["epsilon"] is None and st.session_state.slider_eps == "None"))
    ),
    None,
)

if match is None:
    components.pending("a grid entry for this exact combination")
    st.stop()

# Define thresholds for each metric to dynamically determine releasability
thresholds = {
    "a6_accuracy_pct": 60.0,
    "a1_uniqueness_pct": 10.0,
    "a2_linkage_risk_pct": 10.0,
    "a3_homogeneity_pct": 25.0,
    "a5_differencing_pct": 30.0
}
current_threshold = thresholds.get(selected_y_key, 100.0)

# Everything the controls drive renders in the right-hand pane.
with main_pane:
    # --- Overview Panels ---
    colA, colB, colC = st.columns([1, 1, 1.5])

    with colA:
        st.metric("Utility (U1)", f"{match['metrics'].get('u1_pct_within_5pct', 0):.1f}%", help=metric_help_texts["U1"])
    with colA:
        st.metric("Utility (U1)", f"{match['metrics'].get('u1_pct_within_5pct', 0):.1f}%", help=metric_help_texts["U1"])

    with colB:
        st.metric(selected_y_label.split(" (")[0], f"{match['metrics'].get(selected_y_key, 0):.1f}%", help=metric_help_texts[selected_y_label])
    with colB:
        st.metric(selected_y_label.split(" (")[0], f"{match['metrics'].get(selected_y_key, 0):.1f}%", help=metric_help_texts[selected_y_label])

    with colC:
        current_risk = match["metrics"].get(selected_y_key, 0)
        if current_risk <= current_threshold:
            st.success(f"✅ **PASSES**\n\nRisk is below {current_threshold}%.")
        else:
            st.error(f"🚫 **FAILS**\n\nExceeds {current_threshold}% threshold.")
    with colC:
        current_risk = match["metrics"].get(selected_y_key, 0)
        if current_risk <= current_threshold:
            st.success(f"✅ **PASSES**\n\nRisk is below {current_threshold}%.")
        else:
            st.error(f"🚫 **FAILS**\n\nExceeds {current_threshold}% threshold.")


    # --- Scatter Plot of All Configs ---
    st.subheader("Trade-off Spectrum")
    # --- Scatter Plot of All Configs ---
    st.subheader("Trade-off Spectrum")

    df_grid = []
    df_grid = []



    for i, entry in enumerate(grid):
        risk_val = entry["metrics"].get(selected_y_key, 0)
        is_releasable = risk_val <= current_threshold
    
        df_grid.append({
            "id": i,
            "k": entry["config"]["k"],
            "epsilon": entry["config"]["epsilon"],
            "time_bucket": entry["config"]["time_bucket"],
            "area_mode": entry["config"]["area_mode"],
            "utility": entry["metrics"].get("u1_pct_within_5pct", 0),
            "risk": risk_val,
            "releasable": "Yes" if is_releasable else "No",
            "is_selected": entry == match
        })
    df_grid = pd.DataFrame(df_grid)

    # One chart, not a layered pair: Streamlit refuses selections on multi-view
    # charts, so the "current config" highlight is an encoding on the same marks.
    selection = alt.selection_point(name='selector', fields=['id'])
    scatter = alt.Chart(df_grid).mark_point(filled=True).encode(
        x=alt.X('utility:Q', title='Utility (U1 headline %)', scale=alt.Scale(zero=False)),
        y=alt.Y('risk:Q', title=f'Risk ({selected_y_label} %)', scale=alt.Scale(zero=False)),
        color=alt.Color(
            'releasable:N',
            scale=alt.Scale(domain=['Yes', 'No'], range=[theme.PALETTE['pass'], theme.PALETTE['fail']]),
            legend=alt.Legend(title='Releasable'),
        ),
        size=alt.condition('datum.is_selected', alt.value(400), alt.value(110)),
        stroke=alt.condition('datum.is_selected', alt.value(theme.PALETTE['text']), alt.value('transparent')),
        strokeWidth=alt.condition('datum.is_selected', alt.value(2), alt.value(0)),
        tooltip=['k', 'epsilon', 'time_bucket', 'area_mode', 'utility', 'risk', 'releasable'],
        opacity=alt.condition(selection, alt.value(1), alt.value(0.35)),
    ).add_params(selection).properties(height=350)
    # One chart, not a layered pair: Streamlit refuses selections on multi-view
    # charts, so the "current config" highlight is an encoding on the same marks.
    selection = alt.selection_point(name='selector', fields=['id'])
    scatter = alt.Chart(df_grid).mark_point(filled=True).encode(
        x=alt.X('utility:Q', title='Utility (U1 headline %)', scale=alt.Scale(zero=False)),
        y=alt.Y('risk:Q', title=f'Risk ({selected_y_label} %)', scale=alt.Scale(zero=False)),
        color=alt.Color(
            'releasable:N',
            scale=alt.Scale(domain=['Yes', 'No'], range=[theme.PALETTE['pass'], theme.PALETTE['fail']]),
            legend=alt.Legend(title='Releasable'),
        ),
        size=alt.condition('datum.is_selected', alt.value(400), alt.value(110)),
        stroke=alt.condition('datum.is_selected', alt.value(theme.PALETTE['text']), alt.value('transparent')),
        strokeWidth=alt.condition('datum.is_selected', alt.value(2), alt.value(0)),
        tooltip=['k', 'epsilon', 'time_bucket', 'area_mode', 'utility', 'risk', 'releasable'],
        opacity=alt.condition(selection, alt.value(1), alt.value(0.35)),
    ).add_params(selection).properties(height=350)

    event = st.altair_chart(scatter, use_container_width=True, on_select="rerun")
    event = st.altair_chart(scatter, use_container_width=True, on_select="rerun")

    sel_list = []
    if hasattr(event, "selection") and hasattr(event.selection, "selector"):
        sel_list = event.selection.selector
    elif isinstance(event, dict) and "selection" in event and "selector" in event["selection"]:
        sel_list = event["selection"]["selector"]
    sel_list = []
    if hasattr(event, "selection") and hasattr(event.selection, "selector"):
        sel_list = event.selection.selector
    elif isinstance(event, dict) and "selection" in event and "selector" in event["selection"]:
        sel_list = event["selection"]["selector"]

    if sel_list and isinstance(sel_list, list) and len(sel_list) > 0:
        sel = sel_list[0]
        if "id" in sel:
            idx = sel["id"]
            clicked_config = df_grid.iloc[idx]
        
            c_eps = clicked_config["epsilon"]
            if pd.isna(c_eps) or c_eps is None:
                c_eps = "None"
            else:
                c_eps = float(c_eps)
            
            if st.session_state.slider_k != int(clicked_config["k"]) or \
               st.session_state.slider_tb != int(clicked_config["time_bucket"]) or \
               st.session_state.slider_am != clicked_config["area_mode"] or \
               st.session_state.slider_eps != c_eps:

               
                st.session_state.slider_k = int(clicked_config["k"])
                st.session_state.slider_tb = int(clicked_config["time_bucket"])
                st.session_state.slider_am = clicked_config["area_mode"]
                st.session_state.slider_eps = c_eps
                st.rerun()

    st.caption("The ringed, larger point is the active configuration. Click any point to jump to it.")
    st.caption("The ringed, larger point is the active configuration. Click any point to jump to it.")
