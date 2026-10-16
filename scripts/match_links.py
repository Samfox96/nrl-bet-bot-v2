"""Which nrl.com draw-page links are individual match pages.

Regular-season match pages look like ".../2026/round-21/knights-v-dragons/".
Finals don't use "round-N": Finals Week 1/2/3 are "finals-week-1/2/3" and the
Grand Final is "grand-final/game-1" (the same segments scrape_match_results.py's
FINALS_ROUND_SEGMENTS uses). Without the finals markers the player-stats
scraper sees zero matches for rounds 28-31.
"""

FINALS_URL_MARKERS = ("/finals-week-", "/grand-final")


def is_match_link(href):
    """True if an nrl.com draw-page link is an individual match page (regular season or finals)."""
    if not href:
        return False
    if "/round-" in href:
        return True
    if not any(m in href for m in FINALS_URL_MARKERS):
        return False
    last = href.split("#")[0].rstrip("/").split("/")[-1]
    # A match page ends in "team-v-team", or (Grand Final) in "game-1".
    return "-v-" in last or last.startswith("game-")
