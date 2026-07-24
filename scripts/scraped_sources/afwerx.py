"""AFWERX (Air Force innovation). No public API -- scraped."""
from scraped_sources.common import scrape

SOURCE = "afwerx"
URL = "https://afwerx.com/challenges/"


def run():
    return scrape(SOURCE, URL)
