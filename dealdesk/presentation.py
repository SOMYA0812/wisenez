"""Landing and dashboard visual surfaces; workflow execution is separate."""
import html
from pathlib import Path

import streamlit as st


def stylesheet() -> None:
    css = (Path(__file__).resolve().parent.parent / "static" / "dealdesk.css").read_text(encoding="utf-8")
    st.html("<style>" + css + "</style>")


def landing() -> None:
    with st.container(key="landing_page"):
        st.markdown('<header class="landing-brandline"><span>Wisnez</span><span>Human judgement, first.</span></header>', unsafe_allow_html=True)
        st.markdown('''<section class="landing-copy" aria-label="Wisnez introduction">
          <h1><span class="landing-first">B<em>uilt</em> for the</span><span class="landing-word"><em>builders</em></span></h1>
          <p>An AI workforce for your business. Every action, approved by you.</p>
          </section>''', unsafe_allow_html=True)
        with st.container(key="landing_actions"):
            if st.button("Enter workspace", type="primary", key="enter_workspace", width="stretch"):
                st.query_params["page"] = "dashboard"
                st.rerun()
            st.markdown('<p class="landing-action-note">Plan. Review. Execute.</p>', unsafe_allow_html=True)
        st.markdown('<footer class="landing-footer"><span>Wisnez</span><span>Your AI team. Your final say.</span><span>Simulated tools. Real approval.</span></footer>', unsafe_allow_html=True)


def hero(prepared: int, completed: int, blocked: int, status: str) -> None:
    with st.container(key="dashboard_hero"):
        left, right = st.columns([1.7, 1], gap="large", vertical_alignment="bottom")
        with left:
            st.title("YOUR AI WORKFORCE.")
            st.markdown('<section class="human-control"><h2>Human control</h2><p>Every business change needs your approval.</p></section>', unsafe_allow_html=True)
        with right:
            st.markdown(f'''<section class="overview-glass" aria-label="Workflow overview">
              <h2>Workflow overview</h2><dl>
              <div><dd>{prepared}</dd><dt>Prepared</dt></div>
              <div><dd>{completed}</dd><dt>Completed</dt></div>
              <div><dd>{blocked}</dd><dt>Blocked</dt></div>
              </dl></section>
              <div class="hero-mini-grid">
                <section><h3>Approval status</h3><p>{html.escape(status)}</p></section>
                <section><h3>Business memory</h3><p>Shared policies &amp; history</p></section>
              </div>''', unsafe_allow_html=True)
