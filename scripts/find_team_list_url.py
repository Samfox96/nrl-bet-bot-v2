"""
find_team_list_url.py
=======================
Solves two problems at once by parsing nrl.com's team-lists topic listing
page (https://www.nrl.com/news/topic/team-lists/):

  1. URL discovery: this page lists "NRL Team Lists: Round N" articles with
     their real, dated URLs right in the link text/href -- no need to guess
     a publish date to construct the URL ourselves.
  2. Round detection: the most recent "NRL Team Lists: Round N" entry (NOT
     "Late Mail", which is a separate, more frequent article type for the
     same round) tells us which round currently has a published team list,
     which is exactly the round Job B should be polling for.

Confirmed via a real fetch (2026-06-22) that this page is server-rendered
plain HTML/links -- no JavaScript-gated "no data" problem like the draw
page has for future rounds. This is the more reliable discovery path of
the two pages tested.

Deliberately ignores "Late Mail" entries for the purpose of URL discovery,
since testing (Sam's screenshots) showed Late Mail and Team Lists are
DIFFERENT articles for the same round, and only the "Team Lists: Round N"
one was confirmed to carry the full per-match, per-position roster data
this project parses. Late Mail articles may be worth a separate look later,
but are out of scope for this pass -- not yet tested.
"""

import re

TEAM_LIST_LINK_PATTERN = re.compile(
    r"NRL Team Lists: Round (?P<round>\d+).*?\]\((?P<url>https://www\.nrl\.com/news/[^\)]+)\)"
)


def find_latest_team_list_url(listing_page_text):
    """
    Returns (round_num, url) for the most recent "NRL Team Lists: Round N"
    entry found on the topic listing page, or None if no match is found.

    Listing pages show newest-first, so the FIRST match in the text is the
    most recent round with a published team list.
    """
    matches = TEAM_LIST_LINK_PATTERN.finditer(listing_page_text)
    for m in matches:
        return int(m.group("round")), m.group("url")
    return None


def find_all_team_list_urls(listing_page_text):
    """
    Returns all (round_num, url) pairs found, newest first -- useful for
    backfilling or sanity-checking against several recent rounds at once,
    not just the latest.
    """
    return [
        (int(m.group("round")), m.group("url"))
        for m in TEAM_LIST_LINK_PATTERN.finditer(listing_page_text)
    ]


if __name__ == "__main__":
    with open("sample_topic_listing.txt") as f:
        text = f.read()

    print("Testing against real listing page sample (fetched 2026-06-22):\n")

    latest = find_latest_team_list_url(text)
    print(f"Latest team list found: Round {latest[0]} -> {latest[1]}")
    expected = (16, "https://www.nrl.com/news/2026/06/16/nrl-team-lists-round-16/")
    assert latest == expected, f"MISMATCH: got {latest}, expected {expected}"
    print("  PASS -- matches expected Round 16 URL")

    all_found = find_all_team_list_urls(text)
    print(f"\nAll team-list URLs found ({len(all_found)}):")
    for round_num, url in all_found:
        print(f"  Round {round_num}: {url}")

    # Confirm Late Mail entries are correctly NOT matched as team-list URLs
    late_mail_count = text.count("Late Mail")
    print(f"\n'Late Mail' substring appears {late_mail_count} times in sample, "
          f"but {len(all_found)} team-list URLs were extracted (should be fewer than total links).")
