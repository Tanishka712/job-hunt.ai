# MINT Principles (always on)

This repo builds a job-application agent system step by step using **MINT — Minimal Intelligence, Necessary Tools**.
The system: Job Finder → (Networker ‖ Resume Customizer ‖ Company Research) → Outreach Drafter → HITL approval → Playwright worker.
Stack: FastAPI + LangGraph on Azure Container Apps, Cosmos DB, Blob Storage, Azure AI Search, GitHub → Azure Pipelines.

## The rules, and why they exist

1. **One step at a time.** The ordered plan is in `.agent/skills/mint-developer/references/build-plan.md`. Work on exactly one step. Stacking unverified steps makes failures impossible to localize, and agent bugs are already hard enough to find.
2. **Smallest agent first: one LLM + one tool.** Add a second tool, a second agent, or a loop only after the first version is tested and deployed. Every extra capability multiplies the failure modes.
3. **Climb the risk ladder, never skip rungs.**
   - R0 pure logic / no I/O → R1 read-only external (scrape, search) → R2 writes to *our own* storage → R3 side effects in the outside world (form submit, email send).
   - R3 tools are unreachable without an explicit, signed human approval and a passing dry-run. No exceptions, even for "just a test".
4. **Tests gate every step.** A step is done only when the gate in `mint-tester` passes locally and in Azure Pipelines. Code that is not tested is not "almost done"; it is not done.
5. **Ports and adapters.** Cosmos, Blob, AI Search and every LLM are behind interfaces with an in-memory fake. This keeps unit tests fast and free (the Azure student credit is limited) and lets agents be tested without network or cost.
6. **Deterministic checks wrap every LLM call.** Pydantic schema validation, max 2 retries, then fail loudly. Never parse free text with regexes in the happy path.
7. **Secrets never enter prompts, logs, or the repo.** Passwords and tokens live in Key Vault / pipeline secrets. PII is stripped before any external model call.
8. **Separate state for Resume and Email agents.** Each has its own state schema, own conversation memory, own versions. They exchange only typed handoff objects, never message histories.
9. **Stop at gates.** After each step, update `docs/PROGRESS.md`, summarize, and wait for the user to say "next". Do not start the next step on your own.
10. **Proactive step-by-step external setup guides.** Whenever a step touches an external account, cloud project, repository, or API (GitHub, Azure, Groq, Search APIs, etc.), ALWAYS:
    - State clearly whether creating it is **compulsory right now** or **can be deferred** (because local development uses `InMemory*` fakes and `FakeLLM`).
    - Provide a complete, numbered **step-by-step guide** showing the user what account/project/API to create, exact CLI commands or portal clicks, cost tier, and where to store the resulting config/keys safely (`.env`, GitHub Secrets, or Azure Key Vault — never pasted into chat).
11. **Interactive CLI testing at every agentic stage.** Every stage that adds or modifies agentic architecture (`S2`–`S8`) MUST add or update a subcommand in `src/app/cli.py` (`python -m app.cli ...`) so the user can test the live agent directly from their terminal, and every step summary must include exact copy-paste CLI commands for the user to try.

## Which agent to use

| Situation | Skill |
|---|---|
| Plan or write code for the next step | `mint-developer` |
| Prove a step works (or find why not) | `mint-tester` |
| Git push, pipeline, Azure resources, release, rollback | `mint-deployer` |

Workflows: `/mint-next-step` (full loop), `/mint-test-step`, `/mint-deploy-step`, `/mint-status`.

## Communication style
Short status updates. Show the failing test output, not a paraphrase. If a requirement is ambiguous (especially UI, which the user specifies as work proceeds), ask one concrete question and propose a default.
