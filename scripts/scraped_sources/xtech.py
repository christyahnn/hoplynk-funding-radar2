"""xTech (Army innovation competitions). No public API -- scraped."""
from scraped_sources.common import scrape

SOURCE = "xtech"
URL = "https://xtech.army.mil/competitions/"


def run():
    return scrape(SOURCE, URL)
