"""HTML/JSON-LD job page cleaner (<=750 tokens) and normalized job hash generator."""

import hashlib
import html
import json
import re
from html.parser import HTMLParser
from urllib.parse import urlparse, urlunparse

_SKIP_TAGS = frozenset({"script", "style", "noscript", "svg", "nav", "footer", "header", "iframe"})
_CORPORATE_SUFFIX_RE = re.compile(
    r"\b(?:inc|incorporated|llc|l\.l\.c|ltd|limited|corp|corporation|co|company|gmbh|plc)\b\.?",
    re.IGNORECASE,
)
_JSON_LD_RE = re.compile(
    r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
    re.IGNORECASE | re.DOTALL,
)


class _TextExtractor(HTMLParser):
    """Lightweight stdlib HTML text extractor that skips boilerplate/script tags."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_lower = tag.lower()
        if tag_lower in _SKIP_TAGS:
            self._skip_depth += 1
            return
        # Skip elements explicitly hidden with display:none
        for attr_name, attr_val in attrs:
            if (
                attr_name.lower() == "style"
                and attr_val
                and "display:none" in attr_val.replace(" ", "").lower()
            ):
                self._skip_depth += 1
                return
        if tag_lower in {"p", "div", "li", "h1", "h2", "h3", "h4", "br", "tr", "section"}:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in _SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            cleaned = data.strip()
            if cleaned:
                self._chunks.append(cleaned + " ")

    def get_text(self) -> str:
        raw = "".join(self._chunks)
        lines = [re.sub(r"\s+", " ", line).strip() for line in raw.splitlines()]
        return "\n".join(line for line in lines if line)


def _extract_json_ld_job_posting(raw_html: str) -> str:
    """Extract schema.org JobPosting JSON-LD summary if embedded in the HTML."""
    summaries: list[str] = []
    for match in _JSON_LD_RE.finditer(raw_html):
        block = html.unescape(match.group(1).strip())
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            if isinstance(item, dict) and str(item.get("@type", "")).lower() == "jobposting":
                title = item.get("title", "")
                org = item.get("hiringOrganization", {})
                company = org.get("name", "") if isinstance(org, dict) else str(org)
                loc = item.get("jobLocation", {})
                addr = loc.get("address", {}) if isinstance(loc, dict) else {}
                locality = addr.get("addressLocality", "") if isinstance(addr, dict) else ""
                desc = str(item.get("description", ""))[:600]
                summaries.append(
                    f"[JSON-LD JobPosting] Title: {title} | Company: {company} | "
                    f"Location: {locality} | Description: {desc}"
                )
    return "\n".join(summaries)


def clean_job_html(raw_html: str, *, max_chars: int = 3000) -> str:
    """Clean raw HTML down to <=750 tokens (~3000 chars) while preserving JSON-LD JobPosting."""
    json_ld_summary = _extract_json_ld_job_posting(raw_html)
    parser = _TextExtractor()
    parser.feed(raw_html)
    visible_text = parser.get_text()

    combined = f"{json_ld_summary}\n\n{visible_text}".strip() if json_ld_summary else visible_text
    if len(combined) <= max_chars:
        return combined
    return combined[:max_chars].rsplit(" ", 1)[0]


def normalize_entity_text(value: str, *, strip_corp_suffix: bool = False) -> str:
    """Normalize text for hashing (lowercase, strip corporate suffixes and punctuation)."""
    text = value.lower()
    if strip_corp_suffix:
        text = _CORPORATE_SUFFIX_RE.sub(" ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def compute_job_hash(company: str, title: str) -> str:
    """Compute a deterministic 24-char SHA-256 job hash from normalized company and title."""
    norm_company = normalize_entity_text(company, strip_corp_suffix=True)
    norm_title = normalize_entity_text(title, strip_corp_suffix=False)
    canonical = f"{norm_company}::{norm_title}"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]


def normalize_job_url(url: str) -> str:
    """Normalize a job URL for cross-user GlobalJobCacheRepo keys."""
    raw = url.strip()
    parsed = urlparse(raw)
    if not parsed.scheme:
        return raw.lower()
    clean_path = parsed.path.rstrip("/") or "/"
    return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), clean_path, "", "", ""))
