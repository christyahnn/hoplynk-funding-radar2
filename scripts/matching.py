"""
Hoplynk product-fit matching.

Ported from the v1 static-site scanner. Three tiers:
  - PRODUCT_KEYWORDS: a direct hit on what HAVEN/Argus/Hydra/GoLynk actually do
  - GENERAL_KEYWORDS: close-but-not-product-specific networking/defense-tech terms
  - ADJACENT_KEYWORDS: broader defense-tech terms worth a human glance, tagged
    as a lower-confidence "Review (broad match)" so it's visually distinct
    from a tighter match on the dashboard/search UI.

This module is intentionally free of any I/O (no requests, no DB) so it can
be unit tested in isolation and reused identically by every source's parser,
whether that source is an API or a scraped page.
"""

from __future__ import annotations

PRODUCT_KEYWORDS: dict[str, list[str]] = {
    "HAVEN": [
        "multi-transport", "transport aggregation", "network aggregat",
        "contested environment", "denied environment", "disconnected",
        "intermittent", "limited bandwidth", "dil", "mesh network",
        "satcom", "satellite communications", "rf communications",
        "resilient communications", "resilient network", "edge network",
        "tactical data link", "beyond line of sight", "line of sight comms",
    ],
    "Argus": [
        "fleet management", "fleet control", "control plane",
        "device management", "node management", "telemetry",
        "situational awareness", "network monitoring", "sensor tasking",
        "resource allocation", "swarm coordination", "swarm management",
    ],
    "Hydra": [
        "autonomous network", "policy-driven", "self-healing network",
        "software defined network", "sdn", "zero trust", "ai-native",
        "network automation", "autonomous policy", "network execution",
        "decentralized control", "adaptive routing",
    ],
    "GoLynk": [
        "rapid deploy", "rapid deployment", "expeditionary",
        "quick deploy", "commercial networking", "field deployable",
        "portable network", "man-packable",
    ],
}

GENERAL_KEYWORDS: list[str] = [
    "network", "networking", "connectivity", "communications", "comms",
    "drone", "uas", "unmanned", "radar", "sensor fusion", "command and control",
    "c2", "c4isr", "multi-domain", "autonomous", "ai agent", "artificial intelligence",
    "resilient", "resilience", "edge computing", "wireless", "data link",
    "situational awareness", "battle management", "mesh", "spectrum",
]

ADJACENT_KEYWORDS: list[str] = [
    "artificial intelligence", "machine learning", "ai/ml", "robotics",
    "autonomy", "isr", "intelligence surveillance reconnaissance",
    "electronic warfare", "cyber", "cybersecurity", "space", "satellite",
    "gps", "pnt", "positioning navigation and timing", "logistics",
    "digital engineering", "cloud", "data fusion", "swarm", "tactical",
    "expeditionary", "contested logistics", "joint all-domain",
    "jadc2", "dual-use", "prototype", "rapid prototyping",
    "unmanned systems", "counter-uas", "cuas", "sensor", "sensors",
]


def flatten_strings(obj, max_depth: int = 4) -> str:
    """Recursively pull every string value out of a JSON-like structure."""
    if max_depth <= 0:
        return ""
    if isinstance(obj, str):
        return obj
    if isinstance(obj, dict):
        return " ".join(flatten_strings(v, max_depth - 1) for v in obj.values())
    if isinstance(obj, list):
        return " ".join(flatten_strings(v, max_depth - 1) for v in obj)
    return ""


def keyword_matches(text: str) -> list[str]:
    """Return the list of Hoplynk products a piece of text seems relevant to."""
    text_l = text.lower()
    return [product for product, kws in PRODUCT_KEYWORDS.items() if any(kw in text_l for kw in kws)]


def all_matched_terms(text: str) -> set[str]:
    """Every distinct keyword (across product/general/adjacent tiers) found
    in the text. Used to require multiple corroborating signals rather than
    letting one stray term (e.g. a single mention of "cyber" in an
    otherwise-unrelated posting) count as relevant on its own."""
    text_l = text.lower()
    hits = set()
    for kws in PRODUCT_KEYWORDS.values():
        hits.update(kw for kw in kws if kw in text_l)
    hits.update(kw for kw in GENERAL_KEYWORDS if kw in text_l)
    hits.update(kw for kw in ADJACENT_KEYWORDS if kw in text_l)
    return hits


MIN_KEYWORD_HITS = 2  # require at least this many distinct terms total


def is_relevant(text: str) -> bool:
    """A posting counts as relevant only if BOTH:
      1. it hits at least one PRODUCT_KEYWORDS term -- something that
         actually describes what HAVEN/Argus/Hydra/GoLynk does, not just
         generic defense-tech language, and
      2. it hits at least MIN_KEYWORD_HITS distinct terms total (product +
         general + adjacent combined).

    Generic buzzwords alone (e.g. "resilient" + "autonomous" with no actual
    product-specific term) are no longer sufficient by themselves -- that
    was letting in postings only loosely connected to what Hoplynk
    actually builds. This is the main lever to pull if the dashboard is
    still surfacing too many/too few results: loosen by removing the
    keyword_matches(text) requirement below, or tighten by raising
    MIN_KEYWORD_HITS."""
    if not keyword_matches(text):
        return False
    return len(all_matched_terms(text)) >= MIN_KEYWORD_HITS


def match_tier(text: str) -> str:
    """Always 'Review' for anything that passes is_relevant() now, since
    that already guarantees a direct product-keyword hit -- there's no
    weaker "broad match" tier being assigned by the automated scan anymore.
    Manual/curated entries use 'High'/'Adjacent' directly in
    data/normalized/manual.json and never go through this function."""
    return "Review"
