"""MCP tools page component listing forthcoming utilities."""

from __future__ import annotations

import streamlit as st


def render_mcp_tools_page() -> None:
    st.title("🛠️ MCP Tools")
    st.caption("Curated utilities to work with Multi Chain Programs (MCP) and Arc developer tooling.")

    st.markdown(
        """
        - **Registry Lookups**: Verify contract deployments and decode registry state.
        - **Credit Simulations**: Stress-test draw/repay flows before going live.
        - **Automation Hooks**: Wire Streamlit actions to backend MCP agents for scripted workflows.
        """
    )

    st.info(
        "Coming soon: trigger CreditLineManager draws, upload MCP scripts, and visualize multi-step executions "
        "directly from this panel."
    )

    st.markdown("### Helpful Commands")
    st.code("""streamlit run app.py
# Customize MCP integrations inside `streamlit/src/backend/`
""")

    st.markdown(
        """
        **Tip**: Pair this dashboard with background MCP services to orchestrate underwriting, settlement, and reporting.
        """
    )

