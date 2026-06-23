r"""
parse_try_minutes.py

Extracts try-scorer + minute data from an NRL match page's "Tries" summary
box, for merging into nrl_master.csv as a new try_minutes column.

STRUCTURE THIS IS BUILT AGAINST (confirmed via real DevTools capture,
Round 16 Knights v Dragons, 2026-06-23 -- NOT an assumption):

  <div class="match-centre-summary-group">
    <h3 class="match-centre-summary-group__title">Tries</h3>
    <div class="u-display-flex">
      <h4 class="u-visually-hidden"> {Full Home Team Name} tries achieved by: </h4>
      <ul class="match-centre-summary-group__list match-centre-summary-group__list--home">
        <li> {Player Name} {minute}' </li>
        ...
      </ul>
      <h4 class="u-visually-hidden"> {Full Away Team Name} tries achieved by: </h4>
      <ul class="match-centre-summary-group__list match-centre-summary-group__list--away">
        <li> {Player Name} {minute}' </li>
        ...
      </ul>
    </div>
  </div>

Key real findings that informed this design (do not "simplify" away from these):
  - The page has multiple "match-centre-summary-group" divs (Tries, Conversions,
    Penalty Goals, Half Time, etc). We must specifically find the one that is
    the TRIES group -- identified by its <h4> text containing "tries achieved by",
    NOT by trusting the <h3> title text alone (title text wasn't fully visible in
    the captured DOM, and keying off the more specific working <h4> text is more
    robust regardless).
  - Team identity comes from the <h4 class="u-visually-hidden"> text, which uses
    FULL team names (e.g. "Newcastle Knights", "St. George Illawarra Dragons"),
    not the short names used in nrl_master.csv's `team` column (e.g. "Knights",
    "Dragons"). This MUST go through team_aliases.json to normalise before any
    comparison against nrl_master.csv -- confirmed live 2026-06-23 that
    nrl_master.csv stores short names, so a naive direct-string join would
    silently fail (0 matches), exactly as it did on first attempt this session.
  - Multiple tries by the same player appear as separate, repeated <li> elements
    (e.g. "Fletcher Sharpe 5'" and "Fletcher Sharpe 8'" as two distinct <li>s),
    not as one combined entry. Aggregation into a single "5;8" style string
    per player is something WE build when merging into nrl_master.csv -- it is
    not present in the source HTML.
  - <li> text has no player_id or link -- just "{Name} {minute}'" as plain text.
    Matching against nrl_master.csv's player_name column is therefore exact-string
    dependent. This is a real risk (nickname/suffix formatting mismatches between
    the match-summary box and the Player Stats table) and is NOT yet guaranteed
    safe -- see validate_try_minutes() below, which flags rather than silently
    drops any name that fails to match.

KNOWN, DELIBERATE GAP (decided 2026-06-23, do not "fix" without a real sample):
    Confirmed against 2 real captures (Knights v Dragons R16, Bulldogs v Sea
    Eagles R16 golden-point game). Both used plain "{minute}'" formatting (e.g.
    "82'") for events up to minute 82. Neither capture contained a TRY scored
    in extra time -- the golden-point game's winning score was a 1-point field
    goal (a separate stat-group, "...onePointFieldGoals achieved by:", correctly
    NOT matched by this parser's "tries achieved by" filter), not a try. So the
    extra-time TRY minute format (plain "81'" vs e.g. "80+1'") remains unconfirmed.
    Decision: do not guess. The minute regex (^(.*?)\s+(\d+)'$) will not match an
    "80+1'" style string if that's what nrl.com uses -- and by design that is NOT
    a silent failure: it's caught by the li_match check below and surfaces as an
    unparsed_entries flag in validate_try_minutes(), which sets ok=False. Revisit
    this the next time a real extra-time try is captured, rather than speculating
    now.
"""

import json
import re
from bs4 import BeautifulSoup


def load_team_aliases(path="team_aliases.json"):
    with open(path) as f:
        data = json.load(f)
    return data["aliases"]


def normalise_team_name(raw_name, aliases):
    """
    Best-effort normalisation of a team name string from the Tries box's
    h4 text (e.g. "St. George Illawarra Dragons") to the canonical full
    name used in team_aliases.json's canonical_teams list.

    Tries direct alias lookup first; falls back to a loose substring match
    against canonical_teams since the h4 text sometimes includes a leading
    "St." with a period that the alias map's "St George" entry doesn't have.
    Returns None (never guesses) if nothing matches, so callers can flag it
    rather than silently mis-attributing a team.
    """
    cleaned = raw_name.strip()
    if cleaned in aliases:
        return aliases[cleaned]

    # Loose fallback: try stripping punctuation and matching against
    # alias keys/values case-insensitively.
    normalised = re.sub(r"[.\-]", " ", cleaned).strip().lower()
    normalised = re.sub(r"\s+", " ", normalised)
    for key, canonical in aliases.items():
        if re.sub(r"[.\-]", " ", key).strip().lower() == normalised:
            return canonical
        if re.sub(r"[.\-]", " ", canonical).strip().lower() == normalised:
            return canonical

    return None


def parse_try_minutes(html, team_aliases_path="team_aliases.json"):
    """
    Parses the Tries summary box out of a match page's HTML.

    Returns a list of dicts:
        [{"player_name": "Fletcher Sharpe", "team_full": "Newcastle Knights",
          "team_canonical": "Newcastle Knights", "minute": 5}, ...]

    team_canonical is None if normalise_team_name() couldn't resolve it --
    callers should treat that as a flag-for-review case, not silently drop it.

    Returns [] (not an error) if no Tries group is found on the page -- this
    is a legitimate outcome (e.g. a 0-0 scoreline has no try-scorers to list,
    or the page structure differs from what we've captured so far) and callers
    should treat absence as "no try-minute data this match", never crash the
    main stats scrape over it.
    """
    soup = BeautifulSoup(html, "html.parser")
    aliases = load_team_aliases(team_aliases_path)

    results = []

    groups = soup.find_all("div", class_="match-centre-summary-group")
    tries_group = None
    for group in groups:
        h4s = group.find_all("h4")
        if any("tries achieved by" in h4.get_text(strip=True).lower() for h4 in h4s):
            tries_group = group
            break

    if tries_group is None:
        return results

    h4_tags = tries_group.find_all("h4")
    for h4 in h4_tags:
        h4_text = h4.get_text(strip=True)
        match = re.match(r"^(.*?)\s+tries achieved by:?$", h4_text, re.IGNORECASE)
        if not match:
            continue
        team_full = match.group(1).strip()
        team_canonical = normalise_team_name(team_full, aliases)

        # The relevant <ul> is the next sibling list element after this h4.
        ul = h4.find_next_sibling("ul")
        if ul is None:
            continue

        for li in ul.find_all("li"):
            li_text = li.get_text(strip=True)
            li_match = re.match(r"^(.*?)\s+(\d+)'$", li_text)
            if not li_match:
                # Doesn't match the expected "{Name} {minute}'" shape --
                # flag via None minute rather than skip silently, so a
                # genuine structure change gets noticed, not swallowed.
                results.append({
                    "player_name": li_text,
                    "team_full": team_full,
                    "team_canonical": team_canonical,
                    "minute": None,
                })
                continue

            player_name = li_match.group(1).strip()
            minute = int(li_match.group(2))
            results.append({
                "player_name": player_name,
                "team_full": team_full,
                "team_canonical": team_canonical,
                "minute": minute,
            })

    return results


def aggregate_try_minutes(parsed_tries):
    """
    Aggregates parsed per-try entries into one row per (player, team) with
    a semicolon-joined minute string, matching the format described in
    project notes (e.g. "5;8" for two tries by the same player).

    Returns a dict keyed by (player_name, team_canonical) -> "5;8" string.
    Entries with team_canonical=None are kept under (player_name, None) so
    they surface as unmatched in validate_try_minutes() rather than being
    merged incorrectly into a guessed team.
    """
    agg = {}
    for entry in parsed_tries:
        key = (entry["player_name"], entry["team_canonical"])
        minute_str = str(entry["minute"]) if entry["minute"] is not None else "?"
        agg.setdefault(key, []).append(minute_str)

    return {key: ";".join(minutes) for key, minutes in agg.items()}


def validate_try_minutes(parsed_tries, master_rows_for_match):
    """
    Cross-checks parsed try-minute data against existing `tries` column
    counts for the same match, per the outstanding validation gap noted
    in STATUS.md ("no validation cross-check against the existing tries
    column count exists yet").

    master_rows_for_match: list of dicts (or DictReader rows) for this
    match's players, each with at least 'player_name' and 'tries' (as
    a string or int) -- i.e. the relevant slice of nrl_master.csv.

    Returns a dict:
        {
          "ok": bool,
          "mismatches": [ {player_name, team_canonical, parsed_count, master_tries} ],
          "unmatched_team_names": [ team_full, ... ],   # normalise_team_name failures
          "unparsed_entries": [ {player_name, team_full}, ... ],  # minute regex failures
        }

    This NEVER silently trusts a clean-looking parse -- ok is only True if
    every parsed player's try count matches the master file's tries column
    AND every team name resolved AND every li matched the expected shape.
    """
    agg = aggregate_try_minutes(parsed_tries)

    master_tries_by_player = {}
    for row in master_rows_for_match:
        raw_tries = row.get("tries", "")
        try:
            master_tries_by_player[row["player_name"]] = int(raw_tries)
        except (ValueError, TypeError):
            # Raw scraped value before clean_dataframe() has run (e.g. "",
            # "-", or similar) -- treat as 0 rather than letting int() raise
            # and silently killing validation for the whole match via the
            # caller's outer try/except.
            master_tries_by_player[row["player_name"]] = 0

    mismatches = []
    unmatched_team_names = set()
    unparsed_entries = []

    for entry in parsed_tries:
        if entry["team_canonical"] is None:
            unmatched_team_names.add(entry["team_full"])
        if entry["minute"] is None:
            unparsed_entries.append({
                "player_name": entry["player_name"],
                "team_full": entry["team_full"],
            })

    for (player_name, team_canonical), minute_str in agg.items():
        parsed_count = len(minute_str.split(";"))
        master_count = master_tries_by_player.get(player_name)
        if master_count is None:
            mismatches.append({
                "player_name": player_name,
                "team_canonical": team_canonical,
                "parsed_count": parsed_count,
                "master_tries": None,  # player not found in master at all
            })
        elif parsed_count != master_count:
            mismatches.append({
                "player_name": player_name,
                "team_canonical": team_canonical,
                "parsed_count": parsed_count,
                "master_tries": master_count,
            })

    ok = (
        not mismatches
        and not unmatched_team_names
        and not unparsed_entries
    )

    return {
        "ok": ok,
        "mismatches": mismatches,
        "unmatched_team_names": sorted(unmatched_team_names),
        "unparsed_entries": unparsed_entries,
    }


if __name__ == "__main__":
    # Self-test against the real captured Round 16 Knights v Dragons structure.
    with open("sample_tries_box.html") as f:
        html = f.read()

    parsed = parse_try_minutes(html, team_aliases_path="team_aliases.json")
    print("=== Parsed try entries ===")
    for entry in parsed:
        print(entry)

    print("\n=== Aggregated (player, team) -> minutes ===")
    agg = aggregate_try_minutes(parsed)
    for key, minutes in agg.items():
        print(key, "->", minutes)

    print("\n=== Validation against known real nrl_master.csv data ===")
    master_rows = [
        {"player_name": "Fletcher Sharpe", "tries": "2"},
        {"player_name": "Sandon Smith", "tries": "1"},
        {"player_name": "Setu Tu", "tries": "1"},
        {"player_name": "Valentine Holmes", "tries": "1"},
        {"player_name": "Dylan Egan", "tries": "1"},
        {"player_name": "Tyrell Sloan", "tries": "1"},
    ]
    result = validate_try_minutes(parsed, master_rows)
    print(json.dumps(result, indent=2))
