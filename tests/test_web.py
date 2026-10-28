import asyncio
from uuid import uuid4

import httpx
import pytest

from dealdesk.storage import Store
from dealdesk.web import app, _login_attempts

BRIEF = "Review these leads, qualify them, update the CRM and prepare follow-ups. Ask before execution."
CODE = "test-workspace-code-not-a-real-credential"
HEADERS = {"X-Wisnez-Request": "1"}


def payload(**kwargs):
    return {"operation_id": str(uuid4()), **kwargs}


@pytest.fixture
def env(tmp_path, monkeypatch):
    db = tmp_path / "web.sqlite3"
    monkeypatch.setenv("DEALDESK_DB", str(db))
    monkeypatch.setenv("BLOB_READ_WRITE_TOKEN", "")
    monkeypatch.setenv("VERCEL", "0")
    monkeypatch.setenv("WISNEZ_ACCESS_CODE", CODE)
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    _login_attempts.clear()
    return Store(db)


def scenario(callback):
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test", headers=HEADERS) as client:
            response = await client.post("/api/login", json={"code": CODE})
            assert response.status_code == 200
            return await callback(client)
    return asyncio.run(run())


async def prepare(client, ids=None):
    response = await client.post("/api/prepare", json=payload(request=BRIEF, lead_ids=ids or ["L001", "L002", "L003"], mode="sample"))
    assert response.status_code == 200, response.text
    return (await client.get("/api/state", params={"run": response.json()["run_id"]})).json()["active"]


async def approve(client, run):
    response = await client.post(f"/api/runs/{run['id']}/approve", json=payload(version=run["version"], plan_hash=run["plan_hash"], operator="Test owner", confirmed=True))
    assert response.status_code == 200, response.text


def test_every_business_api_requires_login(env):
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test", headers=HEADERS) as client:
            for method, path in [("GET", "/api/state"), ("POST", "/api/prepare"), ("POST", "/api/leads"), ("POST", "/api/runs/x/approve"), ("POST", "/api/execute/x")]:
                assert (await client.request(method, path, json={})).status_code == 401
            assert (await client.post("/api/login", json={"code": "wrong"})).status_code == 401
            for _ in range(4):
                await client.post("/api/login", json={"code": "wrong"})
            assert (await client.post("/api/login", json={"code": CODE})).status_code == 429
    asyncio.run(run())


def test_csrf_and_incomplete_approval_are_rejected(env):
    async def check(client):
        assert (await client.post("/api/leads", json={}, headers={"Origin": "https://attacker.example"})).status_code == 403
        run = await prepare(client)
        response = await client.post(f"/api/runs/{run['id']}/approve", json=payload(version=1, plan_hash=run["plan_hash"], operator="Test owner", confirmed=False))
        assert response.status_code == 409
        assert env.run(run["id"])["state"] == "review"
        assert not env.rows("SELECT * FROM outbox")
    scenario(check)


def test_full_http_edit_approve_recover_duplicate_and_refresh(env):
    async def check(client):
        before = [l.model_dump() for l in env.leads()]
        run = await prepare(client)
        assert before == [l.model_dump() for l in env.leads()]
        assert not env.rows("SELECT * FROM outbox")
        denied = await client.post('/api/execute/' + run['id'], json=payload(version=1, plan_hash=run['plan_hash']))
        assert denied.status_code == 409
        await approve(client, run)
        edit = await client.post(f"/api/runs/{run['id']}/edit", json=payload(version=1, changes={"L001": {"subject": "A considered next step"}}))
        assert edit.status_code == 200
        changed = (await client.get('/api/state', params={"run":run['id']})).json()['active']
        assert changed['state'] == 'review' and changed['version'] == 2 and changed['approved_hash'] is None
        denied = await client.post('/api/execute/' + run['id'], json=payload(version=1, plan_hash=run['plan_hash']))
        assert denied.status_code == 409
        await approve(client, changed)
        execution = payload(version=2, plan_hash=changed['plan_hash'], failure='temporary')
        first = await client.post('/api/execute/' + run['id'], json=execution)
        assert first.status_code == 200, first.text
        assert (await client.post('/api/execute/' + run['id'], json=execution)).json() == first.json()
        saved = (await client.get('/api/state', params={"run":run['id']})).json()
        assert saved['active']['state'] == 'completed'
        assert saved['active']['counts']['completed'] == 2
        assert len(saved['outbox']) == 2
        assert saved['impact']['recovered'] == 1
        assert saved['impact']['estimated_minutes'] == 10
        assert saved['outbox'][0]['subject'] == 'A considered next step' or saved['outbox'][1]['subject'] == 'A considered next step'
        assert len((await client.get('/api/state')).json()['outbox']) == 2
    scenario(check)


def test_source_optout_blocks_stale_execution(env):
    async def check(client):
        run = await prepare(client, ['L001'])
        await approve(client, run)
        lead = env.lead('L001')
        update = payload(**{k:getattr(lead,k) for k in ['name','company','email','enquiry','version']}, opted_out=True)
        assert (await client.post('/api/leads/L001', json=update)).status_code == 200
        assert (await client.post('/api/execute/' + run['id'], json=payload(version=1,plan_hash=run['plan_hash']))).status_code == 200
        assert env.run(run['id'])['state'] == 'stale'
        assert not env.rows('SELECT * FROM outbox')
    scenario(check)


def test_reject_and_prepare_request_retry_never_duplicate(env):
    async def check(client):
        request = payload(request=BRIEF,lead_ids=['L002'],mode='sample')
        first = await client.post('/api/prepare',json=request)
        second = await client.post('/api/prepare',json=request)
        assert first.json() == second.json()
        assert len(env.runs()) == 1
        run = env.runs()[0]
        response = await client.post(f"/api/runs/{run['id']}/reject",json=payload(version=1,plan_hash=run['plan_hash'],operator='Test owner'))
        assert response.status_code == 200
        assert env.run(run['id'])['state'] == 'rejected'
        assert env.lead('L002').status == 'New'
        assert not env.rows('SELECT * FROM outbox')
    scenario(check)


def test_logout_revokes_browser_session(env):
    async def check(client):
        assert (await client.get('/api/state')).status_code == 200
        assert (await client.post('/api/logout',json={})).status_code == 200
        assert (await client.get('/api/state')).status_code == 401
    scenario(check)
