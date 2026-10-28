"""Authenticated HTTP interface sharing the existing, tested workflow engine."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import threading
import time
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import Field

from . import cloud
from .agents import OpenRouterAgents, RecordingAgents, SampleAgents
from .models import Lead, StrictModel, WorkflowError, canonical, digest, now
from .storage import Store
from .workflow import Workflow

load_dotenv()
ROOT = Path(__file__).resolve().parents[1]
app = FastAPI(title="Wisnez", docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
_login_attempts: dict[str, list[float]] = {}
_login_lock = threading.Lock()
SESSION_SECONDS = 8 * 60 * 60


def session_token(timestamp: int) -> str:
    secret = os.getenv("WISNEZ_ACCESS_CODE", "")
    signature = hmac.new(secret.encode(), str(timestamp).encode(), hashlib.sha256).hexdigest()
    return f"{timestamp}.{signature}"


def authenticated(request: Request) -> bool:
    if len(os.getenv("WISNEZ_ACCESS_CODE", "")) < 16:
        return False
    value = request.cookies.get("wisnez_session", "")
    try:
        timestamp = int(value.split(".")[0])
        return 0 <= time.time() - timestamp <= SESSION_SECONDS and hmac.compare_digest(value, session_token(timestamp))
    except (ValueError, IndexError):
        return False


@app.middleware("http")
async def protect_requests(request: Request, call_next):
    path = request.url.path
    if path.startswith("/api/") and path not in {"/api/login", "/api/health"} and not authenticated(request):
        return JSONResponse({"detail": "Enter your workspace access code to continue."}, status_code=401)
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        origin = request.headers.get("origin")
        if origin and urlparse(origin).netloc != request.headers.get("host"):
            return JSONResponse({"detail": "Submit changes from the Wisnez workspace."}, status_code=403)
        if request.headers.get("x-wisnez-request") != "1" or not request.headers.get("content-type", "").startswith("application/json"):
            return JSONResponse({"detail": "Use the workspace controls to submit changes."}, status_code=403)
        try:
            oversized = int(request.headers.get("content-length", "0")) > 100_000
        except ValueError:
            oversized = True
        if oversized:
            return JSONResponse({"detail": "Request too large."}, status_code=413)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    if path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(WorkflowError)
async def workflow_error(request: Request, error: WorkflowError):
    code = 503 if isinstance(error, cloud.CloudUnavailable) else 409
    return JSONResponse({"detail": str(error)}, status_code=code)


class Login(StrictModel):
    code: str = Field(min_length=1, max_length=256)


@app.post("/api/login")
def login(data: Login, request: Request):
    # The high-entropy code is provisioned outside the UI; never stored in client JS.
    secret = os.getenv("WISNEZ_ACCESS_CODE", "")
    if len(secret) < 16:
        return JSONResponse({"detail": "Workspace access is not configured yet."}, status_code=503)
    ip = request.client.host if request.client else "unknown"
    with _login_lock:
        recent = [t for t in _login_attempts.get(ip, []) if t > time.time() - 60]
        if len(recent) >= 5:
            return JSONResponse({"detail": "Too many attempts. Wait a minute before trying again."}, status_code=429)
        _login_attempts[ip] = recent + [time.time()]
    if not hmac.compare_digest(data.code.strip(), secret):
        return JSONResponse({"detail": "The access code is incorrect."}, status_code=401)
    response = JSONResponse({"ok": True})
    response.set_cookie("wisnez_session", session_token(int(time.time())), max_age=SESSION_SECONDS,
                        httponly=True, secure=os.getenv("VERCEL") == "1" or request.url.scheme == "https", samesite="strict")
    return response


@app.post("/api/logout")
def logout():
    response = JSONResponse({"ok": True})
    response.delete_cookie("wisnez_session")
    return response


@app.get("/")
@app.get("/workspace")
def index():
    return FileResponse(ROOT / "static" / "wisnez.html", headers={"Cache-Control": "no-cache"})


@app.get("/api/health")
def health():
    return {"status": "ok", "product": "Wisnez"}


def requests_table(store):
    with store.connection() as con:
        con.execute("CREATE TABLE IF NOT EXISTS web_requests(id TEXT PRIMARY KEY, signature TEXT NOT NULL, state TEXT NOT NULL, result TEXT, created_at TEXT NOT NULL)")


def metrics(store):
    completed = store.rows("SELECT COUNT(*) AS n FROM actions WHERE state='completed'")[0]["n"]
    recovered = store.rows("SELECT COUNT(*) AS n FROM events WHERE kind='recovered'")[0]["n"]
    blocked = set()
    for run in store.runs():
        if run["plan"]:
            blocked.update(p["lead_id"] for p in json.loads(run["plan"])["proposals"] if p["blocked_reasons"])
    return {"completed": completed, "recovered": recovered, "blocked": len(blocked),
            "estimated_minutes": completed * store.policy().manual_minutes_per_lead,
            "minutes_per_lead": store.policy().manual_minutes_per_lead}


@app.get("/api/state")
def state(run: str | None = None):
    def read(store):
        flow = Workflow(store)
        runs = store.runs()
        active = store.run(run) if run else None
        if active:
            active = {**active, "plan": json.loads(active["plan"]) if active["plan"] else None,
                      "counts": flow.counts(run), "events": store.events(run), "actions": store.actions(run)}
        return {"leads": [x.model_dump() for x in store.leads()], "policy": store.policy().model_dump(),
                "runs": [{k: r[k] for k in ("id", "state", "mode", "version", "created_at")} for r in runs[:100]],
                "active": active, "impact": metrics(store),
                "outbox": store.rows("SELECT * FROM outbox ORDER BY created_at DESC LIMIT 100"),
                "approvals": store.rows("SELECT * FROM approvals ORDER BY id DESC LIMIT 100"),
                "live_available": bool(os.getenv("OPENROUTER_API_KEY", "").strip()),
                "model": os.getenv("OPENROUTER_MODEL", "").strip() or OpenRouterAgents.default_model,
                "persistent": bool(os.getenv("BLOB_READ_WRITE_TOKEN")), "daily_live_limit": 20}
    return cloud.operation(read)


class Mutation(StrictModel):
    operation_id: str = Field(min_length=10, max_length=80)


class Prepare(Mutation):
    request: str = Field(min_length=1, max_length=4000)
    lead_ids: list[str] = Field(min_length=1, max_length=5)
    mode: Literal["sample", "openrouter", "replay"] = "sample"


class Decision(Mutation):
    version: int = Field(ge=1)
    plan_hash: str
    operator: str = Field(min_length=1, max_length=120)
    confirmed: bool = False


class Edit(Mutation):
    version: int = Field(ge=1)
    changes: dict[str, dict[str, str]]


class Execute(Mutation):
    version: int = Field(ge=1)
    plan_hash: str
    failure: Literal["none", "temporary", "persistent", "outbox"] = "none"


class NewLead(Mutation):
    name: str = Field(min_length=1, max_length=120)
    company: str = Field(min_length=1, max_length=120)
    email: str = Field(max_length=240)
    enquiry: str = Field(min_length=1, max_length=5000)


class UpdateLead(NewLead):
    version: int = Field(ge=1)
    opted_out: bool = False
    identity_conflict: bool = False


def once(data: Mutation, callback, *, scope: str):
    signature = digest({"scope": scope, "data": data.model_dump(exclude={"operation_id"})})
    def apply(store):
        requests_table(store)
        rows = store.rows("SELECT * FROM web_requests WHERE id=?", (data.operation_id,))
        if rows:
            if rows[0]["signature"] != signature:
                raise WorkflowError("This request identifier belongs to different changes. Refresh and retry.")
            if rows[0]["state"] != "done":
                raise WorkflowError("This request is processing. Refresh saved workflows before submitting another.")
            return json.loads(rows[0]["result"])
        result = callback(store)
        with store.connection() as con:
            con.execute("INSERT INTO web_requests VALUES(?,?,?,?,?)", (data.operation_id, signature, "done", canonical(result), now()))
        return result
    return cloud.operation(apply, write=True)


@app.post("/api/prepare")
def prepare(data: Prepare):
    signature = ("live:" if data.mode == "openrouter" else "") + digest(data.model_dump(exclude={"operation_id"}))
    def reserve(store):
        requests_table(store)
        previous = store.rows("SELECT * FROM web_requests WHERE id=?", (data.operation_id,))
        if previous:
            if previous[0]["signature"] != signature:
                raise WorkflowError("Request identifier already used. Refresh and retry.")
            if previous[0]["state"] == "done":
                return json.loads(previous[0]["result"])
            raise WorkflowError("Preparation is processing. Refresh the workflow list to see saved results.")
        if len(set(data.lead_ids)) != len(data.lead_ids):
            raise WorkflowError("Select distinct leads, at most five.")
        for lead_id in data.lead_ids:
            store.lead(lead_id)
        if data.mode == "openrouter":
            OpenRouterAgents()
            count = store.rows("SELECT COUNT(*) AS n FROM web_requests WHERE signature LIKE 'live:%' AND created_at LIKE ?", (now()[:10] + "%",))[0]["n"]
            if count >= 20:
                raise WorkflowError("Today's 20 live demo preparations have been used. Sample mode and recorded replay remain available.")
        with store.connection() as con:
            con.execute("INSERT INTO web_requests VALUES(?,?,?,?,?)", (data.operation_id, signature, "started", None, now()))
        return None
    existing = cloud.operation(reserve, write=True)
    if existing:
        return existing
    def build(store):
        selected = [store.lead(i) for i in data.lead_ids]
        agents = SampleAgents() if data.mode == "sample" else RecordingAgents(
            store, data.request.strip(), selected, store.policy(), OpenRouterAgents() if data.mode == "openrouter" else None)
        run_id = Workflow(store).prepare(data.request, data.lead_ids, agents)
        result = {"run_id": run_id}
        with store.connection() as con:
            con.execute("UPDATE web_requests SET state='done',result=? WHERE id=?", (canonical(result), data.operation_id))
        return result
    return cloud.operation(build, write=True)


@app.post("/api/runs/{run_id}/edit")
def edit(run_id: str, data: Edit):
    return once(data, lambda s: (Workflow(s).edit(run_id, data.version, data.changes), {"run_id": run_id})[1], scope=run_id + ":edit")


@app.post("/api/runs/{run_id}/{decision}")
def decide(run_id: str, decision: Literal["approve", "reject"], data: Decision):
    def apply(store):
        flow = Workflow(store)
        if decision == "approve":
            if not data.confirmed:
                raise WorkflowError("Confirm that you reviewed the exact recipients, drafts, and CRM changes.")
            flow.approve(run_id, data.version, data.plan_hash, data.operator)
        else:
            flow.reject(run_id, data.version, data.operator)
        return {"run_id": run_id}
    return once(data, apply, scope=run_id + ":" + decision)


@app.post("/api/execute/{run_id}")
def execute(run_id: str, data: Execute):
    def apply(store):
        run = store.run(run_id)
        if run["version"] != data.version or run["plan_hash"] != data.plan_hash:
            raise WorkflowError("The preview changed. Review and approve the latest version.")
        return {"run_id": run_id, "counts": Workflow(store).execute(run_id, data.failure)}
    return once(data, apply, scope=run_id + ":execute")


@app.post("/api/leads")
def add_lead(data: NewLead):
    def apply(store):
        lead = Lead(id="L" + uuid4().hex[:7], **data.model_dump(exclude={"operation_id"}))
        store.add_lead(lead)
        return {"lead_id": lead.id}
    return once(data, apply, scope="add_lead")


@app.post("/api/leads/{lead_id}")
def update_lead(lead_id: str, data: UpdateLead):
    def apply(store):
        current = store.lead(lead_id)
        store.save_lead(Lead.model_validate({**current.model_dump(), **data.model_dump(exclude={"operation_id"})}))
        return {"lead_id": lead_id}
    return once(data, apply, scope=lead_id + ":update")
