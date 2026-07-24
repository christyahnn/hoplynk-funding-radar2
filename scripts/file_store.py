"""
File-based storage layer for the GitHub-only build of Hoplynk Funding Radar.

Three kinds of files, three different write-owners, by design -- this is
what makes it safe for a scheduled bot and a human to both touch this repo
without constant merge conflicts:

  data/raw/<source>/<hash>.json   -- written ONLY by scrapers. Exact,
      unmodified API responses / HTML snapshots. Deduped by content hash,
      so re-scraping unchanged content is a no-op, not repo bloat.

  data/normalized/<source>.json   -- written ONLY by parsers (one file per
      source). Structured opportunity records, auto-generated every run.

  data/manual-overrides.json      -- written ONLY by a human, ONLY ever
      by hand in an editor. Keyed by externalKey. The merge step applies
      these on top of normalized data, so curation (bumping fitLevel to
      High, adding notes, correcting product tags) survives forever, no
      matter how many times the scrapers re-run.

  data/opportunities.json         -- auto-generated output of merge_and_prune.py.
      This is what index.html actually reads. Never hand-edit this one --
      edits belong in manual-overrides.json instead, or they'll be
      overwritten on the next merge.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
NORMALIZED_DIR = DATA_DIR / "normalized"
OVERRIDES_FILE = DATA_DIR / "manual-overrides.json"
MERGED_FILE = DATA_DIR / "opportunities.json"

GRACE_PERIOD_DAYS = 0  # kept as a named constant (rather than a bare 0 inline)
# so it's obvious this was a deliberate choice: only active/open opportunities
# should show, closed means gone the same day it closes, no lingering window.


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def stage_raw_document(
    source: str,
    raw_content: str,
    source_url: str,
    fetch_method: str,
    content_type: str,
    external_id: Optional[str] = None,
) -> str:
    """Write a raw scrape/API response to data/raw/<source>/<hash>.json.
    If byte-identical content was already staged for this source, this is a
    no-op that just returns the existing path -- re-running a scraper
    against unchanged content never creates a duplicate file."""
    source_dir = RAW_DIR / source
    source_dir.mkdir(parents=True, exist_ok=True)
    h = _content_hash(raw_content)
    path = source_dir / f"{h}.json"
    rel_path = str(path.relative_to(ROOT))
    if path.exists():
        return rel_path

    payload = {
        "source": source,
        "fetch_method": fetch_method,
        "source_url": source_url,
        "external_id": external_id,
        "content_type": content_type,
        "raw_content": raw_content,
        "fetched_at": datetime.utcnow().isoformat() + "Z",
    }
    path.write_text(json.dumps(payload, indent=2))
    return rel_path


def write_normalized(source: str, opportunities: list[dict]) -> None:
    """Overwrite data/normalized/<source>.json with this run's results,
    merged against whatever was already there so a temporary empty/partial
    scrape doesn't wipe out previously-found opportunities, and so
    firstSeen dates are preserved rather than reset every run."""
    NORMALIZED_DIR.mkdir(parents=True, exist_ok=True)
    path = NORMALIZED_DIR / f"{source}.json"

    existing_by_key = {}
    if path.exists():
        existing_by_key = {o["externalKey"]: o for o in json.loads(path.read_text())}

    merged_by_key = dict(existing_by_key)  # start from what was already there
    for opp in opportunities:
        key = opp["externalKey"]
        prior = existing_by_key.get(key)
        if prior:
            opp["firstSeen"] = prior.get("firstSeen", opp["firstSeen"])
        merged_by_key[key] = opp

    path.write_text(json.dumps(list(merged_by_key.values()), indent=2, default=str))


def load_overrides() -> dict:
    if not OVERRIDES_FILE.exists():
        return {}
    return json.loads(OVERRIDES_FILE.read_text())


def merge_and_prune() -> dict:
    """Read every data/normalized/*.json file, apply manual-overrides.json
    on top, drop anything that's already closed (GRACE_PERIOD_DAYS=0 means
    no lingering window -- only active/open opportunities make it into the
    live output), and write the final data/opportunities.json the dashboard
    reads. Returns a small summary dict for logging."""
    overrides = load_overrides()
    today = date.today()
    cutoff = today - timedelta(days=GRACE_PERIOD_DAYS)

    all_opps = []
    per_source_counts = {}
    if NORMALIZED_DIR.exists():
        for source_file in sorted(NORMALIZED_DIR.glob("*.json")):
            items = json.loads(source_file.read_text())
            per_source_counts[source_file.stem] = len(items)
            all_opps.extend(items)

    kept, archived, overridden = [], 0, 0
    for opp in all_opps:
        key = opp.get("externalKey")
        if key in overrides:
            opp = {**opp, **overrides[key]}
            overridden += 1

        if opp.get("archived"):
            archived += 1
            continue

        close_date_str = opp.get("closeDate")
        if close_date_str:
            try:
                close_date = datetime.fromisoformat(close_date_str[:10]).date()
                if close_date < cutoff:
                    archived += 1
                    continue
            except ValueError:
                pass  # unparseable date -- keep rather than silently drop

        kept.append(opp)

    output = {"lastScan": datetime.utcnow().isoformat() + "Z", "opportunities": kept}
    MERGED_FILE.write_text(json.dumps(output, indent=2, default=str))

    return {
        "per_source_counts": per_source_counts,
        "total_before_prune": len(all_opps),
        "kept": len(kept),
        "archived_or_expired": archived,
        "overrides_applied": overridden,
    }
