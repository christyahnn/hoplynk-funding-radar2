"""
GoColosseum. No public API -- scraped.

Important caveat: this was originally flagged as a sign-in-required source
(it's in the dashboard's "manual check" list) because real opportunity
details on GoColosseum likely sit behind an account login. This scraper
will only ever see whatever's on the public-facing pages -- if that's just
marketing content with no listing, it will legitimately find zero results
every run, which is expected, not a bug. Kept in the dashboard's manual
sources list as a fallback for exactly this reason. If GoColosseum does
expose a public listing page, update URL below to point at it directly.
"""
from scraped_sources.common import scrape

SOURCE = "gocolosseum"
URL = "https://gocolosseum.com/"


def run():
    return scrape(SOURCE, URL)
