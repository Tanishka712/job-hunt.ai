"""Interactive CLI for testing MINT LLM gateway, guardrails, and agents."""

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence

from pydantic import BaseModel, Field

from app.adapters.llm.groq_adapter import (
    GroqAdapter,
    MissingAPIKeyError,
    RateLimitExceededError,
)
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


async def _run_interactive(llm: LLMClient, initial_role: AgentRole) -> int:
    current_role = initial_role
    print("\n=== MINT Interactive Agent CLI ===")
    print("Commands:")
    print("  /roles                  List all AgentRoles and Groq models")
    print("  /role <role_name>       Switch active AgentRole (e.g. /role analytical_reasoner)")
    print("  /system                 Show the active AgentRole's system prompt")
    print("  /shield <text>          Test PII/credential redaction locally")
    print("  /extract <job_text>     Run structured Pydantic job extraction on live LLM")
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
    role = AgentRole(args.role)

    if args.command == "prompt":
        return await _run_prompt(llm, args.text, role)

    if args.command == "extract":
        return await _run_extract(llm, args.text, role)

    if args.command == "interactive":
        return await _run_interactive(llm, role)

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
