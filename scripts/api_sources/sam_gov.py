"""
SAM.gov Opportunities API v2 scraper (GitHub-only build).

Endpoint: https://api.sam.gov/opportunities/v2/search
Requires a free API key: https://sam.gov/data-services/ -- set SAM_API_KEY
as a GitHub Actions repo secret. Silently skipped if unset.

Runs one query per term in SEARCH_TERMS (SAM.gov's title search is
substring-only, not full-text OR) and dedupes naturally since each query's
raw response is staged and parsed separately, then merged by externalKey.
"""

from __future__ import annotations

import os
import json
import sys
from datetime import datetime, date
from pathlib import Path
from typing import Optional

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from matching import flatten_strings, is_relevant, keyword_matches, match_tier
from models import Opportunity

SOURCE = "sam_gov"
API_URL = "https://api.sam.gov/opportunities/v2/search"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; HoplynkFundingRadar/2.0)"}

SEARCH_TERMS = [
    "network", "communications", "resilient", "autonomous",
    "unmanned", "zero trust", "mesh network",
]


def _parse_date(value) -> Optional[date]:
    if not value:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(value)[:10], fmt).date()
        except ValueError:
            continue
    return None


def fetch() -> list[dict]:
    api_key = os.environ.get("SAM_API_KEY")
    if not api_key:
        print("[sam_gov] SAM_API_KEY not set, skipping", file=sys.stderr)
        return []

    today = datetime.now().strftime("%m/%d/%Y")
    year_start = datetime.now().strftime("01/01/%Y")

    results = []
    for term in SEARCH_TERMS:
        try:
            resp = httpx.get(
                API_URL,
                params={
                    "api_key": api_key, "postedFrom": year_start, "postedTo": today,
                    "ptype": "o", "limit": 100, "title": term,
                },
                headers=HEADERS, timeout=30,
            )
            resp.raise_for_status()
        except httpx.HTTPError as e:
            print(f"[sam_gov] fetch failed for term '{term}': {e}", file=sys.stderr)
            continue
        results.append({
            "raw_content": resp.text,
            "source_url": str(resp.request.url),
            "fetch_method": "api",
            "content_type": "json",
            "external_id": term,
        })
    return results


def parse(raw_content: str, raw_document_path: str) -> list[Opportunity]:
    data = json.loads(raw_content)
    items = data.get("opportunitiesData", [])

    opportunities = []
    for item in items:
        name = (item.get("title") or "").strip()
        if not name:
            continue

        full_blob = flatten_strings(item)
        if not is_relevant(full_blob):
            continue

        notice_id = item.get("noticeId") or name

        opportunities.append(Opportunity(
            external_key=f"sam_gov:{notice_id}",
            raw_document_path=raw_document_path,
            source=SOURCE,
            name=name,
            objective=(item.get("description") or "Auto-collected lead -- confirm details on SAM.gov.").strip(),
            open_date=_parse_date(item.get("postedDate")),
            close_date=_parse_date(item.get("responseDeadLine")),
            application_url=item.get("uiLink", "https://sam.gov"),
            notes="Picked up by keyword scan; not yet manually reviewed.",
            products=keyword_matches(full_blob),
            fit_level=match_tier(full_blob),
        ))
    return opportunities
