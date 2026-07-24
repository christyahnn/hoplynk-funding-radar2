"""
Defense Innovation Unit. No public API -- scraped.

required_url_pattern is set based on one confirmed real DIU opportunity URL
from your original PDF (.../work-with-us/submit-solution/PROJ00684) --
restricting to that path shape should cut out a lot of nav noise, but it's
based on a single confirmed example, not documented URL structure. If this
comes back with zero results even after the Playwright fallback, that's the
first thing to loosen -- try removing required_url_pattern entirely and
leaning on the nav blocklist alone, same as the other four sources.
"""
from scraped_sources.common import scrape

SOURCE = "diu"
URL = "https://www.diu.mil/work-with-us/open-solicitations"
REQUIRED_URL_PATTERN = r"/submit-solution/"


def run():
    return scrape(SOURCE, URL, required_url_pattern=REQUIRED_URL_PATTERN)
