from __future__ import annotations

import html
import os
from pathlib import Path
from uuid import uuid4

import streamlit as st
from pydantic import ValidationError

from .agents import GeminiAgents, OpenRouterAgents, RecordingAgents, SampleAgents
from .models import Lead, WorkflowError
from .storage import Store
from .presentation import hero, landing, stylesheet
from .workflow import Workflow

DEFAULT_BRIEF = "Review these enquiries, identify promising leads, update their CRM records, and prepare personalised follow-ups. Ask me before execution."
MODES = {
    "Sample demo · no live AI": "sample",
    "Live OpenRouter": "openrouter",
    "Live Gemini": "live",
    "Recorded replay · saved AI": "replay",
}
MODE_NOTES = {
    "sample": "Sample demo — deterministic sample outputs, no live AI calls.",
    "live": "Live Gemini — three specialised roles, one human-controlled workflow.",
    "openrouter": "Live OpenRouter — three specialised roles, one human-controlled workflow.",
    "replay": "Recorded replay — saved live AI outputs, no new model calls. Exact source inputs must match.",
}
STATE_LABELS = {
    "preparing": "Preparing", "review": "Awaiting your review", "approved": "Approved · ready to execute",
    "executing": "Execution in progress", "completed": "Completed", "partial": "Needs attention",
    "rejected": "Rejected", "stale": "Preview expired", "preparation_failed": "Preparation stopped",
    "unsupported": "Request outside this MVP",
}


def notify(message: str) -> None:
    st.session_state["flash"] = message


def activate(run_id: str) -> None:
    st.query_params["run"] = run_id
    st.rerun()


def sidebar(store: Store, mode: str) -> str | None:
    with st.sidebar:
        st.markdown('<div class="brand">Wisnez</div><div class="brand-note">Your AI team. Your final say.</div>', unsafe_allow_html=True)
        st.divider()
        st.subheader("Run settings")
        if mode == "live":
            if os.getenv("GEMINI_API_KEY"):
                st.caption("Gemini key configured locally.")
            else:
                st.warning("Set GEMINI_API_KEY in .env to enable live AI.")
        elif mode == "openrouter":
            if os.getenv("OPENROUTER_API_KEY", "").strip():
                st.caption("OpenRouter key configured locally.")
            else:
                st.warning("Set OPENROUTER_API_KEY in .env to enable live AI.")
            st.caption("Model: " + (os.getenv("OPENROUTER_MODEL", "").strip() or OpenRouterAgents.default_model))
        st.write("")
        runs = store.runs()
        options = [""] + [r["id"] for r in runs]
        current = st.query_params.get("run", "")
        if current not in options:
            current = ""
        lookup = {r["id"]: r for r in runs}
        selected = st.selectbox("Active workflow", options, index=options.index(current),
                                format_func=lambda x: "New workflow" if not x else f"{x[:6]} · {STATE_LABELS.get(lookup[x]['state'], lookup[x]['state'])}",
                                key=f"active_{current}_{lookup[current]['state'] if current else 'new'}")
        if selected != current:
            if selected:
                st.query_params["run"] = selected
            else:
                st.query_params.clear()
            st.rerun()
        st.caption("Lead follow-up")
        st.divider()
        st.caption("Simulated tools. Real approval.")
        if os.getenv("WISNEZ_EPHEMERAL_STORAGE") == "1":
            st.info("Cloud demo storage resets when this instance restarts. Use fictional data.")
        st.caption("CRM changes persist locally. No email is delivered. Single-operator demo; names are an audit label, not authenticated identities.")
        with st.expander("Live AI setup"):
            st.markdown("**OpenRouter:** set `OPENROUTER_API_KEY` in your local `.env`, restart the app, and choose **Live OpenRouter**. Optionally set `OPENROUTER_MODEL` to a model supporting structured outputs. Requests may use your OpenRouter credits.")
            st.markdown("**Direct Gemini:** set `GEMINI_API_KEY` from [Google AI Studio](https://aistudio.google.com/apikey), restart, and choose **Live Gemini**. Start from `.env.example` if you do not have a local `.env` file.")
            st.caption("Never paste your key into the brief or a customer record. Recorded replay becomes available after a successful live preparation.")
    return selected or None


def business_memory(store: Store) -> None:
    policy = store.policy()
    st.subheader("Business memory")
    st.caption("Human-authored policies and customer history, shared across your team.")
    rows = [
        ("Services offered", "Website development, landing pages, ecommerce solutions."),
        ("Minimum budget", f"₹{policy.minimum_budget:,}"),
        ("Urgency", f"A known timeline within {policy.urgent_days} days qualifies for the urgent window."),
        ("Opt-out", "Respect unsubscribe requests. Block opted-out or conflicting customer records."),
        ("Approval", "All CRM changes and simulated emails need approval of the exact preview."),
    ]
    body = "".join(f"<tr><td>{html.escape(a)}</td><td>{html.escape(b)}</td></tr>" for a, b in rows)
    st.markdown(f'<table class="policy-table">{body}</table>', unsafe_allow_html=True)
    st.caption(f"{policy.business_name} · Policy version {policy.version} · Agents cannot rewrite these rules.")


def source_editor(store: Store, leads: list[Lead]) -> None:
    with st.expander("Inspect or update a customer record"):
        chosen = st.selectbox("Customer", [x.id for x in leads], format_func=lambda i: next(f"{x.name} · {x.company}" for x in leads if x.id == i))
        lead = next(x for x in leads if x.id == chosen)
        st.caption("These are manual source edits. They invalidate pending approvals involving this customer.")
        with st.form(f"source_{chosen}_{lead.version}"):
            email = st.text_input("Contact email", value=lead.email)
            enquiry = st.text_area("Original enquiry", value=lead.enquiry)
            opted_out = st.checkbox("Customer opted out", value=lead.opted_out)
            identity_conflict = st.checkbox("Identity needs resolution", value=lead.identity_conflict)
            st.caption("History: " + (" · ".join(lead.history) or "No previous interactions recorded."))
            if st.form_submit_button("Save customer record"):
                updated = Lead.model_validate({**lead.model_dump(), "email": email.strip(), "enquiry": enquiry.strip(),
                                               "opted_out": opted_out, "identity_conflict": identity_conflict})
                store.save_lead(updated)
                notify("Customer record updated. Existing previews will be rechecked before execution.")
                st.rerun()
    with st.expander("Add a fresh enquiry"):
        with st.form("new_lead"):
            c1, c2 = st.columns(2)
            name = c1.text_input("Customer name")
            company = c2.text_input("Company")
            email = st.text_input("Email address")
            enquiry = st.text_area("Customer enquiry", placeholder="What are they looking for? Include only information the customer provided.")
            if st.form_submit_button("Add enquiry"):
                lead = Lead(id="L" + uuid4().hex[:7], name=name.strip(), company=company.strip(), email=email.strip(), enquiry=enquiry.strip())
                store.add_lead(lead)
                notify("Enquiry added. Select it in the lead workspace to prepare a workflow.")
                st.rerun()


def workspace(store: Store, flow: Workflow, mode: str, active: str | None) -> None:
    leads = store.leads()
    with st.container(key="workspace_columns"):
        left, right = st.columns([1.65, 1], gap="small")
    with left, st.container(key="leads_panel"):
        st.header("Lead workspace")
        st.caption(f"{len(leads)} fictional enquiries · choose up to 5 per run")
        st.dataframe([{"Lead": x.name, "Company": x.company, "Status": x.status, "Contact": x.email,
                       } for x in leads], hide_index=True, height=205, row_height=32,
                     width="stretch")
        chosen = st.multiselect("Leads for this workflow", [x.id for x in leads], default=[x.id for x in leads[:5]],
                                max_selections=5, format_func=lambda i: next(f"{x.name} · {x.company}" for x in leads if x.id == i))
        source_editor(store, leads)
    with right:
        with st.container(key="brief_panel"):
            st.header("Give your team a brief")
            with st.form("prepare"):
                brief = st.text_area("Business request", value=DEFAULT_BRIEF, height=110, max_chars=4000, label_visibility="collapsed")
                submitted = st.form_submit_button("Prepare workflow", type="primary", width="stretch")
            st.caption(MODE_NOTES[mode])
        if submitted:
            if not chosen:
                st.error("Choose at least one lead.")
            else:
                selected = [next(x for x in leads if x.id == i) for i in chosen]
                if mode == "sample":
                    agents = SampleAgents()
                else:
                    provider = OpenRouterAgents() if mode == "openrouter" else GeminiAgents() if mode == "live" else None
                    agents = RecordingAgents(store, brief.strip(), selected, store.policy(), provider)
                with st.status("Your team is preparing the workflow…", expanded=True) as status:
                    run_id = flow.prepare(brief, chosen, agents, lambda role, msg: st.write(f"**{role}** · {msg}"))
                    result = store.run(run_id)
                    status.update(label="Preparation finished" if result["state"] == "review" else "Workflow needs attention", state="complete" if result["state"] == "review" else "error")
                notify("Workflow prepared. Open Review to inspect the exact proposed actions." if result["state"] == "review" else result["error"] or "Preparation stopped.")
                activate(run_id)
        if active:
            with st.expander("Agent activity"):
                for event in store.events(active):
                    st.caption(f"{event['stage']} · {event['message']}")
    with st.container(key="team_grid"):
        columns = st.columns(3, gap="small")
        roles = [("01", "Planner", "Turns your brief into a task plan."), ("02", "Lead analyst", "Extracts facts and evidence; Python checks the fit."), ("03", "Outreach writer", "Prepares a personal follow-up.")]
        for index, (column, (number, title, description)) in enumerate(zip(columns, roles)):
            with column, st.container(key=f"agent_{index}"):
                st.markdown(f'<div class="team-row"><div class="team-number">{number}</div><div><span class="team-title">{title}</span><div class="team-description">{description}</div></div></div>', unsafe_allow_html=True)
    with st.container(key="memory_panel"):
        business_memory(store)


def review(store: Store, flow: Workflow, run_id: str | None) -> None:
    st.header("Review before anything changes")
    if not run_id:
        st.info("Prepare a workflow in Workspace. Your proposed changes will appear here.")
        return
    run = store.run(run_id)
    st.caption(f"Workflow {run_id} · Version {run['version']} · {MODE_NOTES[run['mode']]}")
    st.write(f"**{STATE_LABELS[run['state']]}**")
    if run["error"]:
        st.warning(run["error"])
    plan = flow.prepared(run_id)
    if not plan:
        if run["state"] == "preparing":
            st.info("This preparation may have been interrupted. Return to Workspace and prepare a new workflow; no business changes have executed.")
        return
    st.write(plan.task_plan.explanation)
    st.caption(" → ".join(t.name.replace("_", " ").title() for t in plan.task_plan.tasks))
    actionable = [p for p in plan.proposals if p.actionable]
    blocked = [p for p in plan.proposals if p.blocked_reasons]
    m1, m2, m3 = st.columns(3)
    m1.metric("Eligible lead workflows", len(actionable))
    m2.metric("Blocked contacts", len(blocked))
    m3.metric("Needs clarification", sum(bool(p.missing) and not p.blocked_reasons for p in plan.proposals))
    action_states = {a["lead_id"]: a["state"] for a in store.actions(run_id)}
    edits_allowed = run["state"] in {"review", "approved"}
    changes = {}
    with st.form(f"drafts_{run_id}_{run['version']}"):
        for p in plan.proposals:
            state = "Blocked" if p.blocked_reasons else action_states.get(p.lead_id, "Read-only")
            with st.expander(f"{p.source.name} · {p.source.company} · {p.qualification.upper()} · {state}", expanded=p.lead_id == plan.proposals[0].lead_id):
                st.write(p.assessment.summary)
                st.caption("Rule: " + p.rule)
                st.caption("Source enquiry")
                st.text(p.source.enquiry)
                for e in p.assessment.evidence:
                    st.caption(f"{e.field.title()} evidence: “{e.quote}”")
                if p.missing:
                    st.info("Clarify: " + ", ".join(p.missing) + ".")
                if p.blocked_reasons:
                    for reason in p.blocked_reasons:
                        st.error(reason)
                    continue
                if p.write_crm:
                    st.write("**Proposed CRM changes**")
                    st.table([{"Field": field.title(), "Before": getattr(p.source, field) or "—", "After": value}
                              for field, value in p.crm_after.items()])
                    summary = st.text_area("CRM summary", value=p.crm_after["summary"], max_chars=800,
                                           key=f"summary_{run_id}_{run['version']}_{p.lead_id}", disabled=not edits_allowed)
                    changes[p.lead_id] = {"summary": summary}
                if p.draft:
                    st.write("**Email draft**" + (" · will be queued after approval" if p.queue_email else " · draft only"))
                    st.caption("To: " + p.source.email)
                    subject = st.text_input("Subject", value=p.draft.subject, max_chars=200,
                                            key=f"subject_{run_id}_{run['version']}_{p.lead_id}", disabled=not edits_allowed)
                    body = st.text_area("Message", value=p.draft.body, height=200, max_chars=5000,
                                        key=f"body_{run_id}_{run['version']}_{p.lead_id}", disabled=not edits_allowed)
                    changes.setdefault(p.lead_id, {}).update({"subject": subject, "body": body})
        if st.form_submit_button("Save preview edits", disabled=not edits_allowed):
            flow.edit(run_id, run["version"], changes)
            notify("Preview saved. Any changed content requires a new approval.")
            st.rerun()
    if blocked:
        st.subheader("Exception inbox")
        for p in blocked:
            st.warning(f"{p.source.name}: {' '.join(p.blocked_reasons)}")
    if not actionable:
        st.info("There are no eligible business changes. The analysis and any drafts are available for review.")
        return
    st.divider()
    if run["state"] in {"review", "approved"}:
        st.subheader("Your final say")
        st.caption(f"Preview fingerprint: {run['plan_hash'][:16]} · Version {run['version']}")
        if run["state"] == "approved":
            st.success(f"Approved by {run['approved_by']}. Open Execution to run these exact actions. Editing this preview invalidates approval.")
        with st.form(f"approval_{run_id}_{run['version']}"):
            operator = st.text_input("Approving person's name", max_chars=120)
            confirm = st.checkbox("I have saved my edits and reviewed the recipients, CRM changes, and complete drafts in this preview.")
            a, b = st.columns(2)
            approved = a.form_submit_button("Approve this version", type="primary", disabled=run["state"] != "review", width="stretch")
            rejected = b.form_submit_button("Reject workflow", width="stretch")
            if approved:
                if not confirm:
                    st.error("Review the preview and tick the confirmation before approving.")
                else:
                    flow.approve(run_id, run["version"], run["plan_hash"], operator)
                    notify("Approval recorded for this exact version. Open Execution when ready.")
                    st.rerun()
            if rejected:
                flow.reject(run_id, run["version"], operator)
                notify("Workflow rejected. No business changes executed.")
                st.rerun()


def execution(store: Store, flow: Workflow, run_id: str | None) -> None:
    st.header("Execution you can follow")
    st.caption("Simulated — no email delivered. Approved CRM changes and outbox entries persist in SQLite.")
    if not run_id:
        st.info("Prepare and approve a workflow first.")
        return
    run = store.run(run_id)
    counts = flow.counts(run_id)
    st.write(f"**{STATE_LABELS[run['state']]}** · {counts['completed']} of {counts['total']} lead workflows completed")
    if run["state"] in {"approved", "partial", "executing"}:
        with st.expander("Demonstrate failure recovery"):
            failure = st.selectbox("Failure injection", ["none", "temporary", "persistent", "outbox"],
                                   format_func=lambda x: {"none": "None · normal execution", "temporary": "CRM fails once · recover automatically",
                                                          "persistent": "CRM stays unavailable · stop after retry", "outbox": "Outbox fails once · roll back CRM, then recover"}[x])
            st.caption("Targets the first unfinished lead only. Each attempt has one automatic retry. Completed leads are never repeated.")
        if st.button("Execute approved actions" if run["state"] == "approved" else "Resume unfinished actions", type="primary"):
            with st.spinner("Executing the approved version…"):
                flow.execute(run_id, failure)
            notify("Execution finished. Inspect the results below.")
            st.rerun()
    elif run["state"] == "review":
        st.info("Waiting for a person's approval in Review. Business actions are locked.")
    elif run["state"] == "stale":
        st.warning("The approved source data changed. Return to Workspace and prepare a new workflow. Completed actions remain in the audit trail.")
    actions = store.actions(run_id)
    if actions:
        st.dataframe([{"Lead": a["lead_id"], "Result": a["state"].title(), "Attempts": a["attempts"], "Action ID": a["id"]} for a in actions], hide_index=True, width="stretch")
    st.subheader("Event trail")
    events = store.events(run_id)
    for event in events:
        text = f"**{event['stage']}** · {event['message']}"
        if event["lead_id"]:
            text += f" ({event['lead_id']})"
        if event["kind"] in {"error", "stale"}:
            st.error(text)
        elif event["kind"] == "recovered":
            st.success(text)
        else:
            st.write(text)
        st.caption(event["created_at"])
    st.subheader("Simulated email outbox")
    messages = store.rows("SELECT * FROM outbox WHERE run_id=? ORDER BY created_at,id", (run_id,))
    if not messages:
        st.caption("No simulated emails queued for this workflow.")
    for message in messages:
        with st.expander(f"{message['recipient']} · {message['subject']}"):
            st.text(message["body"])
            st.caption(f"Action {message['id']} · {message['created_at']} · Simulated — no email delivered.")


def impact(store: Store, flow: Workflow, run_id: str | None) -> None:
    st.header("Work completed, clearly measured")
    st.caption("Metrics for the selected workflow. These are operational counts, not revenue or measured time savings.")
    if not run_id:
        st.info("Select a workflow to see its results.")
        return
    plan = flow.prepared(run_id)
    counts = flow.counts(run_id)
    recovered = store.rows("SELECT COUNT(DISTINCT lead_id) AS n FROM events WHERE run_id=? AND kind='recovered'", (run_id,))[0]["n"]
    blocked = sum(bool(p.blocked_reasons) for p in plan.proposals) if plan else 0
    minutes = plan.policy.manual_minutes_per_lead if plan else 5
    cols = st.columns(4)
    for col, title, value in zip(cols, ["Completed workflows", "Blocked contacts", "Failures recovered", "Estimated effort automated"],
                                 [counts["completed"], blocked, recovered, f"{counts['completed'] * minutes} min"]):
        col.metric(title, value)
    st.info(f"Estimate assumption: {minutes} minutes of manual work per completed lead workflow. Failed and pending actions contribute zero minutes. This is not measured time saved.")
    st.subheader("Approval history")
    approvals = store.rows("SELECT version,operator,decision,created_at,plan_hash FROM approvals WHERE run_id=? ORDER BY id", (run_id,))
    if approvals:
        st.dataframe(approvals, hide_index=True, width="stretch")
    else:
        st.caption("No human decision recorded yet.")


def main() -> None:
    st.set_page_config(page_title="Wisnez · Your AI workforce", page_icon="🤝", layout="wide", initial_sidebar_state="collapsed")
    stylesheet()
    page = st.query_params.get("page", "dashboard" if st.query_params.get("run") else "landing")
    if page != "dashboard":
        landing()
        return
    root = Path(__file__).resolve().parent.parent
    db = Path(os.getenv("DEALDESK_DB", "data/dealdesk.sqlite3"))
    store = Store(db if db.is_absolute() else root / db)
    flow = Workflow(store)
    with st.container(key="dashboard_top"):
        brand_column, provider_column, home_column = st.columns([1, 1.3, .55], vertical_alignment="center")
        brand_column.markdown('<div class="dashboard-wordmark">Wisnez</div>', unsafe_allow_html=True)
        with provider_column:
            label = st.selectbox("Agent mode", list(MODES), label_visibility="collapsed", key="agent_mode")
        with home_column:
            if st.button("Home", key="go_home"):
                st.query_params["page"] = "landing"
                st.rerun()
    mode = MODES[label]
    active = sidebar(store, mode)
    plan = flow.prepared(active) if active else None
    counts = flow.counts(active) if active else {"completed": 0}
    hero(prepared=len(plan.proposals) if plan else 0, completed=counts["completed"],
         blocked=sum(bool(p.blocked_reasons) for p in plan.proposals) if plan else 0,
         status=STATE_LABELS[store.run(active)["state"]] if active else "Awaiting brief")
    flash_slot = st.empty()
    if flash := st.session_state.pop("flash", None):
        flash_slot.info(flash)
    tabs = st.tabs(["Workspace", "Review", "Execution", "Impact"], key="main_tabs")
    for name, tab, render in zip(["workspace", "review", "execution", "impact"], tabs,
                                [lambda: workspace(store, flow, mode, active), lambda: review(store, flow, active),
                                 lambda: execution(store, flow, active), lambda: impact(store, flow, active)]):
        with tab, st.container(key=f"view_{name}"):
            try:
                render()
            except WorkflowError as exc:
                st.error(str(exc))
            except ValidationError:
                st.error("Some fields are missing or invalid. Check the form and try again.")
