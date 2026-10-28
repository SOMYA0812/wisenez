# Wisnez

## Landing page and dashboard

The default URL opens the cinematic business-themed landing page. **Enter workspace** opens `?page=dashboard`; **Home** returns to the landing page. Existing `?run=...` links still open the dashboard directly. All four dashboard views use the dark brown office-window theme. The italic display font is bundled Instrument Serif under the included SIL Open Font License.

## Vercel deployment

`Dockerfile.vercel` and `vercel.json` select Vercel's Container runtime and run Streamlit on the supplied `PORT`. Deploy with `npx vercel --prod` after authenticating, or import this GitHub repository in Vercel using the Container framework preset.

The container copies only application code, static assets, requirements and the non-secret Streamlit config. Local `.env`, API keys and databases are excluded. Set a provider key through Vercel environment variables only when enabling live AI; sample mode works without credentials.

This container is an MVP demo using SQLite under `/tmp/wisnez`. Its data is not durable across cold starts or shared between instances. The UI labels this limitation. Use an external persistent database before relying on cloud approval history or customer records. Container availability, WebSocket support and function-duration limits must be verified in the target Vercel account.

A Python MVP for Code E Fiesta problem statement two: an AI team prepares lead follow-ups, a person approves the exact preview, and a deterministic executor commits the approved CRM changes and simulated emails.

**Simulated business tools. Real approval. No email is delivered.**

## Start on Windows

Python 3.11 or newer is recommended. This project was exercised on Python 3.14.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m streamlit run app.py
```

Open the local URL printed by Streamlit. Activation of the virtual environment is optional when using these commands. If a file watcher causes problems on a synced folder, add `--server.fileWatcherType none`.

The frontend uses a warm architectural style inspired by the supplied Eloqwnt/Siwa Capital reference. Provider selection and saved workflows are in the initially collapsed sidebar; use the double-arrow control at the top left to open it. The architecture photo is served locally from `static/`; keep Streamlit static serving enabled in `.streamlit/config.toml`. Design details are in `docs/design.md`.

On macOS/Linux, use `.venv/bin/python` in place of `.\.venv\Scripts\python.exe`.

## Operating modes

- **Sample demo · no live AI:** deterministic extraction and sample drafts. Works without a key. It is neither live AI nor a recording of an AI call.
- **Live OpenRouter:** separate structured model calls through your OpenRouter key. Uses the same agent roles, validation, human approval, and local execution rules as direct Gemini.
- **Live Gemini:** separate structured model calls for the planner, analyst, and writer. Python validates their outputs and controls all business writes.
- **Recorded replay · saved AI:** reuses outputs from a successful live preparation only when the request, selected source records, and policy match exactly. It never quietly falls back to generated sample content.

To use your OpenRouter key:

1. Open the ignored local `.env` file (or copy `.env.example` to `.env` if absent).
2. Set `OPENROUTER_API_KEY` there. Never paste the key into chat, the business request, or customer records.
3. `OPENROUTER_MODEL` defaults to `google/gemini-2.5-flash`. You can change it to another OpenRouter model supporting JSON-schema structured outputs. Model access and credits are determined by your OpenRouter account.
4. Restart Streamlit and select **Live OpenRouter** in the sidebar. Click **Prepare workflow** to run the agents. Approval and execution remain separate manual steps.

The OpenRouter integration calls the fixed `https://openrouter.ai/api/v1/chat/completions` endpoint with a bearer header, strict JSON schema, and `provider.require_parameters=true` to require a compatible endpoint. An OpenRouter key works without a separate Google key, including when using a Google model through OpenRouter. Provider errors show a safe explanation for invalid keys, insufficient credits, rate limits, unavailable models, or incompatible structured output; raw provider responses and credentials are never displayed.

References: [OpenRouter structured outputs](https://openrouter.ai/docs/guides/features/structured-outputs), [default model](https://openrouter.ai/google/gemini-2.5-flash).

To use direct Gemini instead:

1. Create a Gemini key in [Google AI Studio](https://aistudio.google.com/apikey).
2. Copy `.env.example` to `.env` and set `GEMINI_API_KEY` locally. Never paste a key into a customer record or commit it.
3. `GEMINI_MODEL` defaults to `gemini-3.8-flash`, the model documented when the project was built. Change it if your account requires another model supporting structured Interactions responses.
4. Restart Streamlit, select **Live Gemini**, and prepare a workflow. Approval and execution are separate manual steps.

Direct Gemini uses the `google-genai` Interactions API and Pydantic JSON schemas. Both live providers stop preparation on provider/network errors without business writes. Invalid structured output gets one correction attempt. A missing key never substitutes fake live output.

No live API call can be verified until a valid key, model access, and connectivity are available. The automated tests use deterministic doubles and do not consume API credits.

References: [Gemini setup](https://ai.google.dev/gemini-api/docs/get-started), [structured output](https://ai.google.dev/gemini-api/docs/structured-output).

## Three-minute demo

1. Keep **Sample demo** selected. The first five fictional leads include a hot lead, a warm lead with missing information, and an opted-out contact.
2. Click **Prepare workflow**. No CRM business fields or outbox entries change.
3. Open **Review**. Inspect the task plan, exact evidence quotes, qualification rule, before/after CRM values, recipients, and complete drafts. The opted-out contact has no executable action.
4. Edit an email and click **Save preview edits**. The version and fingerprint change. Any previous approval is invalidated.
5. Enter a name, confirm review, and click **Approve this version**.
6. Open **Execution**, expand **Demonstrate failure recovery**, select **CRM fails once**, and click **Execute approved actions**.
7. Inspect the retry/recovery events and simulated outbox. **Impact** shows successful workflows, blocked contacts, recovery counts, and the explicit five-minute-per-workflow effort assumption.

To prove stale approval handling, approve a new workflow, then edit an affected customer through **Workspace → Inspect or update a customer record**. Execution will invalidate the preview. Prepare a new workflow from the updated records.

To prove partial recovery, choose **CRM stays unavailable**. The first unfinished lead stops after two attempts; independent leads can complete. Select **None** and **Resume unfinished actions**. Previously completed leads are not repeated.

To prove atomic writes, choose **Outbox fails once**. The CRM update is rolled back with the failed outbox insertion before the retry succeeds.

To demonstrate live adaptability, add a fresh fictional enquiry with a different company, budget and timeline, then select it and use Live OpenRouter or Live Gemini. Run another preparation with identical inputs in replay mode **before executing**; execution changes source snapshots and intentionally makes that original recording ineligible for later replay.

## Architecture

```text
Streamlit workspace
  → Planner: supported tasks and selected leads
  → Lead analyst: facts and exact enquiry quotes
  → Python: classification and contact eligibility
  → Outreach writer: personalised drafts for eligible hot/warm leads
  → Versioned preview
  → Human approval tied to SHA-256 fingerprint
  → Python executor: source recheck + SQLite transaction per lead
  → CRM state + simulated outbox + event trail
```

- `dealdesk/agents.py`: role instructions, typed model calls, sample mode and live recordings.
- `dealdesk/workflow.py`: orchestration, dependency checks, policy enforcement, approvals, editing, rejection, recovery and execution.
- `dealdesk/storage.py`: SQLite persistence and short, explicit transactions.
- `dealdesk/models.py`: typed contracts; unknown budget/timeline remain null.
- `dealdesk/ui.py`: four-tab interface, source editor, fresh enquiries and run selection.

There is no public HTTP API. The internal interface is `Workflow.prepare`, `approve`, `edit`, `reject`, and `execute`. Preview version and fingerprint are required when approving; version is required when editing or rejecting.

## Important guarantees and limits

- Agents cannot call write tools or approve their own work. Customer text and previous agent output are treated as untrusted data.
- Python validates supported task dependencies, lead IDs, output coverage, evidence quotes and draft structure. Exact quotes make decisions inspectable; they do not prove that every model interpretation is correct. Human review remains necessary.
- Hot means an offered service, stated budget of at least INR 10,000, and known timeline within 30 days. Other interested leads are warm unless their budget or requested service explicitly mismatches the policy. Cold leads can have an approved CRM review update, but receive no follow-up draft/email.
- Invalid email, opt-out, or conflicting identity blocks all business actions for that lead. Duplicate email identities are checked again at execution.
- Read-only analysis and drafts happen automatically. Every business write needs approval. Approval records a name as a demo audit label; this is not authentication or a verified identity system.
- The entire prepared plan, source snapshots, policy and version are fingerprinted. Draft/CRM-summary edits invalidate approval. Changes to relevant customer data or company policy expire pending actions.
- Each lead's CRM update, simulated outbox insertion, completion marker and success event commit atomically. Stable action IDs and write transactions prevent duplicate execution on retries or repeated clicks. This guarantee applies to the local SQLite simulated tools, not to an external email service.
- One automatic retry is allowed per invocation. Persistent failure is visible; another explicit resume attempt is required. Completed actions are preserved.
- State survives refresh and restart. Interrupted preparations can be prepared again; approved/partially completed workflows can resume. Work is performed synchronously, so a live preparation can take time.
- Policies remain human-authored. Shared memory includes source enquiry, policy and customer history; no vector database or autonomous policy learning is included.
- Operational counts are scoped to the selected workflow. Estimated effort is five minutes per completed lead workflow, not measured savings or revenue.

## Persistence

The ignored `data/dealdesk.sqlite3` file stores the simulated CRM, policies, workflow snapshots, proposed actions, approval history, outbox, events and live response recordings. Ten fictional leads are inserted only if absent, so app restarts do not reset business data. All seeded addresses use reserved `.example` domains.

Use `DEALDESK_DB` in `.env` to choose another database for a fresh demonstration without deleting previous data. Recordings and customer information are local data: use fictional enquiries for public demonstrations.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Tests exercise unapproved/rejected execution, exact preview execution, edits, stale source/policy data, conflicting identity, malformed agent output, prompt injection, transaction rollback, retry limits, partial resume, concurrent duplicate clicks, restart persistence, matching live-recording doubles, and the Streamlit prepare → approve → execute flow.

Live AI acceptance is a separate manual check using your own key: add a fresh enquiry, prepare it in Live OpenRouter or Live Gemini, inspect evidence and draft quality, approve, execute, and confirm that the outbox exactly matches the reviewed version.

## MVP boundaries

This is a single-operator local demonstration. Real email/CRM APIs, login and permissions, background workers, multiple businesses, automatic scheduling, arbitrary workflows and general code-repair agents are deliberately deferred. Deploying this beyond a trusted local demo requires authentication and an appropriate tool adapter.
