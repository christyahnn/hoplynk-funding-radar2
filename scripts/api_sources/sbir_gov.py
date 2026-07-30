"""
SBIR.gov / DSIP public API scraper (GitHub-only build).

Endpoint: https://api.www.sbir.gov/public/api/solicitations
Docs: https://www.sbir.gov/api -- verify field names there if parsing comes
back empty; this was written without live-API access from the build
environment, so field-name fallbacks below are best-effort until confirmed.
"""

from __future__ import annotations

import json
import random
import sys
import time
from datetime import datetime, date
from pathlib import Path
from typing import Optional

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from matching import flatten_strings, is_relevant, keyword_matches, match_tier
from models import Opportunity

SOURCE = "sbir_gov"
API_URL = "https://api.www.sbir.gov/public/api/solicitations"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; HoplynkFundingRadar/2.0)"}

MAX_RETRIES = 4
BASE_BACKOFF_SECONDS = 8  # doubles each retry: ~8s, 16s, 32s, 64s, plus jitter


def _parse_date(value) -> Optional[date]:
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(str(value)[:19], fmt).date()
        except ValueError:
            continue
    return None


def fetch() -> list[dict]:
    """Returns a list with one raw-fetch record (kept as a list for a
    consistent interface with multi-query sources like sam_gov).

    GitHub Actions runners share IP ranges across many unrelated jobs, so a
    429 here often isn't about this project's own request volume -- it's
    the shared IP getting caught by SBIR.gov's rate limiter. Retries with
    exponential backoff, honoring the server's own Retry-After header when
    it sends one, since that's the most reliable signal for how long to
    actually wait."""
    last_exception = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = httpx.get(API_URL, params={"agency": "DOD", "open": 1, "rows": 100}, headers=HEADERS, timeout=30)
            if resp.status_code == 429:
                retry_after = resp.headers.get("Retry-After")
                wait = float(retry_after) if retry_after else BASE_BACKOFF_SECONDS * (2 ** attempt) + random.uniform(0, 3)
                print(f"[sbir_gov] 429 rate limited (attempt {attempt + 1}/{MAX_RETRIES}) -- waiting {wait:.1f}s", file=sys.stderr)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return [{
                "raw_content": resp.text,
                "source_url": str(resp.request.url),
                "fetch_method": "api",
                "content_type": "json",
                "external_id": None,
            }]
        except httpx.HTTPError as e:
            last_exception = e
            wait = BASE_BACKOFF_SECONDS * (2 ** attempt) + random.uniform(0, 3)
            print(f"[sbir_gov] fetch error on attempt {attempt + 1}/{MAX_RETRIES} ({e}) -- retrying in {wait:.1f}s", file=sys.stderr)
            time.sleep(wait)

    print(f"[sbir_gov] giving up after {MAX_RETRIES} attempts. Last error: {last_exception}", file=sys.stderr)
    return []


def parse(raw_content: str, raw_document_path: str) -> list[Opportunity]:
    data = json.loads(raw_content)
    items = data if isinstance(data, list) else data.get("results", [])

    opportunities = []
    for item in items:
        name = (item.get("solicitation_title") or item.get("topic_title") or "").strip()
        if not name:
            continue

        full_blob = flatten_strings(item)
        if not is_relevant(full_blob):
            continue

        objective = (
            item.get("topic_description")
            or item.get("solicitation_description")
            or item.get("description")
            or ""
        ).strip()

        external_id = str(item.get("solicitation_id") or item.get("topic_id") or name)

        opportunities.append(Opportunity(
            external_key=f"sbir_gov:{external_id}",
            raw_document_path=raw_document_path,
            source=SOURCE,
            name=name,
            objective=objective or "See listing for full description.",
            open_date=_parse_date(item.get("open_date") or item.get("solicitation_open_date")),
            close_date=_parse_date(item.get("close_date") or item.get("solicitation_close_date")),
            application_url=item.get("sbir_solicitation_link") or "https://www.dodsbirsttr.mil/topics-app/",
            notes="Auto-matched by scan -- fit level not yet manually reviewed.",
            products=keyword_matches(full_blob),
            fit_level=match_tier(full_blob),
        ))
    return opportunities
