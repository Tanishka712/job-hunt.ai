"""Safety tests enforcing strict isolation between Resume (S4) and Email (S7) agents."""

import ast
from pathlib import Path

import pytest

from app.agents.resume.state import ResumeState, build_resume_session_id

SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "app" / "agents"


def _collect_imported_modules(package_dir: Path) -> set[str]:
    imported: set[str] = set()
    if not package_dir.exists():
        return imported
    for py_file in package_dir.rglob("*.py"):
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported.add(alias.name)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
    return imported


@pytest.mark.safety
def test_resume_and_email_packages_never_import_each_other() -> None:
    """AST import-boundary check: resume and email packages must never import each other."""
    resume_dir = SRC_ROOT / "resume"
    email_dir = SRC_ROOT / "email"

    resume_imports = _collect_imported_modules(resume_dir)
    assert resume_imports, "Expected src/app/agents/resume to contain Python modules"
    for mod in resume_imports:
        assert not mod.startswith("app.agents.email"), f"Forbidden import '{mod}' in resume package"

    if email_dir.exists():
        email_imports = _collect_imported_modules(email_dir)
        for mod in email_imports:
            assert not mod.startswith("app.agents.resume"), (
                f"Forbidden import '{mod}' in email package"
            )


@pytest.mark.safety
def test_resume_state_rejects_email_session_ids() -> None:
    """ResumeState session_id validator rejects any non-resume session prefix."""
    valid_id = build_resume_session_id("user-1", "job-1")
    assert valid_id == "resume:user-1:job-1"

    with pytest.raises(ValueError, match="must start with 'resume:'"):
        ResumeState(
            session_id="email:user-1:job-1:contact-1",
            user_id="user-1",
            job_id="job-1",
            jd_requirements=[],
            retrieved_chunks=[],
            pinned_instructions=[],
            current_version=0,
        )
