"""
Shared scraping logic for sources with no public API: xTech, DIU, AFWERX,
SpaceWERX, GoColosseum.

Strategy per source, per the original spec:
  1. Try a static fetch (httpx) + parse (BeautifulSoup).
  2. If that finds zero candidate opportunities, fall back to a
     Playwright-rendered fetch (handles JS-rendered listing pages) and
     parse again.
  3. Every raw HTML fetched -- static attempt AND playwright fallback, if
     it ran -- gets staged as-is. Nothing is thrown away, so if a source
     goes quiet, the raw staged HTML tells you whether the fetch itself
     failed or the fetch succeeded but nothing matched.

Filtering is intentionally strict about what counts as a real opportunity
vs. site navigation -- this pipeline already burned a real bug on "Skip to
content" and "Careers At DIU" showing up as fake opportunities, so the
blocklist here is deliberately aggressive.
"""

from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from matching import all_matched_terms, is_relevant, keyword_matches, match_tier
from models import Opportunity

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; HoplynkFundingRadar/2.0)"}

# Same fixed-string boilerplate list as the v1 dashboard scanner.
BOILERPLATE_LINK_TEXT = {
    "skip to content", "skip to main content", "skip to navigation",
    "skip navigation", "skip to footer", "back to top", "home",
    "menu", "search", "login", "log in", "sign in", "contact",
    "contact us", "about", "about us", "privacy policy", "privacy",
    "terms of use", "terms of service", "accessibility",
    "accessibility statement", "sitemap", "site map", "careers",
    "newsletter", "subscribe", "facebook", "twitter", "linkedin",
    "instagram", "youtube", "read more", "learn more", "next", "previous",
    "close", "faq", "faqs", "help", "cookie policy", "cookies",
}

# Pattern-based blocklist -- catches nav/site-structure phrasing a fixed
# string set can't, e.g. "Careers At DIU" or "5 Open Pathways".
NAV_PATTERN_BLOCKLIST = [
    r"\bcareers?\b", r"\bterms\b.*\bconditions\b", r"\bprivacy\b",
    r"\bsubmit your solution\b", r"\bpathways?\b", r"\bfor (commercial|government|industry)\b",
    r"\b(dow|dod) entities\b", r"\bcommercial companies\b", r"\babout\b",
    r"\bour (team|mission|approach|story|history)\b", r"\bleadership\b",
    r"\bwho we are\b", r"\bget involved\b", r"\bnewsletter\b", r"\bsign ?up\b",
    r"\bsite ?map\b", r"\bnews\b", r"\bevents?\b", r"\bblog\b", r"\bpress\b",
    r"\bwork with us\b", r"\bpartners?\b", r"\bpress release", r"\bfaq",
    r"\bhow (it|to) works?\b", r"\boverview\b$", r"\bhome\b",
]


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:80]


def _matches_nav_pattern(title: str) -> bool:
    title_l = title.lower()
    return any(re.search(p, title_l) for p in NAV_PATTERN_BLOCKLIST)


def _is_boilerplate_link(title: str, href: str) -> bool:
    normalized = re.sub(r"[^a-z0-9 ]", "", title.lower()).strip()
    if normalized in BOILERPLATE_LINK_TEXT:
        return True
    if href.strip().startswith("#"):
        return True
    if len(normalized) < 12:
        return True
    if len(normalized.split()) < 3:
        return True
    if _matches_nav_pattern(title):
        return True
    return False


def fetch_static(url: str) -> str:
    resp = httpx.get(url, headers=HEADERS, timeout=30, follow_redirects=True)
    resp.raise_for_status()
    return resp.text


def fetch_playwright(url: str, wait_ms: int = 3000) -> str:
    """Renders the page with a real headless browser -- for listing pages
    that build their content with JS after initial load, where a static
    fetch sees an empty shell. Requires `playwright install chromium` to
    have been run (see requirements.txt / the workflow's install step)."""
    from playwright.sync_api import sync_playwright  # imported lazily so a
    # missing Playwright install only breaks the fallback path, not every
    # source that happens to not need it.

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(user_agent=HEADERS["User-Agent"])
            page.goto(url, timeout=30000, wait_until="networkidle")
            page.wait_for_timeout(wait_ms)
            return page.content()
        finally:
            browser.close()


def extract_opportunities(
    html: str,
    base_url: str,
    source: str,
    raw_document_path: Optional[str] = None,
    required_url_pattern: Optional[str] = None,
    link_selector: str = "a",
) -> list[Opportunity]:
    """Parse a page's HTML and return only links that look like real
    opportunity postings. Relevance is checked against the link's own title
    text plus a narrow, immediately-adjacent description (not the whole
    surrounding page block, which is what caused the original nav-link
    false positives)."""
    soup = BeautifulSoup(html, "html.parser")
def _extract_detail_text(html: str) -> str:
    """Pull real body text out of an opportunity's own detail page -- not
    the listing page. Strips nav/header/footer/script/style, prefers a
    <main>/<article> container if present, and keeps only paragraphs long
    enough to plausibly be real description text (skips short boilerplate
    lines like button labels that sometimes come through as <p> tags)."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer", "form"]):
        tag.decompose()
    container = soup.find("main") or soup.find("article") or soup.find(attrs={"role": "main"}) or soup.body or soup
    paragraphs = [p.get_text(" ", strip=True) for p in container.find_all("p")]
    paragraphs = [p for p in paragraphs if len(p) > 40]
    return " ".join(paragraphs)[:1500].strip()


def _gather_candidates(html: str, base_url: str, required_url_pattern: Optional[str]) -> list[dict]:
    """Stage 1: pull links off the listing page that survive nav-filtering
    and show at least a loose keyword signal in the listing snippet alone.
    Deliberately loose (any single keyword hit, not the strict >=2 relevance
    bar) -- this list only decides which pages are worth the extra network
    call to go fetch their real detail page; the strict relevance check
    happens in stage 2 against the fuller text."""
    soup = BeautifulSoup(html, "html.parser")
    seen_titles = set()
    candidates = []

    for link in soup.select("a"):
        title = link.get_text(strip=True)
        href = link.get("href")
        if not title or not href:
            continue
        if _is_boilerplate_link(title, href):
            continue
        if title in seen_titles:
            continue
        if href.startswith("/"):
            href = urljoin(base_url, href)
        if required_url_pattern and not re.search(required_url_pattern, href):
            continue

        listing_snippet = ""
        immediate_parent = link.find_parent(["li", "article"])
        if immediate_parent:
            p_tag = immediate_parent.find("p")
            if p_tag and p_tag not in link.find_parents():
                listing_snippet = p_tag.get_text(" ", strip=True)
        attr_text = " ".join(filter(None, [link.get("title"), link.get("aria-label")]))
        loose_text = f"{title} {listing_snippet} {attr_text}"

        if not all_matched_terms(loose_text):  # zero keyword hits at all -- not worth a detail-page fetch
            continue

        seen_titles.add(title)
        candidates.append({"title": title, "href": href, "listing_snippet": listing_snippet})
    return candidates


def extract_opportunities(
    html: str,
    base_url: str,
    source: str,
    raw_document_path: Optional[str] = None,
    required_url_pattern: Optional[str] = None,
) -> tuple[list[Opportunity], list[dict]]:
    """Two-stage extraction. Stage 1 (_gather_candidates) finds links worth
    a second look from the listing page alone. Stage 2 fetches each
    candidate's own detail page for its real description, and only then
    applies the strict is_relevant() bar against title+real-description
    combined -- both because that's a better relevance signal than the thin
    listing snippet, and because the detail page is where an actual
    objective/description worth showing on the dashboard lives.

    Returns (opportunities, detail_page_raw_fetches) -- the caller is
    responsible for staging detail_page_raw_fetches, same as the listing
    page's own raw fetch."""
    candidates = _gather_candidates(html, base_url, required_url_pattern)
    opportunities = []
    detail_raw_fetches = []

    for candidate in candidates:
        detail_text = ""
        try:
            detail_html = fetch_static(candidate["href"])
            detail_raw_fetches.append({
                "raw_content": detail_html, "source_url": candidate["href"],
                "fetch_method": "static_scrape", "content_type": "html",
                "external_id": None,
            })
            detail_text = _extract_detail_text(detail_html)
        except Exception as e:
            print(f"[{source}] detail-page fetch failed for {candidate['href']}: {e}", file=sys.stderr)

        # Fall back to the listing snippet if the detail page fetch failed
        # or came back too thin to be useful.
        objective = detail_text if len(detail_text) > 40 else candidate["listing_snippet"]
        match_text = f"{candidate['title']} {objective}"

        if not is_relevant(match_text):
            continue

        opportunities.append(Opportunity(
            external_key=f"{source}:{_slugify(candidate['title'])}",
            raw_document_path=raw_document_path,
            source=source,
            name=candidate["title"],
            objective=objective or "Auto-collected lead -- confirm details on the source page.",
            application_url=candidate["href"],
            notes="Picked up by keyword scan; not yet manually reviewed.",
            products=keyword_matches(match_text),
            fit_level=match_tier(match_text),
        ))

    return opportunities, detail_raw_fetches


def scrape(source: str, url: str, required_url_pattern: Optional[str] = None) -> tuple[list[dict], list[Opportunity]]:
    """Full pipeline for one source: static fetch -> parse; if that finds
    nothing, Playwright fetch -> parse. Returns (raw_fetch_records,
    opportunities) -- raw_fetch_records is a list because both attempts
    (static + playwright, if the fallback ran) get staged."""
    raw_fetches = []
    opportunities: list[Opportunity] = []

    try:
        html = fetch_static(url)
        raw_fetches.append({
            "raw_content": html, "source_url": url,
            "fetch_method": "static_scrape", "content_type": "html", "external_id": None,
        })
        opportunities, detail_raw_fetches = extract_opportunities(html, url, source, required_url_pattern=required_url_pattern)
        raw_fetches.extend(detail_raw_fetches)
    except Exception as e:
        print(f"[{source}] static fetch failed: {e}", file=sys.stderr)

    if not opportunities:
        print(f"[{source}] static scrape found nothing -- trying Playwright fallback")
        try:
            html = fetch_playwright(url)
            raw_fetches.append({
                "raw_content": html, "source_url": url,
                "fetch_method": "playwright", "content_type": "html", "external_id": None,
            })
            opportunities, detail_raw_fetches = extract_opportunities(html, url, source, required_url_pattern=required_url_pattern)
            raw_fetches.extend(detail_raw_fetches)
        except ImportError:
            print(f"[{source}] playwright not installed, skipping dynamic fallback", file=sys.stderr)
        except Exception as e:
            print(f"[{source}] playwright fetch failed: {e}", file=sys.stderr)

    return raw_fetches, opportunities
