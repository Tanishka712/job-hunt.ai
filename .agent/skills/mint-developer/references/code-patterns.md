# Code Patterns

## Repo layout
```
src/app/
  api/            FastAPI routers (thin: validate, call graph, return)
  agents/
    job_finder/   graph.py, tools.py, schemas.py, prompts.py
    resume/       (own state, own memory)
    email/        (own state, own memory)
    networker/  company_research/
  graphs/         dag.py (S8)
  ports/          Protocols only (no imports of azure/llm SDKs)
  adapters/       cosmos/, blob/, search/, llm/, queue/, fakes/
  guardrails/     pii_shield.py, validator.py, budget.py, approval.py
  core/           settings.py, logging.py, ids.py
tests/{unit,contract,integration,safety,live,e2e}/
docs/{steps,test-reports,runbook.md,PROGRESS.md}
```
Agents depend on `ports`, never on `adapters`. Wiring happens in one composition root (`core/container.py`), so tests swap in fakes.

## Port + fake
```python
class JobHashRepo(Protocol):
    async def exists(self, user_id: str, h: str) -> bool: ...
    async def put(self, user_id: str, h: str, payload: dict) -> None: ...

class InMemoryJobHashRepo:      # adapters/fakes
    ...
```
Write the contract test once, parametrize over `[InMemory..., Cosmos...]`.

## Risk-tagged tools
```python
class Risk(IntEnum): R1_READ_EXTERNAL = 1; R2_WRITE_INTERNAL = 2; R3_SIDE_EFFECT = 3

def tool(name: str, risk: Risk):
    def wrap(fn):
        @functools.wraps(fn)
        async def inner(*a, approval: ApprovalToken | None = None, **kw):
            if risk is Risk.R3_SIDE_EFFECT:
                require_valid_approval(approval, name)   # raises if missing/stale/forged
            return await fn(*a, **kw)
        inner.risk = risk; inner.tool_name = name
        return inner
    return wrap
```
A safety test enumerates every registered tool and asserts that every `R3` tool raises without a token.

## LLM call with validation
```python
async def call_structured(llm, prompt, model: type[T], *, retries=2) -> T:
    last_err = None
    for _ in range(retries + 1):
        raw = await llm.complete(shield(prompt), response_format=model)
        try: return model.model_validate_json(raw)
        except ValidationError as e:
            last_err = e; prompt = add_error_feedback(prompt, e)
    raise StructuredOutputError(model, last_err)
```

## FakeLLM
Scripted responses keyed by a prompt marker or sequence, so tests can force: valid output, malformed JSON, invented claim, 200-word email, timeout. No agent test should need network.

## LangGraph notes
- Parallel branches: run Networker, Resume and Company Research as concurrent nodes; collect results with a reducer that tolerates a failed branch (record the error, continue).
- Checkpointing: use an in-memory saver until S8, then a Cosmos-backed saver. LangGraph APIs change between releases, so pin versions and check the current docs before writing the saver.
- Keep prompts in `prompts.py`, versioned by constant name (e.g. `RESUME_DRAFT_V1`) so eval results can be tied to a prompt version.

## Settings
Pydantic `BaseSettings`; env vars only; a `.env.example` with names but no values. Secrets from Key Vault references in Container Apps.
