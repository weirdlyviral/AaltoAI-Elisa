"""AI Analyst — chatting with the aggregate data. Owner: TBD."""
import sys
import json
from pathlib import Path

_APP_DIR = Path(__file__).resolve().parent.parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

import streamlit as st

from lib import components, data, theme
from lib.agent import run_agent, RefusedQuery

theme.setup_page("AI Analyst", icon="🤖")
st.write(
    "Ask natural language questions about the aggregate network performance. "
    "The AI agent writes and executes secure pandas queries against the anonymised "
    "aggregate release to answer you. It cannot access raw data and is blocked "
    "from seeing any cell with fewer than 10 subscribers."
)

if "messages" not in st.session_state:
    st.session_state.messages = []

# Display chat history
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if "chart" in msg and msg["chart"]:
            st.vega_lite_chart(msg["chart"], use_container_width=True)
        if "tool_calls" in msg and msg["tool_calls"]:
            with st.expander("View Agent Queries"):
                for call in msg["tool_calls"]:
                    st.code(json.dumps(call, indent=2), language="json")

# Chat input
if prompt := st.chat_input("Ask a question (e.g. 'Where is 5G video experience worst?')"):
    # Show user message
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # Call AI agent
    with st.chat_message("assistant"):
        with st.spinner("Analyzing aggregate data..."):
            result = run_agent("analyst", prompt, history=st.session_state.messages)
            
        answer = result.get("answer", "No answer provided.")
        tool_calls = result.get("tool_calls", [])
        
        st.markdown(answer)
        chart = result.get("chart")
        if chart:
            st.vega_lite_chart(chart, use_container_width=True)
        if tool_calls:
            with st.expander("View Agent Queries"):
                for call in tool_calls:
                    st.code(json.dumps(call, indent=2), language="json")
                    
        st.session_state.messages.append({
            "role": "assistant", 
            "content": answer,
            "tool_calls": tool_calls,
            "chart": chart
        })
