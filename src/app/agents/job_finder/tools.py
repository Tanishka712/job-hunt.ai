"""R1 external read tool `scrape_job` with robots.txt check and HTML cleaning."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

from app.agents.job_finder.html_cleaner import clean_job_html
from app.guardrails.risk import Risk, tool

USER_AGENT = "MINTJobHuntBot/0.1 (+https://github.com/Tanishka712/job-hunt.ai)"


@dataclass(frozen=True)
class HttpResponseData:
    """Transport response returned by an HTTP fetcher."""

    status_code: int
    text: str
    url: str


HttpFetcher = Callable[[str], Awaitable[HttpResponseData]]


class ScrapeError(Exception):
    """Raised when scraping a job posting fails or is disallowed."""


class RobotsDisallowedError(ScrapeError):
    """Raised when the site's robots.txt disallows scraping the target URL."""


@dataclass(frozen=True)
class ScrapedJobPage:
    """Cleaned text and metadata returned by the `scrape_job` R1 tool."""

    url: str
    cleaned_text: str
    raw_length: int


async def default_httpx_fetcher(url: str) -> HttpResponseData:
    """Default async HTTP GET fetcher using httpx."""
    async with httpx.AsyncClient(
        timeout=15.0,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        resp = await client.get(url)
        return HttpResponseData(status_code=resp.status_code, text=resp.text, url=str(resp.url))


def _is_allowed_by_robots_txt(robots_txt: str, target_url: str) -> bool:
    """Check whether `robots_txt` permits fetching `target_url` for our User-Agent or `*`."""
    rp = RobotFileParser()
    rp.parse(robots_txt.splitlines())
    return rp.can_fetch(USER_AGENT, target_url) and rp.can_fetch("*", target_url)


@tool("scrape_job", risk=Risk.R1_READ_EXTERNAL)
async def scrape_job(
    url: str,
    *,
    fetcher: HttpFetcher | None = None,
    check_robots: bool = True,
) -> ScrapedJobPage:
    """Fetch a public job URL after checking robots.txt and clean HTML to <=750 tokens.

    Tagged as `Risk.R1_READ_EXTERNAL`: strictly read-only, with no storage write access.
    """
    active_fetcher = fetcher or default_httpx_fetcher
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        raise ScrapeError(f"Invalid job URL: '{url}'")

    if check_robots:
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        try:
            robots_resp = await active_fetcher(robots_url)
            if robots_resp.status_code == 200 and not _is_allowed_by_robots_txt(
                robots_resp.text, url
            ):
                raise RobotsDisallowedError(f"Disallowed by robots.txt for URL: {url}")
        except RobotsDisallowedError:
            raise
        except Exception:
            # If robots.txt itself is unreachable/404, standard web etiquette allows proceeding
            pass

    page_resp = await active_fetcher(url)
    if page_resp.status_code >= 400:
        raise ScrapeError(f"HTTP {page_resp.status_code} when fetching job URL: {url}")

    cleaned = clean_job_html(page_resp.text, max_chars=3000)
    return ScrapedJobPage(
        url=url,
        cleaned_text=cleaned,
        raw_length=len(page_resp.text),
    )
