"""Markdown and deterministic single-page PDF renderer for S4 Resume Customizer (`R2`)."""

import re

from app.agents.resume.schemas import ResumeDraftContent
from app.guardrails.risk import Risk, tool
from app.ports.storage import BlobStore


def render_resume_markdown(
    draft: ResumeDraftContent,
    *,
    candidate_name: str = "MINT Candidate",
) -> str:
    """Format a validated `ResumeDraftContent` into clean Markdown with chunk citations."""
    lines = [
        f"# {candidate_name}",
        "",
        "## Professional Summary",
        draft.professional_summary.strip(),
        "",
        "## Experience & Impact",
    ]
    for bullet in draft.bullets:
        citations = ", ".join(bullet.source_chunk_ids)
        lines.append(f"- {bullet.text.strip()} [{citations}]")
    if draft.highlighted_skills:
        lines.extend(
            [
                "",
                "## Technical Skills",
                ", ".join(draft.highlighted_skills),
            ]
        )
    return "\n".join(lines) + "\n"


def _escape_pdf_text(text: str) -> str:
    safe = text.encode("ascii", errors="replace").decode("ascii")
    return safe.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def render_single_page_pdf(markdown_text: str) -> bytes:
    """Render Markdown text into a valid single-page PDF 1.4 document (zero native binaries)."""
    lines = [line.strip() for line in markdown_text.splitlines() if line.strip()]
    # Cap lines to fit cleanly on 1 standard Letter page (612 x 792 pt)
    visible_lines = lines[:42]

    stream_cmds = ["BT", "/F1 10 Tf", "50 750 Td", "14 TL"]
    for idx, raw_line in enumerate(visible_lines):
        escaped = _escape_pdf_text(raw_line[:95])
        if idx == 0:
            stream_cmds.append(f"({escaped}) Tj")
        else:
            stream_cmds.append(f"T* ({escaped}) Tj")
    stream_cmds.append("ET")
    stream_body = "\n".join(stream_cmds).encode("ascii")

    objects: list[bytes] = [
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n",
        (
            b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>\nendobj\n"
        ),
        b"4 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n",
        (
            f"5 0 obj\n<< /Length {len(stream_body)} >>\nstream\n".encode("ascii")
            + stream_body
            + b"\nendstream\nendobj\n"
        ),
    ]

    header = b"%PDF-1.4\n"
    body = b""
    offsets: list[int] = []
    current_offset = len(header)
    for obj in objects:
        offsets.append(current_offset)
        body += obj
        current_offset += len(obj)

    xref_lines = [f"xref\n0 {len(objects) + 1}", "0000000000 65535 f "]
    for off in offsets:
        xref_lines.append(f"{off:010d} 00000 n ")
    xref_bytes = ("\n".join(xref_lines) + "\n").encode("ascii")
    trailer = (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{current_offset}\n%%EOF\n"
    ).encode("ascii")
    return header + body + xref_bytes + trailer


def inspect_pdf_bytes(pdf_bytes: bytes) -> tuple[bool, int]:
    """Verify that `pdf_bytes` is a valid PDF and return `(is_valid, page_count)`."""
    if not pdf_bytes.startswith(b"%PDF-1.") or b"%%EOF" not in pdf_bytes:
        return (False, 0)
    match = re.search(rb"/Type\s*/Pages\b[^>]*?/Count\s+(\d+)", pdf_bytes, re.DOTALL)
    if not match:
        return (False, 0)
    return (True, int(match.group(1)))


@tool("render_resume_pdf", risk=Risk.R2_WRITE_INTERNAL)
async def render_and_store_resume(
    user_id: str,
    job_id: str,
    version: int,
    draft: ResumeDraftContent,
    *,
    blob_store: BlobStore,
    candidate_name: str = "MINT Candidate",
) -> tuple[str, str, bytes, bytes]:
    """Render Markdown and 1-page PDF and store both in `resumes-tailored` Blob container."""
    md_text = render_resume_markdown(draft, candidate_name=candidate_name)
    md_bytes = md_text.encode("utf-8")
    pdf_bytes = render_single_page_pdf(md_text)

    md_path = f"{user_id}/{job_id}/v{version}.md"
    pdf_path = f"{user_id}/{job_id}/v{version}.pdf"

    md_url = await blob_store.upload_bytes(
        "resumes-tailored", md_path, md_bytes, content_type="text/markdown"
    )
    pdf_url = await blob_store.upload_bytes(
        "resumes-tailored", pdf_path, pdf_bytes, content_type="application/pdf"
    )
    return pdf_url, md_url, pdf_bytes, md_bytes
