"""
scrape_team_lists.py
======================
Job B: scrapes NRL.com's "Team Lists: Round N" article for the current round,
but only does real work when at least one match in the round is within 1
hour of kickoff -- otherwise exits immediately (cheap, frequent polling).

Designed to run hourly Thursday-Sunday via GitHub Actions. Each invocation:
  1. Fetches nrl.com's team-lists topic listing page (plain HTTP, no JS-gating
     issue -- confirmed via real fetch) to find the current round's team-list
     article URL.
  2. Fetches that article (also plain HTTP).
  3. Extracts kickoff times for every match in the round directly from THIS
     SAME page -- the article embeds the same draw-widget link text the draw
     page itself uses (e.g. "Round 16 - Friday 19 Jun 10:00 am ..."), which
     parse_draw_link_text.py already parses correctly, including the UTC ->
     AEST conversion. Confirmed via real test (2026-06-22): all 7 Round 16
     matches' kickoff times extracted correctly from the team-list page text
     alone -- no separate draw-page visit needed.
  4. Parses the same page into structured player rows (parse_team_list.py).
  5. Checks each match's kickoff time against the current time.
  6. If nothing is within the 1-hour pre-kickoff window, exits without writing
     anything -- this is the expected/normal outcome on most hourly runs.
  7. If something IS in-window, overwrites data/team_lists_current.csv with
     the latest full scrape.

DESIGN CHANGE from an earlier version: kickoff times used to come from a
sidecar file Job A was supposed to produce. That created a fragile cross-job
dependency -- Job A only runs Thursdays scraping the round that just
FINISHED, never the round currently being played, so the sidecar file Job B
needed often wouldn't exist yet (confirmed by a real failed test run,
2026-06-22). Job B is now fully self-contained: one HTTP fetch gives it
everything (team list AND kickoff times), no dependency on Job A's timing
or output at all.
"""

import sys
import argparse
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from parse_team_list import parse_team_list_page
from parse_draw_link_text import extract_kickoffs_from_html
from kickoff_time import is_within_n_hours_before


def find_team_list_url(listing_page_text, round_num=None):
    """
    Discovers the team-list article URL using nrl.com's team-lists topic
    listing page (server-rendered, no JS-gating issue -- confirmed via real
    fetch 2026-06-22). See find_team_list_url.py for the underlying parser
    and its test against real listing-page content.

    If round_num is given, returns that specific round's URL if found.
    If round_num is None, returns the latest (most recent) round's URL --
    useful as a fallback "what's the current round" signal, though the
    authoritative round number should still come from nrl_master.csv where
    possible (this listing page reflects publish timing, which could in
    rare cases lag or lead the round nrl_master.csv considers "next").
    """
    from find_team_list_url import find_latest_team_list_url, find_all_team_list_urls

    if round_num is None:
        result = find_latest_team_list_url(listing_page_text)
        return result  # (round_num, url) or None

    for r, url in find_all_team_list_urls(listing_page_text):
        if r == round_num:
            return (r, url)
    return None


def run(round_num, kickoffs, page_text, output_path, now=None, hours_before=1):
    """
    kickoffs: list of dicts with 'home_team', 'away_team', 'kickoff_aest'
    (a datetime), extracted directly from the same team-list page being
    parsed for player rows -- see extract_kickoffs_from_team_list_page().
    """
    now = now or datetime.now()

    if not kickoffs:
        print(f"No kickoff data could be extracted from the round {round_num} "
              f"team-list page. Nothing to do.")
        return False

    in_window_matches = [
        k for k in kickoffs
        if is_within_n_hours_before(k["kickoff_aest"], now, hours=hours_before)
    ]

    if not in_window_matches:
        next_up = min(kickoffs, key=lambda k: abs((k["kickoff_aest"] - now).total_seconds()))
        print(f"No matches within {hours_before}h of kickoff right now ({now}). "
              f"Nearest match: {next_up['home_team']} v {next_up['away_team']} "
              f"at {next_up['kickoff_aest']}. Nothing to do this run.")
        return False

    print(f"{len(in_window_matches)} match(es) within {hours_before}h of kickoff:")
    for k in in_window_matches:
        print(f"  {k['home_team']} v {k['away_team']} -- kickoff {k['kickoff_aest']}")

    rows = parse_team_list_page(page_text, round_num=round_num)
    if not rows:
        print("Team-list page found but zero player rows parsed -- "
              "page structure may have changed. Not writing output.")
        return False

    import csv
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys())
    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} player rows to {output_path}")
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Job B: poll and scrape team lists near kickoff.")
    parser.add_argument("--output", type=str, default="data/team_lists_current.csv")
    parser.add_argument("--hours-before", type=int, default=1)
    args = parser.parse_args()

    # IMPORTANT, NOT YET VERIFIED LIVE: this uses plain `requests` rather than
    # Selenium, since both target pages were confirmed (via real fetch,
    # 2026-06-22) to be server-rendered with no JS-gating. That's true for
    # what was actually fetched and inspected from outside GitHub Actions --
    # but nrl.com may still respond differently to a plain HTTP client from
    # GitHub's IP range specifically. If this fails in practice, the fallback
    # is switching to the same Selenium pattern nrl_update_single_round.py
    # already uses successfully against the (harder, JS-gated) draw page.
    import requests

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    }

    listing_resp = requests.get("https://www.nrl.com/news/topic/team-lists/",
                                  headers=headers, timeout=30)
    listing_resp.raise_for_status()

    discovery = find_team_list_url(listing_resp.text, round_num=None)  # latest published
    if discovery is None:
        print("No team-list article found on the listing page at all. "
              "Page structure may have changed.")
        # Save the raw response for debugging -- without this, a failure here
        # is a black box: no way to tell whether nrl.com served different
        # content to a plain HTTP client than it serves to a real browser,
        # versus the parser regex simply not matching today's exact markup.
        import os
        os.makedirs("debug_output", exist_ok=True)
        with open("debug_output/listing_page_response.html", "w") as f:
            f.write(listing_resp.text)
        print(f"Saved raw response ({len(listing_resp.text)} chars) to "
              f"debug_output/listing_page_response.html for inspection. "
              f"Status code was: {listing_resp.status_code}")
        sys.exit(0)

    round_num, url = discovery
    print(f"Latest published team list: round {round_num} -> {url}")

    page_resp = requests.get(url, headers=headers, timeout=30)
    page_resp.raise_for_status()

    # Always save the raw team-list page response for inspection, regardless
    # of outcome. The listing page already proved real raw HTML can differ
    # significantly from what was tested against during development -- don't
    # repeat that mistake here by assuming success without checking.
    import os
    os.makedirs("debug_output", exist_ok=True)
    with open("debug_output/team_list_page_response.html", "w") as f:
        f.write(page_resp.text)
    print(f"Saved raw team-list page response ({len(page_resp.text)} chars) to "
          f"debug_output/team_list_page_response.html for inspection.")

    kickoffs = extract_kickoffs_from_html(page_resp.text)
    print(f"Extracted {len(kickoffs)} match kickoff times from the page.")

    did_write = run(round_num, kickoffs, page_resp.text, args.output,
                     hours_before=args.hours_before)
    sys.exit(0)  # always exit 0 -- "nothing to do this hour" is not a failure
