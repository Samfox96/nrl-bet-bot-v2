"""
parse_draw_link_text.py
=========================
Extracts each match's kickoff time and team names from a team-list (or
draw) page's embedded match-header markup.

REWRITTEN 2026-06-22 after a real live Actions run revealed the actual raw
HTML structure is considerably cleaner than what this module originally
assumed. The real markup looks like:

    <div class="match ...">
      <h3 class="u-visually-hidden">Match: Knights v Dragons</h3>
      <a href="/draw/nrl-premiership/2026/round-16/knights-v-dragons/">
        <div class="match-header ...">
          <p class="match-header__title">Round 16 -
            <time class="js-local-datetime" datetime="2026-06-19T10:00:00Z"
                  data-local-datetime-options="dddd Do MMMM">
              Round 16 - Friday 19 Jun
            </time>
          </p>
          ...
          <div class="match-team match-team--home">
            ...<p class="match-team__name match-team__name--home">Knights</p>
          ...

Two real findings from inspecting this, both better than the original
(now-deleted) text-regex approach:
  - The <time> element's `datetime` attribute is a proper ISO 8601 UTC
    timestamp (e.g. "2026-06-19T10:00:00Z") -- no fragile parsing of
    "Friday 19 Jun 10:00 am" text required, no month-name lookup table
    needed. This is more robust than the original approach.
  - Team names are reliably recoverable from the match URL's slug
    (".../knights-v-dragons/") OR from match-team__name elements -- the
    slug is used here since it's already needed for match identification
    and is simpler to extract consistently for both teams in one place.

The UTC -> AEST (+10h) conversion finding from the original version still
holds and is still required: the datetime attribute is UTC, confirmed by
cross-referencing against the team-list page's own prose ("Friday 8.00pm"
kickoff time stated elsewhere on the same page).
"""

import re
from datetime import datetime, timedelta
from bs4 import BeautifulSoup

AEST_OFFSET_HOURS = 10

MATCH_URL_PATTERN = re.compile(r"/round-(\d+)/([\w-]+)-v-([\w-]+)/")


def _slug_to_team_name(slug):
    """
    Converts a URL slug fragment like "wests-tigers" into a display-style
    team name "Wests Tigers". Simple title-casing on hyphen-split words --
    matches the team names already used elsewhere in this project's alias
    files closely enough to run through team_aliases.json for final
    normalization (not done here -- this module stays focused on kickoff
    times; alias normalization is the caller's responsibility, consistent
    with how the rest of this project handles team-name normalization).
    """
    return " ".join(word.capitalize() for word in slug.split("-"))


def extract_kickoffs_from_html(page_html):
    """
    Returns a list of dicts: {round, home_team, away_team, kickoff_aest},
    one per match found in the page's match-header markup.

    Best-effort: a match div missing either the URL link or the <time>
    element is silently skipped (logged by the caller if it cares), since
    a partial page (e.g. mid-deploy on nrl.com's end) shouldn't crash the
    whole scrape over one malformed entry.
    """
    soup = BeautifulSoup(page_html, "html.parser")
    match_divs = soup.find_all("div", class_="match")

    results = []
    for div in match_divs:
        link = div.find("a", href=MATCH_URL_PATTERN)
        time_el = div.find("time", attrs={"datetime": True})
        if not link or not time_el:
            continue

        href = link.get("href", "")
        url_match = MATCH_URL_PATTERN.search(href)
        if not url_match:
            continue

        round_num, home_slug, away_slug = url_match.groups()
        utc_str = time_el.get("datetime", "")
        try:
            utc_dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            continue

        aest_dt = utc_dt + timedelta(hours=AEST_OFFSET_HOURS)

        results.append({
            "round": int(round_num),
            "home_team": _slug_to_team_name(home_slug),
            "away_team": _slug_to_team_name(away_slug),
            "kickoff_aest": aest_dt,
        })

    return results


if __name__ == "__main__":
    # Self-test against the REAL team-list page response captured from a
    # live GitHub Actions run (2026-06-22) -- not a hand-typed sample.
    with open("real_team_list_response.html") as f:
        html = f.read()

    print("Testing against REAL live-fetched team-list page response:\n")
    results = extract_kickoffs_from_html(html)
    print(f"Found {len(results)} matches (expect 7):\n")

    expected_first = {
        "round": 16, "home_team": "Knights", "away_team": "Dragons",
        "kickoff_aest": datetime(2026, 6, 19, 20, 0),
    }

    all_passed = True
    for r in results:
        print(f"  R{r['round']}: {r['home_team']} v {r['away_team']} -- {r['kickoff_aest']} AEST")

    first = results[0] if results else None
    passed = first == expected_first
    all_passed &= passed
    print(f"\n[{'PASS' if passed else 'FAIL'}] First match matches expected Knights v Dragons, 8pm AEST")

    assert len(results) == 7, f"Expected 7 matches, got {len(results)}"
    print(f"[PASS] Found all 7 matches")

    print(f"\nAll checks passed: {all_passed}")
