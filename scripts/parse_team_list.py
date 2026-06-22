"""
parse_team_list.py
====================
Parses an NRL.com "Team Lists: Round N" article into structured rows.

This targets the text pattern confirmed by fetching a real, live team-list
page (Round 16, 2026-06-16): each player line reads as a consistent sentence:

    "<Position> for <Team> is number <N> <Player Name>"

This phrasing is stable across both the home and away team blocks for every
match in the round, repeated for every position group (Backs, Forwards,
Interchange, Reserves). The parser below works off that exact pattern via
regex, rather than assuming specific CSS classes/selectors -- those would
need confirming against the live rendered HTML (not yet done; this parses
the *visible text content* of the page, which is more robust to markup
changes than relying on specific div/class structure).

Output: one row per player per match: team, opponent, position, jersey
number, player name, round, plus the match's kickoff time (needed later to
decide which matches are "within 1 hour of kickoff" for the polling logic).
"""

import re
from datetime import datetime


PLAYER_LINE_PATTERN = re.compile(
    r"(?P<position>[\w\s\-/]+?) for (?P<team>[\w\s\-']+?) is number (?P<number>\d+) (?P<name>[\w\s.'\-]+?)(?:\n|$)"
)

# Matches a match header like:
# "Knights v Dragons, Friday 8.00pm at McDonald Jones Stadium"
# Also handles the NZ-fixture dual-timezone format:
# "Warriors v Cowboys, Sunday 2.00pm (AEST), 4.00pm (local time) at One NZ Stadium, Christchurch"
# In the dual-timezone case we keep the AEST time, since that's the timezone
# everything else in the project (bye schedule, round dates) is anchored to.
MATCH_HEADER_PATTERN = re.compile(
    r"^(?P<home>[\w\s'\-]+?) v (?P<away>[\w\s'\-]+?), "
    r"(?P<day>\w+) (?P<time>[\d.]+(?:am|pm))"
    r"(?:\s*\(AEST\))?"
    r"(?:,\s*[\d.]+(?:am|pm)\s*\(local time\))?"
    r" at (?P<venue>.+)$"
)


def parse_match_headers(page_text):
    """
    Finds all match header lines (e.g. '### Knights v Dragons, Friday 8.00pm
    at McDonald Jones Stadium') and returns structured match info, in the
    order they appear (which is the round's chronological match order).
    """
    matches = []
    for line in page_text.split("\n"):
        line = line.strip().lstrip("#").strip()
        m = MATCH_HEADER_PATTERN.match(line)
        if m:
            matches.append(m.groupdict())
    return matches


def parse_team_list_page(page_text, round_num, season=2026):
    """
    Returns a list of dicts, one per player, with team/opponent/position/
    number/name/round. Does not yet attach kickoff times -- that's joined
    in separately since the header format and player-line format appear in
    different parts of the page structure.
    """
    rows = []
    current_match = None  # (home_team, away_team) tuple, tracks context as we scan

    matches_seen = parse_match_headers(page_text)
    match_iter = iter(matches_seen)
    next_match = next(match_iter, None)

    lines = page_text.split("\n")
    for line in lines:
        stripped = line.strip().lstrip("#").strip()

        header_match = MATCH_HEADER_PATTERN.match(stripped)
        if header_match:
            current_match = header_match.groupdict()
            continue

        player_match = PLAYER_LINE_PATTERN.search(line)
        if player_match and current_match:
            d = player_match.groupdict()
            team = d["team"].strip()
            position = d["position"].strip().lstrip("-").strip()
            opponent = current_match["away"] if team == current_match["home"] else current_match["home"]
            rows.append({
                "player_name": d["name"].strip(),
                "team": team,
                "opponent": opponent,
                "position": position,
                "jersey_number": int(d["number"]),
                "round": round_num,
                "season": season,
                "match_day": current_match["day"],
                "match_time": current_match["time"],
                "venue": current_match["venue"],
            })

    return rows


if __name__ == "__main__":
    # Self-test against the real sample fetched from nrl.com Round 16.
    with open("sample_team_list.txt") as f:
        text = f.read()

    headers = parse_match_headers(text)
    print(f"Match headers found: {len(headers)}")
    for h in headers:
        print(f"  {h}")

    rows = parse_team_list_page(text, round_num=16)
    print(f"\nPlayer rows parsed: {len(rows)}")
    for r in rows:
        print(f"  {r}")
