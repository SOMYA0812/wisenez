import json
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from dealdesk.agents import OpenRouterAgents, RecordingAgents, SampleAgents
from dealdesk.models import DraftBatch, Lead, Policy, StalePlan, Task, WorkflowError
from dealdesk.storage import Store
from dealdesk.workflow import Workflow, qualify

BRIEF = "Review these leads, qualify them, update the CRM and prepare follow-ups. Ask before execution."


@pytest.fixture
def env(tmp_path):
    store = Store(tmp_path / "test.sqlite3")
    return store, Workflow(store)


def prepare(env, ids=None, agents=None, brief=BRIEF):
    store, flow = env
    run_id = flow.prepare(brief, ids or ["L001", "L002", "L003", "L004", "L005"], agents or SampleAgents())
    assert store.run(run_id)["state"] == "review", store.run(run_id)["error"]
    return run_id


def approve(env, run_id):
    store, flow = env
    run = store.run(run_id)
    flow.approve(run_id, run["version"], run["plan_hash"], "Demo owner")


def snapshot(store):
    return [x.model_dump() for x in store.leads()]


def test_prepare_proposes_without_business_writes(env):
    store, flow = env
    before = snapshot(store)
    run_id = prepare(env)
    assert snapshot(store) == before
    assert store.rows("SELECT * FROM outbox") == []
    plan = flow.prepared(run_id)
    assert [x.qualification for x in plan.proposals] == ["hot", "warm", "hot", "hot", "hot"]
    assert plan.proposals[2].blocked_reasons
    warm = plan.proposals[1]
    assert "budget" in warm.draft.body.lower()
    assert "timeline" in warm.draft.body.lower()
    assert len(store.actions(run_id)) == 4


def test_reject_never_changes_crm_or_outbox(env):
    store, flow = env
    before = snapshot(store)
    run_id = prepare(env)
    flow.reject(run_id, 1, "Demo owner")
    with pytest.raises(WorkflowError, match="approval"):
        flow.execute(run_id)
    assert snapshot(store) == before
    assert not store.rows("SELECT * FROM outbox")


def test_execution_without_approval_is_blocked(env):
    store, flow = env
    run_id = prepare(env)
    with pytest.raises(WorkflowError):
        flow.execute(run_id)
    assert not store.rows("SELECT * FROM outbox")


def test_approved_actions_match_preview_and_are_idempotent(env):
    store, flow = env
    run_id = prepare(env)
    plan = flow.prepared(run_id)
    approve(env, run_id)
    assert not store.rows("SELECT * FROM outbox")
    result = flow.execute(run_id)
    assert result["completed"] == 4
    for message in store.rows("SELECT * FROM outbox"):
        p = next(p for p in plan.proposals if p.lead_id == message["lead_id"])
        assert (message["recipient"], message["subject"], message["body"]) == (p.source.email, p.draft.subject, p.draft.body)
        assert store.lead(p.lead_id).summary == p.crm_after["summary"]
    completed_snapshot = snapshot(store)
    flow.execute(run_id)
    assert snapshot(store) == completed_snapshot
    assert len(store.rows("SELECT * FROM outbox")) == 4
    assert store.lead("L003").status == "New"


@pytest.mark.parametrize("field,value", [("body", "An owner-edited message."), ("subject", "A revised subject"), ("summary", "A revised CRM summary")])
def test_edit_invalidates_approval(env, field, value):
    store, flow = env
    run_id = prepare(env)
    approve(env, run_id)
    old_hash = store.run(run_id)["plan_hash"]
    flow.edit(run_id, 1, {"L001": {field: value}})
    run = store.run(run_id)
    assert run["version"] == 2
    assert run["state"] == "review"
    assert run["approved_hash"] is None
    assert run["plan_hash"] != old_hash
    with pytest.raises(WorkflowError):
        flow.execute(run_id)
    with pytest.raises(WorkflowError):
        flow.approve(run_id, 1, old_hash, "Owner")
    approve(env, run_id)
    flow.execute(run_id)
    message = store.rows("SELECT * FROM outbox WHERE lead_id='L001'")[0]
    if field in {"body", "subject"}:
        assert message[field] == value
    else:
        assert store.lead("L001").summary == value


def test_unchanged_edit_does_not_invalidate_approval(env):
    store, flow = env
    run_id = prepare(env)
    approve(env, run_id)
    p = flow.prepared(run_id).proposals[0]
    flow.edit(run_id, 1, {"L001": {"body": p.draft.body}})
    assert store.run(run_id)["state"] == "approved"
    assert store.run(run_id)["version"] == 1


@pytest.mark.parametrize("change", ["email", "enquiry", "opted_out", "identity_conflict"])
def test_customer_change_invalidates_execution(env, change):
    store, flow = env
    run_id = prepare(env, ["L001"])
    approve(env, run_id)
    lead = store.lead("L001")
    setattr(lead, change, {"email": "new@cedar.example", "enquiry": "Changed business requirements", "opted_out": True, "identity_conflict": True}[change])
    store.save_lead(lead)
    flow.execute(run_id)
    assert store.run(run_id)["state"] == "stale"
    assert not store.rows("SELECT * FROM outbox")
    assert store.lead("L001").status == "New"


def test_stale_before_approval_persists_invalid_state(env):
    store, flow = env
    run_id = prepare(env, ["L001"])
    lead = store.lead("L001")
    lead.opted_out = True
    store.save_lead(lead)
    with pytest.raises(StalePlan):
        approve(env, run_id)
    assert store.run(run_id)["state"] == "stale"
    assert not store.rows("SELECT * FROM approvals")


def test_changed_policy_invalidates_approval(env):
    store, flow = env
    run_id = prepare(env, ["L001"])
    approve(env, run_id)
    policy = store.policy()
    policy.minimum_budget = 50000
    policy.version += 1
    with store.transaction() as con:
        con.execute("UPDATE policy SET data=?", (policy.model_dump_json(),))
    flow.execute(run_id)
    assert store.run(run_id)["state"] == "stale"
    assert not store.rows("SELECT * FROM outbox")


def test_new_conflicting_contact_invalidates_approval(env):
    store, flow = env
    run_id = prepare(env, ["L001"])
    approve(env, run_id)
    store.add_lead(Lead(id="duplicate", name="Someone Else", company="Other Co", email=store.lead("L001").email, enquiry="A different person."))
    flow.execute(run_id)
    assert store.run(run_id)["state"] == "stale"
    assert not store.rows("SELECT * FROM outbox")


@pytest.mark.parametrize("failure", ["temporary", "outbox"])
def test_temporary_failures_recover_atomically(env, failure):
    store, flow = env
    run_id = prepare(env, ["L001", "L002"])
    approve(env, run_id)
    flow.execute(run_id, failure)
    assert store.run(run_id)["state"] == "completed"
    assert len(store.rows("SELECT * FROM outbox")) == 2
    assert store.lead("L001").version == 2  # rollback did not leak a previous write
    assert [a["attempts"] for a in store.actions(run_id)] == [2, 1]
    assert sum(e["kind"] == "recovered" for e in store.events(run_id)) == 1


def test_persistent_failure_and_resume_preserve_completed_actions(env):
    store, flow = env
    run_id = prepare(env, ["L001", "L002"])
    approve(env, run_id)
    counts = flow.execute(run_id, "persistent")
    assert (counts["completed"], counts["failed"]) == (1, 1)
    assert store.run(run_id)["state"] == "partial"
    assert store.lead("L001").status == "New"
    assert len(store.rows("SELECT * FROM outbox")) == 1
    completed_version = store.lead("L002").version
    assert any(e["kind"] == "error" for e in store.events(run_id))
    counts = flow.execute(run_id)
    assert counts["completed"] == 2
    assert store.lead("L002").version == completed_version
    assert len(store.rows("SELECT * FROM outbox")) == 2
    assert [a["attempts"] for a in store.actions(run_id)] == [3, 1]


def test_restart_recovers_approval_and_execution_state(env):
    store, flow = env
    run_id = prepare(env)
    approve(env, run_id)
    reopened_store = Store(store.path)
    reopened_flow = Workflow(reopened_store)
    assert reopened_store.run(run_id)["state"] == "approved"
    reopened_flow.execute(run_id)
    Workflow(Store(store.path)).execute(run_id)
    assert len(store.rows("SELECT * FROM outbox")) == 4


def test_simultaneous_execute_clicks_do_not_duplicate(env):
    store, flow = env
    run_id = prepare(env, ["L001", "L002"])
    approve(env, run_id)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: Workflow(Store(store.path)).execute(run_id), range(2)))
    assert all(r["completed"] == 2 for r in results)
    assert len(store.rows("SELECT * FROM outbox")) == 2
    assert store.lead("L001").version == 2


def test_untrusted_enquiry_cannot_bypass_approval(env):
    store, flow = env
    run_id = prepare(env, ["L009"])
    assert flow.prepared(run_id).proposals[0].qualification == "hot"
    assert store.run(run_id)["state"] == "review"
    with pytest.raises(WorkflowError):
        flow.execute(run_id)
    assert not store.rows("SELECT * FROM outbox")


def test_bad_addresses_and_conflicting_identity_are_blocked(env):
    store, flow = env
    run_id = prepare(env, ["L006", "L007"])
    assert all(p.blocked_reasons for p in flow.prepared(run_id).proposals)
    assert not store.actions(run_id)
    with pytest.raises(WorkflowError, match="no eligible"):
        approve(env, run_id)


def test_cold_leads_only_get_reviewed_crm_update(env):
    store, flow = env
    run_id = prepare(env, ["L008", "L010"])
    assert all(p.qualification == "cold" and p.draft is None for p in flow.prepared(run_id).proposals)
    approve(env, run_id)
    flow.execute(run_id)
    assert not store.rows("SELECT * FROM outbox")
    assert store.lead("L008").status == "Reviewed"


def test_readonly_request_has_no_business_actions(env):
    store, flow = env
    run_id = prepare(env, ["L001"], brief="Review only these leads")
    assert not store.actions(run_id)
    assert not flow.prepared(run_id).proposals[0].write_crm
    with pytest.raises(WorkflowError):
        approve(env, run_id)


def test_unsupported_request_returns_explanation(env):
    store, flow = env
    run_id = flow.prepare("Transfer money and delete the CRM", ["L001"], SampleAgents())
    assert store.run(run_id)["state"] == "unsupported"
    assert store.run(run_id)["error"]
    assert not store.actions(run_id)


def test_invalid_agent_task_graph_stops_safely(env):
    class BadPlanner(SampleAgents):
        def plan(self, *args):
            plan = super().plan(*args)
            plan.tasks = [Task(name="queue_email")]
            return plan
    store, flow = env
    run_id = flow.prepare(BRIEF, ["L001"], BadPlanner())
    assert store.run(run_id)["state"] == "preparation_failed"
    assert not store.actions(run_id)


def test_fabricated_evidence_stops_safely(env):
    class BadAnalyst(SampleAgents):
        def analyse(self, *args):
            batch = super().analyse(*args)
            batch.assessments[0].evidence[0].quote = "A quote that never existed"
            return batch
    store, flow = env
    run_id = flow.prepare(BRIEF, ["L001"], BadAnalyst())
    assert store.run(run_id)["state"] == "preparation_failed"
    assert not store.actions(run_id)


@pytest.mark.parametrize("target", ["plan", "action"])
def test_tampered_payload_never_executes(env, target):
    store, flow = env
    run_id = prepare(env, ["L001"])
    approve(env, run_id)
    with store.transaction() as con:
        if target == "plan":
            data = json.loads(store.run(run_id, con)["plan"])
            data["proposals"][0]["draft"]["body"] = "Tampered body"
            con.execute("UPDATE runs SET plan=? WHERE id=?", (json.dumps(data), run_id))
        else:
            data = json.loads(store.actions(run_id)[0]["payload"])
            data["draft"]["body"] = "Tampered body"
            con.execute("UPDATE actions SET payload=? WHERE run_id=?", (json.dumps(data), run_id))
    with pytest.raises(WorkflowError, match="integrity"):
        flow.execute(run_id)
    assert store.lead("L001").status == "New"
    assert not store.rows("SELECT * FROM outbox")


def test_real_recordings_require_matching_sources(env):
    class FakeLive(SampleAgents):
        mode = "live"  # Test double; never used by the app.
    store, flow = env
    leads = [store.lead("L001")]
    policy = store.policy()
    with pytest.raises(WorkflowError, match="No live recording"):
        RecordingAgents(store, BRIEF, leads, policy)
    live = RecordingAgents(store, BRIEF, leads, policy, FakeLive())
    run_id = prepare(env, ["L001"], live)
    replay = RecordingAgents(store, BRIEF, leads, policy)
    replay_id = prepare(env, ["L001"], replay)
    assert store.run(replay_id)["mode"] == "replay"
    assert flow.prepared(run_id) == flow.prepared(replay_id)
    leads[0].enquiry = "A changed enquiry"
    with pytest.raises(WorkflowError, match="No live recording"):
        RecordingAgents(store, BRIEF, leads, policy)


def test_new_enquiry_can_be_processed_without_fixture_lookup(env):
    store, flow = env
    store.add_lead(Lead(id="fresh", name="New Customer", company="Fresh Company", email="fresh@new.example",
                        enquiry="We need an ecommerce store. Budget INR 70000, timeline 12 days."))
    run_id = prepare(env, ["fresh"])
    p = flow.prepared(run_id).proposals[0]
    assert p.qualification == "hot"
    assert "Fresh Company" in p.draft.body


def test_openrouter_recording_keeps_its_provider_mode(env):
    class FakeOpenRouter(SampleAgents):
        mode = "openrouter"
    store, flow = env
    leads = [store.lead("L001")]
    agents = RecordingAgents(store, BRIEF, leads, store.policy(), FakeOpenRouter())
    run_id = prepare(env, ["L001"], agents)
    assert store.run(run_id)["mode"] == "openrouter"
    replay = RecordingAgents(store, BRIEF, leads, store.policy())
    replay_id = prepare(env, ["L001"], replay)
    assert flow.prepared(run_id) == flow.prepared(replay_id)


def test_openrouter_three_http_roles_prepare_without_executing(env, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-only-not-a-real-key")
    calls = []
    samples = SampleAgents()

    def post(url, **kwargs):
        body = kwargs["json"]
        calls.append(body["response_format"]["json_schema"]["name"])
        data = json.loads(body["messages"][1]["content"])
        leads = [Lead.model_validate(x) for x in data["leads"]]
        policy = Policy.model_validate(data["policy"])
        if calls[-1] == "TaskPlan":
            result = samples.plan(data["operator_request"], leads, policy)
        elif calls[-1] == "AnalysisBatch":
            result = samples.analyse(leads, policy)
        else:
            from dealdesk.models import AnalysisBatch
            result = samples.write(leads, AnalysisBatch.model_validate(data["analysis"]), policy)
        return httpx.Response(200, json={"choices": [{"message": {"content": result.model_dump_json()}, "finish_reason": "stop"}]})

    monkeypatch.setattr("dealdesk.agents.httpx.post", post)
    store, flow = env
    leads = [store.lead("L001")]
    agents = RecordingAgents(store, BRIEF, leads, store.policy(), OpenRouterAgents())
    run_id = prepare(env, ["L001"], agents)
    assert calls == ["TaskPlan", "AnalysisBatch", "DraftBatch"]
    assert store.run(run_id)["mode"] == "openrouter"
    assert store.lead("L001").status == "New"
    assert not store.rows("SELECT * FROM outbox")
    approve(env, run_id)
    flow.execute(run_id)
    assert len(store.rows("SELECT * FROM outbox")) == 1


def test_opt_out_detected_even_without_source_flag(env):
    store, flow = env
    lead = store.lead("L001")
    lead.enquiry += " Please unsubscribe me."
    store.save_lead(lead)
    run_id = prepare(env, ["L001"])
    assert flow.prepared(run_id).proposals[0].blocked_reasons
    assert not store.actions(run_id)


@pytest.mark.parametrize("ids", [[], ["L001"] * 2, [f"L00{i}" for i in range(1, 7)]])
def test_invalid_selection_rejected(env, ids):
    with pytest.raises(WorkflowError):
        env[1].prepare(BRIEF, ids, SampleAgents())
