#!/usr/bin/env python3
"""
Runs every API-based source end to end, GitHub-only build:

  1. fetch()          -- hit the live API (possibly multiple queries)
  2. stage_raw        -- write the exact raw response to data/raw/<source>/<hash>.json
  3. parse()           -- turn it into normalized Opportunity records
  4. write_normalized  -- overwrite data/normalized/<source>.json for this source
  5. merge_and_prune   -- combine all sources + manual overrides, drop anything
                          closed >7 days ago, write data/opportunities.json

Run locally:
    pip install httpx pydantic
    export SAM_API_KEY="..."   # optional -- SAM.gov skipped without it
    python scripts/run_api_scrapers.py

In CI, see .github/workflows/scan.yml.
"""

from __future__ import annotations

import sys
import traceback

import file_store
from api_sources import grants_gov, sam_gov, sbir_gov


def run_source(source_name: str, module) -> tuple[int, int]:
    print(f"\n=== {source_name} ===")
    try:
        raw_fetches = module.fetch()
    except Exception as e:
        print(f"[{source_name}] fetch() raised: {e}", file=sys.stderr)
        traceback.print_exc()
        return (0, 0)

    if not raw_fetches:
        print(f"[{source_name}] no documents fetched (source may be disabled, e.g. missing API key)")
        return (0, 0)

    all_opportunities = []
    for raw in raw_fetches:
        raw_path = file_store.stage_raw_document(
            source=module.SOURCE,
            raw_content=raw["raw_content"],
            source_url=raw["source_url"],
            fetch_method=raw["fetch_method"],
            content_type=raw["content_type"],
            external_id=raw.get("external_id"),
        )
        try:
            opportunities = module.parse(raw["raw_content"], raw_path)
        except Exception as e:
            print(f"[{source_name}] parse() failed for {raw_path}: {e}", file=sys.stderr)
            traceback.print_exc()
            continue
        all_opportunities.extend(opportunities)
        print(f"[{source_name}] staged {raw_path} -> {len(opportunities)} relevant opportunit{'y' if len(opportunities)==1 else 'ies'}")

    file_store.write_normalized(module.SOURCE, [o.to_dashboard_dict() for o in all_opportunities])
    return (len(raw_fetches), len(all_opportunities))


def main():
    summary = {}
    summary["Grants.gov"] = run_source("Grants.gov", grants_gov)
    summary["SBIR.gov"] = run_source("SBIR.gov", sbir_gov)
    summary["SAM.gov"] = run_source("SAM.gov", sam_gov)

    merge_summary = file_store.merge_and_prune()

    print("\n=== Summary ===")
    for source, (docs, opps) in summary.items():
        print(f"  {source}: {docs} raw fetch(es) staged, {opps} opportunity record(s) found")
    print(f"  Per-source normalized counts: {merge_summary['per_source_counts']}")
    print(f"  Total before prune: {merge_summary['total_before_prune']}")
    print(f"  Manual overrides applied: {merge_summary['overrides_applied']}")
    print(f"  Archived/expired (excluded from live output): {merge_summary['archived_or_expired']}")
    print(f"  Final opportunities.json count: {merge_summary['kept']}")


if __name__ == "__main__":
    main()
