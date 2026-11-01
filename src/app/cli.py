"""Interactive CLI for testing MINT LLM gateway, guardrails, and agents."""

import argparse
import asyncio
import hashlib
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel, Field

from app.adapters.llm.groq_adapter import (
    GroqAdapter,
    MissingAPIKeyError,
    RateLimitExceededError,
)
from app.agents.job_finder.graph import run_job_finder
from app.agents.job_finder.schemas import JobIngestRequest
from app.core.container import StorageContainer, build_in_memory_storage
from app.core.seed import seed_user_data
from app.core.settings import get_settings
from app.guardrails.pii_shield import contains_secret, shield
from app.ports.llm import (
    ROLE_MODEL_ROUTES,
    AgentRole,
    LLMClient,
    get_role_system_prompt,
)


class CLIJobPreview(BaseModel):
    """Structured schema for testing S2 structured extraction from the CLI."""

    title: str
    company: str
    location: str = "Remote / Unspecified"
    required_skills: list[str] = Field(default_factory=list)
    summary: str = ""


def _build_default_llm(user_api_key: str | None = None) -> GroqAdapter:
    settings = get_settings()
    key = (user_api_key or "").strip() or settings.active_groq_api_key()
    return GroqAdapter(default_api_key=key)


def _print_roles() -> None:
    print("\n=== MINT Role-Based Multi-Model Routes on Groq ===")
    print(f"{'AgentRole':<22} | {'Primary Model':<25} | {'Fallback Model':<25}")
    print("-" * 78)
    for role, route in ROLE_MODEL_ROUTES.items():
        print(f"{role.value:<22} | {route.primary:<25} | {route.fallback:<25}")
    print()


def _print_system_prompt(role: AgentRole) -> None:
    print(f"\n=== System Prompt for {role.value} ===")
    print(get_role_system_prompt(role))
    print()


def _print_shield(text: str) -> None:
    redacted = shield(text)
    print("\n=== PII & Credential Shield ===")
    print(f"Had secret/PII : {contains_secret(text)}")
    print(f"Redacted output: {redacted}\n")


async def _run_prompt(
    llm: LLMClient,
    text: str,
    role: AgentRole,
) -> int:
    route = ROLE_MODEL_ROUTES[role]
    safe_preview = shield(text)
    print(f"\n[Role]     {role.value} (Primary: {route.primary} | Fallback: {route.fallback})")
    print(f"[Shielded] {safe_preview}")
    try:
        reply = await llm.complete(text, role=role)
    except (RateLimitExceededError, MissingAPIKeyError) as exc:
        print(f"\n[UI Action: {exc.ui_action}] {exc}", file=sys.stderr)
        return 2
    print(f"\n[Response]\n{reply}\n")
    return 0


async def _run_extract(
    llm: LLMClient,
    text: str,
    role: AgentRole,
) -> int:
    route = ROLE_MODEL_ROUTES[role]
    safe_preview = shield(text)
    print(f"\n[Role]     {role.value} (Primary: {route.primary} | Fallback: {route.fallback})")
    print(f"[Shielded] {safe_preview}")
    try:
        parsed = await llm.complete_structured(text, CLIJobPreview, role=role, retries=2)
    except (RateLimitExceededError, MissingAPIKeyError) as exc:
        print(f"\n[UI Action: {exc.ui_action}] {exc}", file=sys.stderr)
        return 2
    print("\n[Validated Pydantic JSON Output]")
    print(json.dumps(parsed.model_dump(), indent=2))
    print()
    return 0


async def _run_job_finder_cli(
    llm: LLMClient,
    storage: StorageContainer,
    target: str,
    *,
    user_id: str = "cli-user",
) -> int:
    """Run S3 Job Finder on a URL, local HTML file path, or raw job description snippet."""
    raw_input = target.strip()
    url = raw_input
    raw_html_override: str | None = None

    candidate_path = Path(raw_input)
    if not raw_input.startswith(("http://", "https://")):
        if candidate_path.is_file():
            raw_html_override = candidate_path.read_text(encoding="utf-8")
            url = f"https://local.fixture/{candidate_path.name}"
        else:
            raw_html_override = f"<div>{raw_input}</div>"
            digest = hashlib.sha256(raw_input.encode("utf-8")).hexdigest()[:10]
            url = f"https://cli.inline/{digest}"

    print(f"\n=== S3 Job Finder Agent (User: {user_id}) ===")
    print(f"[Source] {url}")
    try:
        result = await run_job_finder(
            JobIngestRequest(
                url=url,
                user_id=user_id,
                raw_html_override=raw_html_override,
            ),
            llm=llm,
            storage=storage,
        )
    except (RateLimitExceededError, MissingAPIKeyError) as exc:
        print(f"\n[UI Action: {exc.ui_action}] {exc}", file=sys.stderr)
        return 2

    print(f"[Status]           {result.status.value}")
    print(f"[Job ID / Hash]    {result.job_id} ({result.job_hash or 'n/a'})")
    print(f"[Global Cache Hit] {result.from_global_cache}")
    print(f"[CV Match Score]   {result.match_score}% (Qualified: {result.qualified_for_tailoring})")
    if result.error_reason:
        print(f"[Reason]           {result.error_reason}")
    if result.job_spec is not None:
        print("\n[JobSpec Handoff]")
        print(json.dumps(result.job_spec.model_dump(mode="json"), indent=2))
    print()
    return 0


async def _run_interactive(
    llm: LLMClient,
    storage: StorageContainer,
    initial_role: AgentRole,
) -> int:
    current_role = initial_role
    print("\n=== MINT Interactive Agent CLI ===")
    print("Commands:")
    print("  /roles                  List all AgentRoles and Groq models")
    print("  /role <role_name>       Switch active AgentRole (e.g. /role analytical_reasoner)")
    print("  /system                 Show the active AgentRole's system prompt")
    print("  /shield <text>          Test PII/credential redaction locally")
    print("  /extract <job_text>     Run S2 structured Pydantic job preview")
    print("  /job <url|file|text>    Run S3 Job Finder (scrape + JobSpec + CV score + dedupe)")
    print("  /quit                   Exit interactive session")
    print(f"\nActive role: {current_role.value} ({ROLE_MODEL_ROUTES[current_role].primary})")
    print(f"System prompt: {get_role_system_prompt(current_role)}")

    while True:
        try:
            line = input(f"\nmint ({current_role.value})> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting.")
            return 0

        if not line:
            continue
        if line in ("/quit", "/exit", "exit", "quit"):
            print("Exiting.")
            return 0
        if line == "/roles":
            _print_roles()
            continue
        if line == "/system":
            _print_system_prompt(current_role)
            continue
        if line.startswith("/role "):
            target = line.split(" ", 1)[1].strip()
            try:
                current_role = AgentRole(target)
                print(
                    f"Switched to {current_role.value} "
                    f"(Primary: {ROLE_MODEL_ROUTES[current_role].primary})"
                )
                print(f"System prompt: {get_role_system_prompt(current_role)}")
            except ValueError:
                valid = ", ".join(r.value for r in AgentRole)
                print(f"Unknown role '{target}'. Valid roles: {valid}")
            continue
        if line.startswith("/shield "):
            _print_shield(line.split(" ", 1)[1])
            continue
        if line.startswith("/extract "):
            await _run_extract(llm, line.split(" ", 1)[1], current_role)
            continue
        if line.startswith("/job "):
            await _run_job_finder_cli(llm, storage, line.split(" ", 1)[1])
            continue

        await _run_prompt(llm, line, current_role)


def build_parser() -> argparse.ArgumentParser:
    """Construct the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="python -m app.cli",
        description="MINT Job Hunt AI — CLI for testing guardrails, LLM roles, and agents.",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="Optional BYOK Groq API key override for this command.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("roles", help="Show AgentRole -> Groq model routing table.")

    shield_p = sub.add_parser("shield", help="Test PII & secret redaction on a string.")
    shield_p.add_argument("text", help="Input string containing emails/phones/secrets.")

    role_choices = [r.value for r in AgentRole]

    prompt_p = sub.add_parser("prompt", help="Send a prompt through shield() to a Groq role.")
    prompt_p.add_argument("text", help="Prompt text to send.")
    prompt_p.add_argument(
        "--role",
        default=AgentRole.LIGHTWEIGHT_PARSER.value,
        choices=role_choices,
        help="AgentRole bucket to route to.",
    )

    extract_p = sub.add_parser(
        "extract",
        help="Extract a validated Pydantic CLIJobPreview object from raw job text.",
    )
    extract_p.add_argument("text", help="Raw job posting text.")
    extract_p.add_argument(
        "--role",
        default=AgentRole.LIGHTWEIGHT_PARSER.value,
        choices=role_choices,
        help="AgentRole bucket to route to.",
    )

    jf_p = sub.add_parser(
        "job-finder",
        help="Run the S3 Job Finder Agent on a URL, HTML fixture path, or raw job snippet.",
    )
    jf_p.add_argument("target", help="Job URL, local HTML file path, or raw job description text.")
    jf_p.add_argument(
        "--user-id",
        default="cli-user",
        help="User ID to score and deduplicate against.",
    )

    inter_p = sub.add_parser("interactive", help="Start an interactive REPL session.")
    inter_p.add_argument(
        "--role",
        default=AgentRole.LIGHTWEIGHT_PARSER.value,
        choices=role_choices,
        help="Initial AgentRole bucket.",
    )
    return parser


async def async_main(
    argv: Sequence[str] | None = None,
    *,
    llm_override: LLMClient | None = None,
    storage_override: StorageContainer | None = None,
) -> int:
    """Async entrypoint for CLI execution and unit testing."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "roles":
        _print_roles()
        return 0

    if args.command == "shield":
        _print_shield(args.text)
        return 0

    llm: LLMClient = llm_override or _build_default_llm(args.api_key)
    storage = storage_override or build_in_memory_storage()
    await seed_user_data(
        user_id="cli-user",
        profile_repo=storage.profile_repo,
        blob_store=storage.blob_store,
        vector_store=storage.vector_store,
    )

    if args.command == "job-finder":
        return await _run_job_finder_cli(llm, storage, args.target, user_id=args.user_id)

    role = AgentRole(args.role)

    if args.command == "prompt":
        return await _run_prompt(llm, args.text, role)

    if args.command == "extract":
        return await _run_extract(llm, args.text, role)

    if args.command == "interactive":
        return await _run_interactive(llm, storage, role)

    return 1


def main() -> None:
    """Synchronous console_scripts entrypoint."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(asyncio.run(async_main()))


if __name__ == "__main__":
    main()
