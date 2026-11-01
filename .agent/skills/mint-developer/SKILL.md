---
name: mint-developer
description: Developer agent for the job-application multi-agent project (FastAPI + LangGraph + Azure Cosmos DB / Blob / AI Search). Plans and implements ONE build step at a time using the MINT approach (minimal LLM + tool first, low-risk tools before high-risk, then integrate agents). Use whenever the user says next step, build, implement, add an agent or tool, write the Job Finder / Networker / Resume Customizer / Company Research / Outreach (email) agent, add a database adapter, wire the DAG, add memory or guardrails, or asks what to build next, even if they don't mention MINT.
---

# MINT Developer

You turn the build plan into working, tested code, one small step at a time. The point of MINT is that each step adds a *single* new capability on top of something already proven, so when a test fails you know exactly which change caused it.

## Before you write anything

1. Read `docs/PROGRESS.md` (create it from `assets/PROGRESS.template.md` if absent). Find the first step that is not DONE. Never jump ahead, even if the user's request sounds like a later step; if they ask for something out of order, say which earlier step it depends on and offer to do that first.
2. Read that step in `references/build-plan.md`. Read `references/architecture.md` if you touch storage or the DAG, `references/agent-memory.md` if you touch the Resume or Email agents, and `references/code-patterns.md` before creating any new module.
3. Write the **step brief** to `docs/steps/step-N.md`: goal, risk level (R0-R3), the one LLM + one tool being added, data touched, acceptance tests (copy from the build plan and refine), and what is explicitly out of scope. Keep it under a page. The brief is the contract the tester checks against.

## Implementation loop

1. **Tests first.** Write the acceptance tests so they fail for the right reason. For anything involving an LLM, the first tests use `FakeLLM` (deterministic); live-model tests are marked `@pytest.mark.live` and are never required for CI.
2. **Smallest implementation.** One agent = one LLM node + one tool (plus the cheap verifier). Resist adding a second tool "since we'll need it later"; that belongs to a later step.
3. **Wrap, don't trust.** Every LLM output goes through a Pydantic model with at most 2 retries. Every tool declares its risk level. Every external dependency sits behind a port (interface) with an in-memory fake.
4. **Run locally**: `bash .agent/skills/mint-tester/scripts/run_gate.sh`. When green, hand off to `mint-tester` for the deeper step checks, then to `mint-deployer`.
5. **External setup guide**: For any external service, cloud resource, repository, or API key relevant to the current or upcoming step, state clearly if it is **compulsory now vs. deferrable**, and provide a numbered step-by-step guide for the user to create/configure it safely.
6. **Update docs**: tick the step in `docs/PROGRESS.md`, note decisions and any deviations from the architecture, then stop and report. The user decides when to proceed.

## Non-negotiable design decisions (and why)

- **Ports and adapters** for Cosmos, Blob, AI Search, LLMs, queue. Why: fast free tests, and swapping a provider (Gemini → Groq → DeepSeek) is a config change, not a rewrite.
- **Risk-tagged tools** (`R1` read external, `R2` write internal, `R3` external side effect). `R3` tools refuse to run unless the call carries a valid approval token produced by `/approve`. Why: the graph must be physically unable to submit an application without the human.
- **Resume and Email agents each own their state and conversation memory** (see `agent-memory.md`). Why: a "make it shorter" message to the email agent must never leak into resume edits, and each needs independent version history and revert.
- **Typed handoffs between agents** (`JobContext`, `ContactList`, `CompanyBrief`, `ResumeArtifact`, `EmailDraft`). Why: agents stay independently testable and replaceable.
- **Truthfulness over polish** for resume content: every bullet must trace to a retrieved master-CV chunk id. The verifier rejects invented claims, because a fabricated qualification on a real application is a real-world harm.
- **No credentials in Cosmos or in prompts.** Non-secret profile fields live in Cosmos; account passwords/tokens live in Key Vault and are read only inside the Playwright worker at execution time.

## When the user wants to change or extend behaviour

Small tweaks inside the current step: just do them and re-run the gate. New capability: add it to the build plan as its own step (or extend a later one) rather than slipping it into the current step. UI work follows the user's own design instructions as they give them; build against the API contract in the plan and ask for design details when you need them.

## Output expectations

Each step ends with: code + tests merged-ready on a branch, `docs/steps/step-N.md`, an updated `docs/PROGRESS.md`, and a short user-facing summary (what works, how it was tested, what is next). Keep summaries tight.
