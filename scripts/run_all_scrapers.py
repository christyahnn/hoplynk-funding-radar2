#!/usr/bin/env python3
"""
Runs every source -- API-based and scraped -- end to end, then merges and
prunes into the final data/opportunities.json.

Run locally:
    pip install -r requirements.txt
    playwright install chromium   # only needed for the Playwright fallback
    export SAM_API_KEY="..."      # optional -- SAM.gov skipped without it
    python run_all_scrapers.py
"""

from __future__ import annotations

import sys
import traceback

import file_store
from api_sources import grants_gov, sam_gov, sbir_gov
from scraped_sources import afwerx, diu, gocolosseum, spacewerx, xtech


def run_api_source(source_name: str, module) -> tuple[int, int]:
    print(f"\n=== {source_name} (API) ===")
    try:
        raw_fetches = module.fetch()
    except Exception as e:
        print(f"[{source_name}] fetch() raised: {e}", file=sys.stderr)
        traceback.print_exc()
        return (0, 0)

    if not raw_fetches:
        print(f"[{source_name}] no documents fetched (disabled or empty)")
        return (0, 0)

    all_opportunities = []
    for raw in raw_fetches:
        raw_path = file_store.stage_raw_document(
            source=module.SOURCE, raw_content=raw["raw_content"], source_url=raw["source_url"],
            fetch_method=raw["fetch_method"], content_type=raw["content_type"],
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


def run_scraped_source(source_name: str, module) -> tuple[int, int]:
    print(f"\n=== {source_name} (scraped) ===")
    try:
        raw_fetches, opportunities = module.run()
    except Exception as e:
        print(f"[{source_name}] run() raised: {e}", file=sys.stderr)
        traceback.print_exc()
        return (0, 0)

    if not raw_fetches:
        print(f"[{source_name}] fetch failed entirely (both static and Playwright) -- nothing staged")
        return (0, 0)

    # Stage every raw fetch attempt (static, and playwright if it ran), and
    # point every found opportunity at whichever fetch actually produced
    # results (the last one in the list -- static if it worked, playwright
    # if it was needed).
    raw_paths = []
    for raw in raw_fetches:
        raw_path = file_store.stage_raw_document(
            source=module.SOURCE, raw_content=raw["raw_content"], source_url=raw["source_url"],
            fetch_method=raw["fetch_method"], content_type=raw["content_type"],
            external_id=raw.get("external_id"),
        )
        raw_paths.append(raw_path)

    if opportunities and raw_paths:
        for opp in opportunities:
            opp.raw_document_path = raw_paths[-1]

    file_store.write_normalized(module.SOURCE, [o.to_dashboard_dict() for o in opportunities])
    print(f"[{source_name}] {len(raw_paths)} raw fetch(es) staged -> {len(opportunities)} relevant opportunit{'y' if len(opportunities)==1 else 'ies'}")
    return (len(raw_paths), len(opportunities))


def main():
    summary = {}
    summary["Grants.gov"] = run_api_source("Grants.gov", grants_gov)
    summary["SBIR.gov"] = run_api_source("SBIR.gov", sbir_gov)
    summary["SAM.gov"] = run_api_source("SAM.gov", sam_gov)
    summary["xTech"] = run_scraped_source("xTech", xtech)
    summary["DIU"] = run_scraped_source("DIU", diu)
    summary["AFWERX"] = run_scraped_source("AFWERX", afwerx)
    summary["SpaceWERX"] = run_scraped_source("SpaceWERX", spacewerx)
    summary["GoColosseum"] = run_scraped_source("GoColosseum", gocolosseum)

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
