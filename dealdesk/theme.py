"""The reference-inspired visual system. Workflow logic stays in ui/workflow."""
import streamlit as st


def stylesheet() -> None:
    st.html("""<style>
    :root {
      --ink:#241c16; --muted:#786b5e; --line:#e5dccf;
      --canvas:#f5ede1; --sand:#e6d3b3; --brown:#38291d;
    }
    .stApp { background:var(--canvas); color:var(--ink); }
    .stApp, .stApp input, .stApp textarea, .stApp button,
    .stApp h1, .stApp h2, .stApp h3 { font-family:Arial,Helvetica,sans-serif!important; }
    .block-container { max-width:1600px; padding:.8rem 3.75rem 3rem; }
    [data-testid="stHeader"] { height:0!important; background:transparent!important; }
    [data-testid="stToolbar"] { pointer-events:none; }
    [data-testid="stAppDeployButton"], [data-testid="stMainMenu"] { display:none; }
    [data-testid="stExpandSidebarButton"] { pointer-events:auto; position:fixed; left:10px; top:13px; background:#eadcc7; border-radius:999px; }
    [data-testid="stSidebar"] { background:#f0e4d3; border-right:1px solid var(--line); }
    [data-testid="stSidebarContent"] { padding-top:0!important; }
    [data-testid="stSidebarHeader"] { height:2rem!important; min-height:2rem!important; }
    .brand { font-size:1.9rem; color:var(--ink); font-weight:400; letter-spacing:-.07rem; }
    .brand-note { color:var(--muted); margin:.25rem 0 1.4rem; font-size:.85rem; }
    h2 { font-size:1.5rem!important; line-height:1.2!important; letter-spacing:-.045rem; font-weight:500!important; padding:.1rem 0 .4rem!important; }
    h3 { font-size:1.08rem!important; letter-spacing:-.025rem; font-weight:500!important; }
    p, label { line-height:1.5; }
    [data-testid="stCaptionContainer"] { color:var(--muted); }
    hr { border-color:var(--line)!important; }
    .st-key-hero {
      background:#463d36 url('/app/static/dealdesk-architecture.png') center 52% / cover no-repeat;
      border-radius:22px; padding:1.1rem 2.1rem .9rem; overflow:hidden;
      min-height:314px; color:white; margin-bottom:-.5rem;
    }
    .hero-top { display:flex; justify-content:space-between; align-items:center; gap:1rem; color:white; }
    .hero-wordmark { font-size:1.85rem; font-weight:400; letter-spacing:-.055rem; line-height:1.2; }
    .hero-promise { font-size:.8rem; color:#fff7ee; text-align:right; }
    .st-key-hero_bottom { margin-top:5.75rem; }
    .st-key-hero h1 {
      font-size:3.1rem!important; line-height:1.04!important; font-weight:400!important;
      letter-spacing:-.12rem; color:#fff!important; padding:0 0 .35rem!important; max-width:420px;
    }
    .st-key-hero [data-testid="stHeadingWithActionElements"] a { display:none; }
    .hero-subtitle { color:#fff; font-size:.99rem; max-width:520px; line-height:1.5; margin:.15rem 0 0; }
    .hero-note {
      background:rgba(77,65,57,.74); border:1px solid rgba(255,255,255,.45);
      border-radius:16px; padding:1rem 1.15rem; backdrop-filter:blur(12px);
      color:white; max-width:265px; margin-left:auto; font-size:1.28rem; font-weight:400; line-height:1.45;
    }
    .hero-note span { display:block; }
    .stTabs [role="tablist"] {
      gap:0; width:min(570px,100%); margin:.15rem auto .2rem; padding:4px;
      background:#e9d9c2; border:0!important; border-radius:999px;
    }
    .stTabs [role="tab"] {
      flex:1; justify-content:center; border-radius:999px; padding:.5rem 1rem;
      height:2.2rem; font-size:.87rem; color:#4e4033; white-space:nowrap; border:0!important; box-shadow:none!important;
    }
    .stTabs [aria-selected="true"] { background:#fff; color:var(--ink)!important; }
    .stTabs [data-baseweb="tab-highlight"], .stTabs [data-baseweb="tab-border"] { display:none; }
    .stTabs [role="tablist"]::after, .stTabs .react-aria-SelectionIndicator { display:none; }
    .stTabs [role="tabpanel"] { padding-top:0; }
    .st-key-leads_panel, .st-key-brief_panel, .st-key-team_panel, .st-key-memory_panel,
    .st-key-view_review, .st-key-view_execution, .st-key-view_impact {
      background:#fffdfa; border-radius:12px; padding:1.25rem 1.45rem;
    }
    .st-key-brief_panel { background:#eee3d3; }
    .st-key-leads_panel, .st-key-brief_panel, .st-key-memory_panel { gap:.55rem!important; }
    .st-key-team_panel { gap:0!important; padding:.3rem 1.1rem; }
    .st-key-brief_panel h2 { font-size:1.12rem!important; letter-spacing:-.025rem; }
    .st-key-brief_panel [data-testid="stCaptionContainer"] { text-align:center; font-size:.73rem; }
    [data-testid="stForm"] { border:0; padding:0; }
    [data-testid="stTextArea"] textarea, [data-testid="stTextInput"] input {
      border-radius:8px; background:#fff; color:var(--ink); font-size:.88rem;
    }
    [data-baseweb="select"] > div { border-radius:8px; }
    [data-testid="stExpander"] { border-color:var(--line); border-radius:8px; background:#fffdfa; }
    [data-testid="stExpander"] summary { font-size:.83rem; }
    [data-testid="stDataFrame"], [data-testid="stTable"] { border-radius:8px; border-color:var(--line); }
    [data-testid="stBaseButton-primary"], button[kind="primary"] { background:var(--brown); color:white; border-color:var(--brown); border-radius:9px; }
    [data-testid="stBaseButton-primary"]:hover, button[kind="primary"]:hover { background:#5a4933; border-color:#5a4933; color:white; }
    [data-testid="stBaseButton-secondary"] { border-color:var(--line); border-radius:9px; }
    .team-row { display:flex; gap:1rem; align-items:center; padding:.85rem 0; border-bottom:1px solid var(--line); }
    .team-row:last-child { border-bottom:0; }
    .team-number { width:2.3rem; height:2.3rem; display:flex; align-items:center; justify-content:center;
      background:#f2e7d7; border-radius:50%; font-size:.82rem; flex-shrink:0; }
    .team-title { font-size:.9rem; font-weight:500; color:var(--ink); }
    .team-description { color:var(--muted); font-size:.79rem; margin-top:.15rem; line-height:1.4; }
    .policy-table { border-collapse:collapse; width:100%; font-size:.84rem; }
    .policy-table td { padding:.65rem .85rem; border-bottom:1px solid var(--line); vertical-align:top; }
    .policy-table td:first-child { font-weight:500; width:25%; }
    .policy-table tr:first-child td { border-top:1px solid var(--line); }
    .st-key-memory_panel { margin-top:.6rem; }
    .st-key-memory_panel h3 { font-size:1.15rem!important; }
    [data-testid="stMetricValue"] { color:#5a4933; font-weight:400; }
    [data-testid="stAlert"] { border-radius:8px; }
    button:focus-visible, input:focus-visible, textarea:focus-visible { outline:2px solid #895e3b!important; outline-offset:2px; }
    @media(min-width:900px) {
      .st-key-workspace_columns > [data-testid="stHorizontalBlock"] { gap:10px; }
    }
    @media(max-width:900px) {
      .block-container { padding:.8rem 1.5rem 2rem; }
      [data-testid="stExpandSidebarButton"] { left:2px; top:2px; }
      .st-key-hero { padding:1.4rem 1.5rem; }
      .st-key-hero h1 { font-size:2.65rem!important; max-width:440px; }
      .hero-note { font-size:1.05rem; }
    }
    @media(max-width:640px) {
      .block-container { padding:2.6rem .8rem 1.5rem; }
      .st-key-hero { border-radius:16px; padding:1.2rem; min-height:395px; background-position:58% center; }
      .hero-wordmark { font-size:1.65rem; }
      .hero-promise { max-width:115px; font-size:.68rem; }
      .st-key-hero_bottom { margin-top:6rem; }
      .st-key-hero h1 { font-size:2.5rem!important; line-height:1.08!important; letter-spacing:-.09rem; max-width:100%; }
      .hero-subtitle { font-size:.85rem; }
      .st-key-hero_bottom [data-testid="stColumn"]:last-child { display:none; }
      .stTabs [role="tablist"] { width:100%; margin-bottom:.6rem; }
      .stTabs [role="tab"] { padding:.4rem .55rem; font-size:.78rem; }
      .st-key-leads_panel, .st-key-brief_panel, .st-key-team_panel, .st-key-memory_panel,
      .st-key-view_review, .st-key-view_execution, .st-key-view_impact { padding:1.1rem .9rem; }
      h2 { font-size:1.35rem!important; }
      .policy-table td { padding:.6rem .3rem; }
      .policy-table td:first-child { width:34%; }
    }
    @media(prefers-reduced-motion:reduce) { *,*::before,*::after { scroll-behavior:auto!important; transition:none!important; animation:none!important; } }
    </style>""")


def hero() -> None:
    with st.container(key="hero"):
        st.markdown('<div class="hero-top"><span class="hero-wordmark">Wisnez</span><span class="hero-promise">Simulated tools. Real approval.</span></div>', unsafe_allow_html=True)
        with st.container(key="hero_bottom"):
            left, right = st.columns([3, 1], gap="large", vertical_alignment="bottom")
            with left:
                st.title("Your next move, ready for review.")
                st.markdown('<p class="hero-subtitle">Turn new enquiries into thoughtful follow-ups.<br>Approve every change before it happens.</p>', unsafe_allow_html=True)
            with right:
                st.markdown('<div class="hero-note"><span>3 specialised agents.</span><span>Your final say.</span></div>', unsafe_allow_html=True)
