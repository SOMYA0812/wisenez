from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Lead(StrictModel):
    id: str
    name: str = Field(min_length=1, max_length=120)
    company: str = Field(min_length=1, max_length=120)
    email: str = Field(max_length=240)
    enquiry: str = Field(min_length=1, max_length=5000)
    opted_out: bool = False
    identity_conflict: bool = False
    history: list[str] = Field(default_factory=list)
    status: str = "New"
    qualification: str | None = None
    summary: str = ""
    version: int = 1


class Policy(StrictModel):
    version: int = 1
    business_name: str = "Fieldwork Web Studio"
    services: list[str] = Field(default_factory=lambda: ["website", "landing page", "ecommerce"])
    minimum_budget: int = 10000
    urgent_days: int = 30
    manual_minutes_per_lead: int = 5
    instructions: str = (
        "Respect opt-outs. Do not invent facts, prices, discounts, delivery promises, "
        "or previous conversations. Ask about missing budget and timeline. "
        "All CRM changes and simulated emails require human approval."
    )


TaskName = Literal["review", "qualify", "draft_followups", "update_crm", "queue_email"]


class Task(StrictModel):
    name: TaskName
    depends_on: list[TaskName] = Field(default_factory=list)


class TaskPlan(StrictModel):
    supported: bool
    explanation: str = Field(max_length=1000)
    lead_ids: list[str] = Field(max_length=5)
    tasks: list[Task] = Field(max_length=5)


class Evidence(StrictModel):
    field: Literal["service", "budget", "timeline", "interest"]
    quote: str = Field(min_length=1, max_length=500)


class Assessment(StrictModel):
    lead_id: str
    service: Literal["website", "landing page", "ecommerce", "other", "unknown"]
    budget_inr: int | None = Field(default=None, ge=0)
    timeline_days: int | None = Field(default=None, ge=0)
    interested: bool
    summary: str = Field(min_length=1, max_length=800)
    evidence: list[Evidence] = Field(max_length=8)


class AnalysisBatch(StrictModel):
    assessments: list[Assessment] = Field(max_length=5)


class Draft(StrictModel):
    lead_id: str
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=5000)


class DraftBatch(StrictModel):
    drafts: list[Draft] = Field(max_length=5)


class Proposal(StrictModel):
    lead_id: str
    qualification: Literal["hot", "warm", "cold"]
    assessment: Assessment
    source: Lead
    rule: str
    missing: list[str]
    blocked_reasons: list[str]
    crm_after: dict[str, str]
    draft: Draft | None = None
    write_crm: bool = False
    queue_email: bool = False

    @property
    def actionable(self) -> bool:
        return not self.blocked_reasons and (self.write_crm or self.queue_email)


class PreparedPlan(StrictModel):
    task_plan: TaskPlan
    policy: Policy
    proposals: list[Proposal]


class WorkflowError(Exception):
    """A user-facing workflow error; contains no provider credentials."""


class StalePlan(WorkflowError):
    pass
