"""
find_team_list_url.py
=======================
Solves two problems at once by parsing nrl.com's team-lists topic listing
page (https://www.nrl.com/news/topic/team-lists/):

  1. URL discovery: this page lists "NRL Team Lists: Round N" articles --
     no need to guess a publish date to construct the URL ourselves.
  2. Round detection: the most recent "NRL Team Lists: Round N" entry (NOT
     "Late Mail", a separate, more frequent article type for the same
     round) tells us which round currently has a published team list.

REWRITTEN 2026-06-22 after a real live test (via GitHub Actions, fetching
with plain `requests`) revealed the actual raw HTML structure differs
significantly from the markdown-flattened text `web_fetch` had returned
during earlier development. The real markup looks like:

    <a aria-label="Team Lists Article - NRL Team Lists: Round 16. 7 minute
                    read. Published 5 days ago"
       href="/news/2026/06/16/nrl-team-lists-round-16/">

Two things the original regex-on-flattened-text version got wrong, now
fixed by parsing real HTML with BeautifulSoup instead of regex-on-text:
  - The href is a RELATIVE path ("/news/..."), not a full URL -- now
    resolved against the site's base URL.
  - The round number and the URL live in separate, non-adjacent attributes
    (aria-label vs href), not adjacent text on one line -- BeautifulSoup's
    actual element structure handles this correctly where a flat-text regex
    could not.

This was a genuine bug caught by a real Actions run (status 200, full valid
200KB+ response, but zero matches) -- not a fetch/blocking problem as
initially suspected. The live HTTP fetch itself works fine from GitHub's
IP; only the parser needed fixing.
"""

import re
from bs4 import BeautifulSoup

BASE_URL = "https://www.nrl.com"

# Matches the VISIBLE TITLE inside the aria-label, specifically the
# "NRL Team Lists: Round N" article type -- deliberately excludes
# "NRL Late Mail Round N", which is a different, more frequent article type
# for the same round and does NOT carry full per-position roster data
# (not yet confirmed/tested; out of scope for this parser).
TEAM_LIST_TITLE_PATTERN = re.compile(r"NRL Team Lists: Round (\d+)")


def _find_team_list_links(listing_page_html):
    """
    Returns a list of (round_num, absolute_url) tuples for every genuine
    "NRL Team Lists: Round N" entry found, in page order (which is
    newest-first on this listing page).
    """
    soup = BeautifulSoup(listing_page_html, "html.parser")
    links = soup.find_all("a", attrs={"aria-label": re.compile(r"Team Lists Article")})

    results = []
    for link in links:
        label = link.get("aria-label", "")
        match = TEAM_LIST_TITLE_PATTERN.search(label)
        if not match:
            continue  # this is a Late Mail or other article type, skip
        href = link.get("href", "")
        if not href:
            continue
        absolute_url = href if href.startswith("http") else BASE_URL + href
        results.append((int(match.group(1)), absolute_url))

    return results


def find_latest_team_list_url(listing_page_html):
    """
    Returns (round_num, url) for the most recent "NRL Team Lists: Round N"
    entry, or None if none found. Listing page is newest-first, so this is
    simply the first result.
    """
    results = _find_team_list_links(listing_page_html)
    return results[0] if results else None


def find_all_team_list_urls(listing_page_html):
    """Returns all (round_num, url) pairs found, newest first."""
    return _find_team_list_links(listing_page_html)


if __name__ == "__main__":
    # Self-test against the REAL response captured from a live GitHub Actions
    # run (2026-06-22), not a hand-typed sample -- this is what actually
    # caught the bug this rewrite fixes.
    with open("real_listing_response.html") as f:
        html = f.read()

    print("Testing against REAL live-fetched listing page response:\n")

    latest = find_latest_team_list_url(html)
    print(f"Latest team list found: Round {latest[0]} -> {latest[1]}")
    expected = (16, "https://www.nrl.com/news/2026/06/16/nrl-team-lists-round-16/")
    assert latest == expected, f"MISMATCH: got {latest}, expected {expected}"
    print("  PASS -- matches expected Round 16 URL")

    all_found = find_all_team_list_urls(html)
    print(f"\nAll team-list URLs found ({len(all_found)}):")
    for round_num, url in all_found:
        print(f"  Round {round_num}: {url}")
