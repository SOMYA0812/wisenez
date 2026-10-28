from pathlib import Path

from streamlit.testing.v1 import AppTest

from dealdesk.storage import Store


def button(app, label):
    return next(b for b in app.button if b.label == label)


def test_app_prepare_approve_execute_and_reload(tmp_path, monkeypatch):
    db = tmp_path / "ui.sqlite3"
    monkeypatch.setenv("DEALDESK_DB", str(db))
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=20)
    app.query_params["page"] = "dashboard"
    app.run()
    assert not app.exception
    assert app.title[0].value == "YOUR AI WORKFORCE."
    button(app, "Prepare workflow").click().run()
    assert not app.exception
    store = Store(db)
    run = store.runs()[0]
    assert run["state"] == "review"
    assert store.rows("SELECT * FROM outbox") == []
    next(x for x in app.text_input if x.label == "Approving person's name").set_value("UI demo owner")
    next(x for x in app.checkbox if x.label.startswith("I have saved my edits")).check()
    button(app, "Approve this version").click().run()
    assert not app.exception
    assert store.run(run["id"])["state"] == "approved"
    button(app, "Execute approved actions").click().run()
    assert not app.exception
    assert store.run(run["id"])["state"] == "completed"
    assert len(store.rows("SELECT * FROM outbox")) == 4
    app.run()
    assert not app.exception
    assert len(store.rows("SELECT * FROM outbox")) == 4


def test_app_openrouter_missing_key_is_clear_and_no_run_is_created(tmp_path, monkeypatch):
    db = tmp_path / "router-ui.sqlite3"
    monkeypatch.setenv("DEALDESK_DB", str(db))
    # Keep dotenv from loading a developer's actual credential into this test.
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=20)
    app.query_params["page"] = "dashboard"
    app.run()
    next(x for x in app.selectbox if x.label == "Agent mode").select("Live OpenRouter").run()
    assert not app.exception
    assert any("OPENROUTER_API_KEY" in x.value for x in app.warning)
    button(app, "Prepare workflow").click().run()
    assert not app.exception
    assert any("OPENROUTER_API_KEY" in x.value for x in app.error)
    assert Store(db).runs() == []


def test_landing_enters_dashboard_and_home_returns_without_model_calls(tmp_path, monkeypatch):
    monkeypatch.setenv("DEALDESK_DB", str(tmp_path / "landing.sqlite3"))
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=20).run()
    assert not app.exception
    button(app, "Enter workspace").click().run()
    assert not app.exception
    assert app.query_params["page"] == "dashboard"
    assert app.title[0].value == "YOUR AI WORKFORCE."
    button(app, "Home").click().run()
    assert not app.exception
    assert app.query_params["page"] == "landing"
    assert any(b.label == "Enter workspace" for b in app.button)


def test_existing_workflow_deep_link_opens_dashboard(tmp_path, monkeypatch):
    from dealdesk.agents import SampleAgents
    from dealdesk.workflow import Workflow
    db = tmp_path / "deep-link.sqlite3"
    monkeypatch.setenv("DEALDESK_DB", str(db))
    store = Store(db)
    run_id = Workflow(store).prepare("Review only these leads", ["L001"], SampleAgents())
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=20)
    app.query_params["run"] = run_id
    app.run()
    assert not app.exception
    assert app.title[0].value == "YOUR AI WORKFORCE."
