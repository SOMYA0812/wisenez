from __future__ import annotations

import json
import re
import sqlite3
from typing import Literal
from uuid import uuid4

from .agents import Agents, Progress, RecordingAgents
from .models import (
    AnalysisBatch, Assessment, DraftBatch, Lead, Policy, PreparedPlan, Proposal,
    StalePlan, TaskPlan, WorkflowError, canonical, digest, now,
)
from .storage import Store

DEPENDENCIES = {
    "review": [], "qualify": ["review"], "draft_followups": ["qualify"],
    "update_crm": ["qualify"], "queue_email": ["draft_followups", "update_crm"],
}
EMAIL = re.compile(r"[^\s@<>]+@[^\s@<>]+\.[A-Za-z]{2,}\Z")
OPT_OUT = re.compile(r"\b(do not contact|don't contact|unsubscribe|stop emailing|remove me|opt[ -]?out)\b", re.I)


def qualify(assessment: Assessment, policy: Policy) -> tuple[str, str, list[str]]:
    missing = []
    if assessment.service == "unknown":
        missing.append("service")
    if assessment.budget_inr is None:
        missing.append("budget")
    if assessment.timeline_days is None:
        missing.append("timeline")
    if not assessment.interested or assessment.service == "other":
        return "cold", "No expressed interest or the requested service is outside our offering.", missing
    if assessment.budget_inr is not None and assessment.budget_inr < policy.minimum_budget:
        return "cold", f"Stated budget is below the INR {policy.minimum_budget:,} minimum.", missing
    if (assessment.service in policy.services and assessment.budget_inr is not None
            and assessment.timeline_days is not None and assessment.timeline_days <= policy.urgent_days):
        return "hot", f"Offered service; budget ≥ INR {policy.minimum_budget:,}; timeline ≤ {policy.urgent_days} days.", missing
    return "warm", "Interested lead; details are incomplete or the timeline is beyond the urgent window.", missing


def contact_blocks(lead: Lead, all_leads: list[Lead]) -> list[str]:
    reasons = []
    if lead.opted_out or OPT_OUT.search(lead.enquiry):
        reasons.append("Customer has opted out. No business actions are permitted for this lead.")
    if not EMAIL.fullmatch(lead.email):
        reasons.append("Missing or invalid email address. Correct the source record and prepare a new workflow.")
    duplicate = any(x.id != lead.id and x.email.casefold() == lead.email.casefold()
                    and (x.name.casefold(), x.company.casefold()) != (lead.name.casefold(), lead.company.casefold())
                    for x in all_leads if x.email)
    if lead.identity_conflict or duplicate:
        reasons.append("Conflicting customer identity. Resolve the source record before preparing another workflow.")
    return reasons


def validate_tasks(plan: TaskPlan, available: list[Lead]) -> None:
    if not plan.supported:
        if plan.tasks or plan.lead_ids:
            raise WorkflowError("Planner returned tasks for an unsupported request.")
        return
    ids = [x.id for x in available]
    if not plan.lead_ids or len(set(plan.lead_ids)) != len(plan.lead_ids) or not set(plan.lead_ids) <= set(ids):
        raise WorkflowError("Planner selected invalid or duplicate leads.")
    seen = set()
    for task in plan.tasks:
        if task.name in seen or set(task.depends_on) != set(DEPENDENCIES[task.name]):
            raise WorkflowError("Planner returned an invalid task dependency graph.")
        if not set(task.depends_on) <= seen:
            raise WorkflowError("A task is missing a prerequisite or is out of order.")
        seen.add(task.name)
    if not {"review", "qualify"} <= seen:
        raise WorkflowError("The workflow requires lead review and qualification.")


def validate_analysis(batch: AnalysisBatch, leads: list[Lead]) -> None:
    expected = {x.id: x for x in leads}
    returned = [x.lead_id for x in batch.assessments]
    if len(returned) != len(set(returned)) or set(returned) != set(expected):
        raise WorkflowError("The analyst must return exactly one assessment for each selected lead.")
    for assessment in batch.assessments:
        lead = expected[assessment.lead_id]
        if any(e.quote not in lead.enquiry for e in assessment.evidence):
            raise WorkflowError("An analyst evidence quote did not match its source enquiry.")
        fields = {e.field for e in assessment.evidence}
        required = {"interest"}
        if assessment.service != "unknown":
            required.add("service")
        if assessment.budget_inr is not None:
            required.add("budget")
        if assessment.timeline_days is not None:
            required.add("timeline")
        if not required <= fields:
            raise WorkflowError("The analyst provided a fact without source evidence.")


def validate_drafts(batch: DraftBatch, leads: list[Lead]) -> None:
    ids = [x.lead_id for x in batch.drafts]
    if len(ids) != len(set(ids)) or set(ids) != {x.id for x in leads}:
        raise WorkflowError("The writer must return exactly one draft for each eligible lead.")
    for draft in batch.drafts:
        if "\r" in draft.subject or "\n" in draft.subject:
            raise WorkflowError("Email subjects must be a single line.")


def plan_hash(plan: PreparedPlan, version: int) -> str:
    return digest({"version": version, "plan": plan.model_dump()})


class Workflow:
    def __init__(self, store: Store):
        self.store = store

    def prepare(self, request: str, lead_ids: list[str], agents: Agents,
                progress: Progress | None = None) -> str:
        request = request.strip()
        if not request or len(request) > 4000:
            raise WorkflowError("Enter a brief between 1 and 4,000 characters.")
        if not 1 <= len(lead_ids) <= 5 or len(set(lead_ids)) != len(lead_ids):
            raise WorkflowError("Select between one and five distinct leads.")
        with self.store.transaction() as con:
            leads = [self.store.lead(i, con) for i in lead_ids]
            policy = self.store.policy(con)
        run_id = uuid4().hex[:12]
        with self.store.transaction() as con:
            con.execute("INSERT INTO runs(id,request,mode,state,created_at) VALUES(?,?,?,?,?)",
                        (run_id, request, agents.mode, "preparing", now()))

        def report(stage: str, message: str) -> None:
            self.store.event(run_id, stage, "info", message)
            if progress:
                progress(stage, message)

        try:
            report("Planner", "Building a task plan from the owner's brief.")
            task_plan = agents.plan(request, leads, policy)
            validate_tasks(task_plan, leads)
            if not task_plan.supported:
                with self.store.transaction() as con:
                    con.execute("UPDATE runs SET state='unsupported',error=? WHERE id=?", (task_plan.explanation, run_id))
                report("Supervisor", task_plan.explanation)
                return run_id
            selected = [next(x for x in leads if x.id == i) for i in task_plan.lead_ids]
            report("Lead analyst", "Extracting facts and evidence; Python applies the qualification rules.")
            analysis = agents.analyse(selected, policy)
            validate_analysis(analysis, selected)
            assessments = {x.lead_id: x for x in analysis.assessments}
            names = {x.name for x in task_plan.tasks}
            proposals = []
            for lead in selected:
                a = assessments[lead.id]
                qualification, rule, missing = qualify(a, policy)
                proposals.append(Proposal(
                    lead_id=lead.id, qualification=qualification, assessment=a, source=lead,
                    rule=rule, missing=missing, blocked_reasons=contact_blocks(lead, self.store.leads()),
                    crm_after={"qualification": qualification, "summary": a.summary,
                               "status": "Follow-up queued" if qualification != "cold" and "queue_email" in names else "Reviewed"},
                    write_crm="update_crm" in names,
                    queue_email=qualification in {"hot", "warm"} and "queue_email" in names,
                ))
            draft_leads = [p.source for p in proposals if not p.blocked_reasons and p.qualification != "cold"]
            if "draft_followups" in names and draft_leads:
                report("Outreach writer", "Writing personalised drafts from shared policy and customer history.")
                filtered = AnalysisBatch(assessments=[assessments[x.id] for x in draft_leads])
                drafts = agents.write(draft_leads, filtered, policy)
                validate_drafts(drafts, draft_leads)
                by_id = {x.lead_id: x for x in drafts.drafts}
                for p in proposals:
                    p.draft = by_id.get(p.lead_id)
                    if p.draft:
                        # Keep missing-field questions explicit even when a model omits them.
                        if "budget" in p.missing and "budget" not in p.draft.body.casefold():
                            p.draft.body += "\n\nWhat budget range do you have in mind?"
                        if "timeline" in p.missing and not re.search(r"timeline|when|timeframe|time frame", p.draft.body, re.I):
                            p.draft.body += "\n\nWhat timeline are you working towards?"
            if any(p.queue_email and not p.blocked_reasons and p.draft is None for p in proposals):
                raise WorkflowError("An email action is missing its required draft.")
            prepared = PreparedPlan(task_plan=task_plan, policy=policy, proposals=proposals)
            with self.store.transaction() as con:
                con.execute("UPDATE runs SET state='review',plan=?,plan_hash=? WHERE id=?",
                            (prepared.model_dump_json(), plan_hash(prepared, 1), run_id))
                self._replace_actions(con, run_id, prepared)
                self.store.event(run_id, "Supervisor", "ready", "Preview ready. No CRM changes or emails have executed.", con=con)
            if isinstance(agents, RecordingAgents):
                agents.save()
            if progress:
                progress("Supervisor", "Preview ready. Open Review to inspect and approve.")
        except Exception as exc:
            message = str(exc) if isinstance(exc, WorkflowError) else "Preparation failed safely. Check the input and retry; no business actions executed."
            with self.store.transaction() as con:
                con.execute("UPDATE runs SET state='preparation_failed',error=? WHERE id=?", (message, run_id))
                self.store.event(run_id, "Supervisor", "error", message, con=con)
        return run_id

    def _replace_actions(self, con: sqlite3.Connection, run_id: str, plan: PreparedPlan) -> None:
        con.execute("DELETE FROM actions WHERE run_id=?", (run_id,))
        for p in plan.proposals:
            if p.actionable:
                con.execute("INSERT INTO actions(id,run_id,lead_id,payload) VALUES(?,?,?,?)",
                            (f"{run_id}:{p.lead_id}", run_id, p.lead_id, p.model_dump_json()))

    def prepared(self, run_id: str) -> PreparedPlan | None:
        run = self.store.run(run_id)
        return PreparedPlan.model_validate_json(run["plan"]) if run["plan"] else None

    def _verified(self, run: dict) -> PreparedPlan:
        if not run["plan"]:
            raise WorkflowError("This workflow has no prepared plan.")
        plan = PreparedPlan.model_validate_json(run["plan"])
        if plan_hash(plan, run["version"]) != run["plan_hash"]:
            raise WorkflowError("Plan integrity check failed. Prepare a new workflow.")
        return plan

    def _fresh(self, con: sqlite3.Connection, plan: PreparedPlan, proposals: list[Proposal]) -> None:
        if self.store.policy(con) != plan.policy:
            raise StalePlan("Company policies changed. Prepare a new workflow and review the new preview.")
        all_leads = [Lead.model_validate_json(x[0]) for x in con.execute("SELECT data FROM leads")]
        for p in proposals:
            if self.store.lead(p.lead_id, con) != p.source:
                raise StalePlan("A customer record changed after preparation. Prepare a new workflow before executing pending actions.")
            if contact_blocks(p.source, all_leads):
                raise StalePlan("A customer is no longer eligible. Prepare a new workflow.")

    def approve(self, run_id: str, version: int, expected_hash: str, operator: str) -> None:
        operator = operator.strip()
        if not operator or len(operator) > 120:
            raise WorkflowError("Enter the approving person's name (1–120 characters).")
        stale = None
        with self.store.transaction() as con:
            run = self.store.run(run_id, con)
            if run["state"] != "review" or run["version"] != version or run["plan_hash"] != expected_hash:
                raise WorkflowError("The preview changed or is no longer awaiting approval. Reload and review it again.")
            plan = self._verified(run)
            actionable = [p for p in plan.proposals if p.actionable]
            if not actionable:
                raise WorkflowError("There are no eligible business changes to approve.")
            try:
                self._fresh(con, plan, actionable)
            except StalePlan as exc:
                stale = str(exc)
                self._mark_stale(con, run_id, stale)
            if not stale:
                con.execute("INSERT INTO approvals(run_id,version,plan_hash,operator,decision,created_at) VALUES(?,?,?,?,?,?)",
                            (run_id, version, expected_hash, operator, "approved", now()))
                con.execute("UPDATE runs SET state='approved',approved_hash=?,approved_by=? WHERE id=?", (expected_hash, operator, run_id))
                self.store.event(run_id, "Human approval", "approved", f"{operator} approved version {version}. Execution has not started.", con=con)
        if stale:
            raise StalePlan(stale)

    def edit(self, run_id: str, version: int, changes: dict[str, dict[str, str]]) -> None:
        with self.store.transaction() as con:
            run = self.store.run(run_id, con)
            if run["state"] not in {"review", "approved"} or run["version"] != version:
                raise WorkflowError("This preview cannot be edited. Reload or prepare another workflow.")
            if con.execute("SELECT COUNT(*) FROM actions WHERE run_id=? AND state='completed'", (run_id,)).fetchone()[0]:
                raise WorkflowError("Completed business actions cannot be rewritten. Prepare a new workflow for additional work.")
            plan = self._verified(run)
            known = {p.lead_id: p for p in plan.proposals}
            for lead_id, fields in changes.items():
                if lead_id not in known or not set(fields) <= {"subject", "body", "summary"}:
                    raise WorkflowError("Only the displayed draft and CRM summary can be edited.")
                proposal = known[lead_id]
                for field, value in fields.items():
                    value = value.strip()
                    if not value:
                        raise WorkflowError("Draft fields and CRM summaries cannot be empty.")
                    if field == "summary":
                        if len(value) > 800:
                            raise WorkflowError("CRM summaries must be at most 800 characters.")
                        proposal.crm_after["summary"] = value
                    elif proposal.draft:
                        data = proposal.draft.model_dump()
                        data[field] = value
                        proposal.draft = type(proposal.draft).model_validate(data)
                        validate_drafts(DraftBatch(drafts=[proposal.draft]), [proposal.source])
                    else:
                        raise WorkflowError("This lead has no editable email draft.")
            if plan_hash(plan, version) == run["plan_hash"]:
                return
            next_version = version + 1
            con.execute("UPDATE runs SET plan=?,version=?,plan_hash=?,approved_hash=NULL,approved_by=NULL,state='review' WHERE id=?",
                        (plan.model_dump_json(), next_version, plan_hash(plan, next_version), run_id))
            self._replace_actions(con, run_id, plan)
            self.store.event(run_id, "Human review", "edited", f"Preview updated to version {next_version}. Any previous approval is invalid.", con=con)

    def reject(self, run_id: str, version: int, operator: str) -> None:
        if not operator.strip():
            raise WorkflowError("Enter your name before recording a rejection.")
        with self.store.transaction() as con:
            run = self.store.run(run_id, con)
            if run["state"] not in {"review", "approved"} or run["version"] != version:
                raise WorkflowError("This version is no longer available for rejection.")
            self._verified(run)
            con.execute("UPDATE runs SET state='rejected',approved_hash=NULL,approved_by=NULL WHERE id=?", (run_id,))
            con.execute("INSERT INTO approvals(run_id,version,plan_hash,operator,decision,created_at) VALUES(?,?,?,?,?,?)",
                        (run_id, version, run["plan_hash"], operator.strip()[:120], "rejected", now()))
            self.store.event(run_id, "Human approval", "rejected", "Owner rejected this version. No business changes executed.", con=con)

    def _mark_stale(self, con: sqlite3.Connection, run_id: str, message: str) -> None:
        con.execute("UPDATE runs SET state='stale',approved_hash=NULL,approved_by=NULL,error=? WHERE id=?", (message, run_id))
        self.store.event(run_id, "Supervisor", "stale", message, con=con)

    def execute(self, run_id: str, failure: Literal["none", "temporary", "persistent", "outbox"] = "none") -> dict[str, int]:
        if failure not in {"none", "temporary", "persistent", "outbox"}:
            raise WorkflowError("Unknown failure mode.")
        actions = self.store.actions(run_id)
        target = next((a["id"] for a in actions if a["state"] != "completed"), None)
        for action in actions:
            if action["state"] == "completed":
                continue
            for attempt in range(2):
                transient = False
                with self.store.transaction() as con:
                    run = self.store.run(run_id, con)
                    if run["state"] == "completed":
                        break
                    if run["state"] not in {"approved", "partial", "executing"}:
                        raise WorkflowError("Execution requires current human approval. Open Review first.")
                    plan = self._verified(run)
                    if run["approved_hash"] != run["plan_hash"]:
                        raise WorkflowError("Approval does not match the current preview.")
                    current = con.execute("SELECT * FROM actions WHERE id=?", (action["id"],)).fetchone()
                    if current["state"] == "completed":
                        break
                    proposal = next(p for p in plan.proposals if p.lead_id == action["lead_id"])
                    if not proposal.actionable or Proposal.model_validate_json(current["payload"]) != proposal:
                        raise WorkflowError("Action integrity check failed. Prepare a new workflow.")
                    try:
                        self._fresh(con, plan, [proposal])
                    except StalePlan as exc:
                        self._mark_stale(con, run_id, str(exc))
                        return self.counts(run_id, con)
                    con.execute("UPDATE runs SET state='executing' WHERE id=?", (run_id,))
                    con.execute("UPDATE actions SET attempts=attempts+1 WHERE id=?", (action["id"],))
                    fail_target = action["id"] == target
                    # Fail before CRM commit, or after CRM write to prove outbox rollback.
                    transient = fail_target and (failure == "persistent" or (failure == "temporary" and attempt == 0)
                                                 or (failure == "outbox" and attempt == 0))
                    con.execute("SAVEPOINT business_action")
                    if not (transient and failure != "outbox"):
                        self._apply_business_action(con, run_id, action["id"], proposal, fail_outbox=transient)
                    if transient:
                        con.execute("ROLLBACK TO business_action")
                        con.execute("RELEASE business_action")
                        con.execute("UPDATE actions SET state='failed' WHERE id=?", (action["id"],))
                        msg = ("Simulated outbox failure; CRM changes rolled back." if failure == "outbox"
                               else "Simulated CRM unavailable; no business changes committed.")
                        self.store.event(run_id, "Executor", "retry" if attempt == 0 else "error",
                                         msg + (" Retrying once." if attempt == 0 else " Retry limit reached; human attention required."),
                                         proposal.lead_id, con)
                    else:
                        con.execute("RELEASE business_action")
                        con.execute("UPDATE actions SET state='completed' WHERE id=?", (action["id"],))
                        previous_failure = current["attempts"] > 0
                        kind = "recovered" if attempt > 0 or previous_failure else "completed"
                        self.store.event(run_id, "Executor", kind,
                                         "Approved CRM changes committed" + (" and simulated email queued." if proposal.queue_email else "."),
                                         proposal.lead_id, con)
                if not transient:
                    break
        with self.store.transaction() as con:
            run = self.store.run(run_id, con)
            if run["state"] in {"approved", "executing", "partial"}:
                counts = self.counts(run_id, con)
                state = "completed" if counts["completed"] == counts["total"] else "partial"
                con.execute("UPDATE runs SET state=? WHERE id=?", (state, run_id))
            return self.counts(run_id, con)

    def _apply_business_action(self, con: sqlite3.Connection, run_id: str, action_id: str,
                               p: Proposal, fail_outbox: bool = False) -> None:
        if p.write_crm:
            lead = p.source.model_copy(deep=True)
            lead.status = p.crm_after["status"]
            lead.qualification = p.crm_after["qualification"]
            lead.summary = p.crm_after["summary"]
            lead.version += 1
            if p.queue_email:
                lead.history.append(f"Simulated follow-up queued by approved workflow {run_id}; no email delivered.")
            con.execute("UPDATE leads SET data=? WHERE id=?", (lead.model_dump_json(), lead.id))
        if p.queue_email and not fail_outbox:
            con.execute("INSERT INTO outbox VALUES(?,?,?,?,?,?,?)",
                        (action_id, run_id, p.lead_id, p.source.email, p.draft.subject, p.draft.body, now()))

    def counts(self, run_id: str, con: sqlite3.Connection | None = None) -> dict[str, int]:
        if con is None:
            with self.store.connection() as connection:
                return self.counts(run_id, connection)
        rows = con.execute("SELECT state,COUNT(*) AS n FROM actions WHERE run_id=? GROUP BY state", (run_id,)).fetchall()
        result = {"completed": 0, "failed": 0, "pending": 0, "total": 0}
        for row in rows:
            result[row["state"]] = row["n"]
            result["total"] += row["n"]
        return result
