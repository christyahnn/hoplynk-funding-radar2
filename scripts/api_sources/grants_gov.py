"""
Grants.gov Search2 API scraper (GitHub-only build).

Endpoint: https://api.grants.gov/v1/api/search2 (POST, JSON body)
Docs: https://grants.gov/api

Not verified against a live call from the build environment -- confirm
field names (especially the data.oppHits path) against a real response the
first time this runs, and adjust if Grants.gov's schema differs.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, date
from pathlib import Path
from typing import Optional

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from matching import flatten_strings, is_relevant, keyword_matches, match_tier
from models import Opportunity

SOURCE = "grants_gov"
API_URL = "https://api.grants.gov/v1/api/search2"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; HoplynkFundingRadar/2.0)", "Content-Type": "application/json"}

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
    results = []
    for term in SEARCH_TERMS:
        body = {"keyword": term, "rows": 100, "oppStatuses": "forecasted|posted"}
        try:
            resp = httpx.post(API_URL, json=body, headers=HEADERS, timeout=30)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            print(f"[grants_gov] fetch failed for term '{term}': {e}", file=sys.stderr)
            continue
        results.append({
            "raw_content": resp.text,
            "source_url": f"{API_URL}?keyword={term}",
            "fetch_method": "api",
            "content_type": "json",
            "external_id": term,
        })
    return results


def parse(raw_content: str, raw_document_path: str) -> list[Opportunity]:
    data = json.loads(raw_content)
    items = data.get("data", {}).get("oppHits", []) or data.get("oppHits", [])

    opportunities = []
    for item in items:
        name = (item.get("title") or "").strip()
        if not name:
            continue

        full_blob = flatten_strings(item)
        if not is_relevant(full_blob):
            continue

        opp_id = item.get("id") or item.get("number") or name

        opportunities.append(Opportunity(
            external_key=f"grants_gov:{opp_id}",
            raw_document_path=raw_document_path,
            source=SOURCE,
            name=name,
            objective=(item.get("description") or "Auto-collected lead -- confirm details on Grants.gov.").strip(),
            open_date=_parse_date(item.get("openDate") or item.get("postedDate")),
            close_date=_parse_date(item.get("closeDate") or item.get("responseDate")),
            application_url=f"https://www.grants.gov/search-results-detail/{opp_id}",
            notes="Picked up by keyword scan; not yet manually reviewed.",
            products=keyword_matches(full_blob),
            fit_level=match_tier(full_blob),
        ))
    return opportunities
