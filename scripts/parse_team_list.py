"""
parse_team_list.py
====================
Parses an NRL.com "Team Lists: Round N" article into structured rows: one
row per player, with team, opponent, position, jersey number, and name.

REWRITTEN 2026-06-22 after a real live Actions run revealed the actual raw
HTML structure differs from what a regex-on-flattened-text approach (the
original version of this module) assumed. The real markup separates a
match's header (kickoff time, team names -- see parse_draw_link_text.py)
from its player roster into sibling sections, not nested parent/child, and
each player's data lives across a few small elements rather than one
single line of readable text:

    <div class="team-list-profile team-list-profile--home">
      <div class="team-list-profile__name">
        <span class="u-visually-hidden">Fullback for Knights is number 6</span>
        Fletcher
        <span class="u-font-weight-700 ...">Sharpe</span>
      </div>
    </div>

The accessibility label span conveniently still contains a clean,
parseable sentence ("Fullback for Knights is number 6") -- this module
extracts position/team/number from that label, and the player's full name
from the surrounding text content of the same div (direct text + the
nested surname span).

Match/opponent context: confirmed via real data that match-header divs
(class="match") and team-list-profile divs appear in document order, with
all of one match's ~38 profile divs (19 players x 2 teams, give or take
empty slots) appearing between one match header and the next. This module
walks the document in order, tracking "current match" as it encounters
each header, and attaches that context to subsequent profiles -- rather
than relying on any DOM nesting relationship (there isn't one).

REAL FINDING 2026-06-24 (Sam provided 3 real consecutive rounds' worth of
team-list URLs -- Round 15, 16, 17 -- as a real cross-check): nrl.com's
RETROSPECTIVE team-list pages (i.e. fetched AFTER a round has been played,
like Round 16's real article, vs Round 17's real PRE-match article) show
an internally inconsistent-LOOKING accessibility label for any player
whose real on-field position differed from what was announced Tuesday.
Confirmed real example: Round 16's Knights v Dragons article literally
says "Fullback for Knights is number 6 Fletcher Sharpe" -- position label
"Fullback" (his real, true on-field position for that match, confirmed
matching nrl_master.csv's own recorded position for that exact game) paired
with jersey number "6" (his ORIGINALLY ANNOUNCED Tuesday number, for the
Five-Eighth slot he was announced to play before a real, later positional
swap). The page visibly shows a SECOND bracketed number too (e.g. "6 1"),
almost certainly the real corrected/final slot number -- not yet parsed
or used by this module, since PROFILE_LABEL_PATTERN only captures the
first number, but worth knowing this second number exists in the real
markup for any future real refinement.

PRACTICAL CONSEQUENCE: this module's regex (PROFILE_LABEL_PATTERN) is
confirmed to correctly extract the REAL, TRUE on-field position from
retrospective pages (the position label itself is accurate -- verified
against nrl_master.csv's own real recorded position for the same player/
round, twice, independently) -- it's only the paired jersey NUMBER that
may be stale/pre-match on a retrospective page. Since this project's real
use case for this module is fetching the CURRENT round's PRE-match team
list (where position and number are freshly announced together and
therefore consistent), this ambiguity doesn't affect generate_predictions.py's
real fetch_real_team_list_live() fallback in practice -- but it's worth
knowing if this module is ever pointed at a past round's article instead.
"""

import re
from bs4 import BeautifulSoup

MATCH_URL_PATTERN = re.compile(r"/round-(\d+)/([\w-]+)-v-([\w-]+)/")
PROFILE_LABEL_PATTERN = re.compile(
    r"(?P<position>[\w\s\-/]+?) for (?P<team>[\w\s\-']+?) is number (?P<number>\d+)"
)


def _slug_to_team_name(slug):
    """Converts a URL slug fragment like 'wests-tigers' to 'Wests Tigers'."""
    return " ".join(word.capitalize() for word in slug.split("-"))


def _is_match_header(tag):
    if tag.name != "div":
        return False
    classes = tag.get("class") or []
    return classes == ["match"] or (len(classes) <= 2 and "match" in classes)


def _is_profile(tag):
    if tag.name != "div":
        return False
    classes = tag.get("class") or []
    return "team-list-profile" in classes


def parse_team_list_page(page_html, round_num, season=2026):
    """
    Returns a list of dicts, one per player: player_name, team, opponent,
    position, jersey_number, round, season. Empty roster slots (a team
    that didn't name a player for a given bench spot) are silently skipped
    -- confirmed via real data this is a genuine, expected occurrence, not
    a parsing failure.
    """
    soup = BeautifulSoup(page_html, "html.parser")
    elements = soup.find_all(lambda t: _is_match_header(t) or _is_profile(t))

    rows = []
    current_home, current_away = None, None

    for el in elements:
        if _is_match_header(el):
            link = el.find("a", href=MATCH_URL_PATTERN)
            href = link.get("href", "") if link else ""
            m = MATCH_URL_PATTERN.search(href)
            if m:
                _, home_slug, away_slug = m.groups()
                current_home = _slug_to_team_name(home_slug)
                current_away = _slug_to_team_name(away_slug)
            continue

        # It's a profile div
        label_span = el.find("span", class_="u-visually-hidden")
        if not label_span:
            continue  # empty roster slot -- expected, not an error
        label_text = label_span.get_text()
        label_match = PROFILE_LABEL_PATTERN.search(label_text)
        if not label_match:
            continue

        team = label_match.group("team").strip()
        position = label_match.group("position").strip()
        jersey_number = int(label_match.group("number"))

        name_div = el.find("div", class_="team-list-profile__name")
        full_text = name_div.get_text(separator=" ", strip=True) if name_div else ""
        player_name = full_text.replace(label_text, "", 1).strip()
        player_name = re.sub(r"\s+", " ", player_name)
        if not player_name:
            continue  # label existed but no name text -- treat as empty slot

        if current_home and team == current_home:
            opponent = current_away
        elif current_away and team == current_away:
            opponent = current_home
        else:
            opponent = None  # shouldn't happen with real data; don't guess

        rows.append({
            "player_name": player_name,
            "team": team,
            "opponent": opponent,
            "position": position,
            "jersey_number": jersey_number,
            "round": round_num,
            "season": season,
        })

    return rows


if __name__ == "__main__":
    # Self-test against the REAL team-list page response captured from a
    # live GitHub Actions run (2026-06-22).
    with open("real_team_list_response.html") as f:
        html = f.read()

    rows = parse_team_list_page(html, round_num=16)
    print(f"Parsed {len(rows)} player rows (expect roughly 266, per real data)")

    teams_seen = sorted(set(r["team"] for r in rows))
    print(f"Teams seen ({len(teams_seen)}): {teams_seen}")

    # Spot check: Knights #6 should be Fletcher Sharpe, opponent Dragons
    knights_6 = [r for r in rows if r["team"] == "Knights" and r["jersey_number"] == 6]
    print(f"\nKnights #6: {knights_6}")
    assert knights_6 and knights_6[0]["player_name"] == "Fletcher Sharpe"
    assert knights_6[0]["opponent"] == "Dragons"
    print("PASS -- Knights #6 is Fletcher Sharpe, opponent correctly Dragons")

    missing_opponent = [r for r in rows if r["opponent"] is None]
    print(f"\nRows with unresolved opponent: {len(missing_opponent)} (expect 0)")
