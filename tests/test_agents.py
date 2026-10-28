from types import SimpleNamespace

import httpx
import pytest

from dealdesk.agents import GeminiAgents, OpenRouterAgents
from dealdesk.models import AnalysisBatch, TaskPlan, WorkflowError


def agent_with_responses(responses):
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        result = responses[len(calls) - 1]
        if isinstance(result, Exception):
            raise result
        return SimpleNamespace(output_text=result)

    agent = GeminiAgents.__new__(GeminiAgents)
    agent.model = "configured-test-model"
    agent.client = SimpleNamespace(interactions=SimpleNamespace(create=create))
    return agent, calls


def test_model_schema_correction_is_bounded():
    good = TaskPlan(supported=False, explanation="Unsupported request", lead_ids=[], tasks=[]).model_dump_json()
    agent, calls = agent_with_responses(["not json", good])
    result = agent._call("Planner", "Instructions", {}, TaskPlan)
    assert not result.supported
    assert len(calls) == 2
    assert calls[0]["model"] == "configured-test-model"
    assert calls[0]["response_format"]["schema"] == TaskPlan.model_json_schema()
    assert "did not validate" in calls[1]["input"]


def test_invalid_output_stops_after_one_correction_attempt():
    agent, calls = agent_with_responses(["bad", "still bad"])
    with pytest.raises(WorkflowError, match="twice"):
        agent._call("Planner", "Instructions", {}, TaskPlan)
    assert len(calls) == 2


def test_provider_error_does_not_expose_exception_or_key():
    agent, calls = agent_with_responses([RuntimeError("https://provider.example?key=SECRET-NEVER-DISPLAY")])
    with pytest.raises(WorkflowError) as error:
        agent._call("Planner", "Instructions", {}, TaskPlan)
    assert "SECRET" not in str(error.value)
    assert "provider.example" not in str(error.value)
    assert len(calls) == 1


def test_missing_gemini_key_fails_explicitly(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(WorkflowError, match="GEMINI_API_KEY"):
        GeminiAgents()


def router_with_responses(monkeypatch, responses):
    calls = []
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-only-not-a-real-key")
    monkeypatch.setenv("OPENROUTER_MODEL", "test/model")

    def post(url, **kwargs):
        calls.append((url, kwargs))
        response = responses[len(calls) - 1]
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr("dealdesk.agents.httpx.post", post)
    return OpenRouterAgents(), calls


def router_response(content, finish="stop"):
    return httpx.Response(200, json={"choices": [{"message": {"content": content}, "finish_reason": finish}]})


def test_openrouter_structured_request_and_credential_header(monkeypatch):
    good = TaskPlan(supported=False, explanation="Outside scope", lead_ids=[], tasks=[]).model_dump_json()
    agent, calls = router_with_responses(monkeypatch, [router_response(good)])
    result = agent._call("Planner", "Instructions", {"operator_request": "test"}, TaskPlan)
    assert not result.supported
    assert agent.mode == "openrouter"
    url, kwargs = calls[0]
    assert url == "https://openrouter.ai/api/v1/chat/completions"
    assert kwargs["headers"]["Authorization"] == "Bearer test-only-not-a-real-key"
    body = kwargs["json"]
    assert body["model"] == "test/model"
    assert body["provider"]["require_parameters"] is True
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["strict"] is True
    assert "untrusted data" in body["messages"][0]["content"]
    assert "test-only-not-a-real-key" not in str(body)
    assert kwargs["timeout"] == 45


def test_openrouter_missing_key_fails_explicitly(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(WorkflowError, match="OPENROUTER_API_KEY"):
        OpenRouterAgents()


def test_openrouter_invalid_output_has_one_correction_attempt(monkeypatch):
    agent, calls = router_with_responses(monkeypatch, [router_response("bad"), router_response("still bad")])
    with pytest.raises(WorkflowError, match="twice"):
        agent._call("Planner", "Instructions", {}, TaskPlan)
    assert len(calls) == 2
    assert "did not validate" in calls[1][1]["json"]["messages"][-1]["content"]


def test_openrouter_correction_can_succeed(monkeypatch):
    good = TaskPlan(supported=False, explanation="Outside scope", lead_ids=[], tasks=[]).model_dump_json()
    agent, calls = router_with_responses(monkeypatch, [router_response("bad"), router_response(good)])
    assert not agent._call("Planner", "Instructions", {}, TaskPlan).supported
    assert len(calls) == 2


@pytest.mark.parametrize("status,explanation", [(400, "schema"), (401, "API key"), (402, "credits"), (403, "denied"),
                                                (404, "model"), (429, "rate limit"), (503, "provider")])
def test_openrouter_http_errors_are_safe_and_actionable(monkeypatch, status, explanation):
    agent, calls = router_with_responses(monkeypatch, [httpx.Response(status, json={"error": {"message": "SECRET-DO-NOT-DISPLAY"}})])
    with pytest.raises(WorkflowError) as error:
        agent._call("Planner", "Instructions", {}, TaskPlan)
    assert explanation in str(error.value)
    assert "SECRET" not in str(error.value)
    assert len(calls) == 1


def test_openrouter_200_error_payload_does_not_trigger_correction(monkeypatch):
    agent, calls = router_with_responses(monkeypatch, [httpx.Response(200, json={"error": {"code": 429, "message": "SECRET"}})])
    with pytest.raises(WorkflowError, match="rate limit"):
        agent._call("Planner", "Instructions", {}, TaskPlan)
    assert len(calls) == 1


@pytest.mark.parametrize("response", [httpx.Response(200, text="not JSON"), httpx.Response(200, json=[]), httpx.Response(200, json={"choices": []})])
def test_openrouter_malformed_envelope_stops_safely(monkeypatch, response):
    agent, calls = router_with_responses(monkeypatch, [response])
    with pytest.raises(WorkflowError):
        agent._call("Planner", "Instructions", {}, TaskPlan)
    assert len(calls) == 1


def test_openrouter_timeout_does_not_expose_request_details(monkeypatch):
    agent, calls = router_with_responses(monkeypatch, [httpx.ReadTimeout("SECRET")])
    with pytest.raises(WorkflowError, match="timed out") as error:
        agent._call("Planner", "Instructions", {}, TaskPlan)
    assert "SECRET" not in str(error.value)
    assert len(calls) == 1


def test_openrouter_truncated_output_stops_without_repair(monkeypatch):
    agent, calls = router_with_responses(monkeypatch, [router_response('{"partial":', "length")])
    with pytest.raises(WorkflowError, match="token limit"):
        agent._call("Planner", "Instructions", {}, TaskPlan)
    assert len(calls) == 1


def test_openrouter_strict_schema_requires_nullable_facts(monkeypatch):
    agent, calls = router_with_responses(monkeypatch, [router_response('{"assessments":[]}')])
    agent._call("Lead analyst", "Instructions", {}, AnalysisBatch)
    schema = calls[0][1]["json"]["response_format"]["json_schema"]["schema"]
    assessment = schema["$defs"]["Assessment"]
    assert "budget_inr" in assessment["required"]
    assert "timeline_days" in assessment["required"]
    assert assessment["additionalProperties"] is False
