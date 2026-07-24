"""
SpaceWERX (Space Force innovation, sibling of AFWERX). No public API --
scraped.

URL is a best guess (spacewerx.us's main site) -- I was not able to confirm
the exact opportunities/topics listing path from the build environment (no
network access). Check the live site the first time this runs and adjust
URL below if it 404s or the listing lives at a different path.
"""
from scraped_sources.common import scrape

SOURCE = "spacewerx"
URL = "https://spacewerx.us/"


def run():
    return scrape(SOURCE, URL)
