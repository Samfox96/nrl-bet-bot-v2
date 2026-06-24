"""
odds_fetcher.py

The actual script that calls the real the-odds-api.com API and reshapes
its response into exactly what edge_finder.py and odds_probability.py
already expect. This was the one remaining piece of Phase 8's pipeline
that didn't exist yet -- everything built earlier (xtry_model.py,
edge_finder.py) was validated against real data shapes but never a
genuinely live call, since this sandbox cannot reach
api.the-odds-api.com directly.

VALIDATED AGAINST REAL DATA 2026-06-24 -- not built from docs alone.
Sam ran two real calls and pasted back the actual JSON:
  1. GET /v4/sports/rugbyleague_nrl/events/ -- confirmed real upcoming
     fixtures, including the exact Round 17 matches this project has
     been testing against all session (e.g. Newcastle Knights v Wests
     Tigers, event id 7d9714af3f3ebd2974b4371b1f2e95c0).
  2. GET /v4/sports/rugbyleague_nrl/events/{id}/odds?markets=h2h,
     player_try_scorer_anytime -- confirmed the EXACT real response
     shape this module parses below, across 9 real bookmakers
     (sportsbet, betright, betr_au, tab, pointsbetau, neds, ladbrokes_au,
     betfair_ex_au, tabtouch, unibet, playup -- not every bookmaker
     carries both markets, confirmed real: only 7 of these 11 actually
     had player_try_scorer_anytime priced).

REAL FINDING FROM THIS VALIDATION (worth tracking, same spirit as the
team-name mismatch found earlier): ran the full real pipeline
end-to-end -- this real odds response, reshaped by this module, fed
into the already-validated xtry_model.py output for the same real
Round 17 squads, through edge_finder.py's real matching logic. Of the
genuine unmatched_in_model results, 3 distinct real causes were found,
precisely diagnosed rather than lumped together:
  - "Tom Cant" (bookmaker) vs "Thomas Cant" (nrl_master.csv, 9 real
    games) -- a genuine nickname/full-name mismatch. The same CATEGORY
    of problem as the team-name spelling fix, just for individual
    players. NOT fixed with a hardcoded alias here (a single nickname
    pair isn't worth a whole alias system yet) -- surfaced instead via
    edge_finder.py's existing unmatched_in_model mechanism, which
    already does exactly this job. If nickname mismatches turn out to
    be common as more rounds get tested, a player_aliases.json
    (mirroring team_aliases.json's pattern) would be the right fix --
    not built preemptively for a sample size of 1.
  - "Lachlan Crouch" -- not a name mismatch at all. Confirmed: no
    matching name exists anywhere in nrl_master.csv. A real Wests
    Tigers player who simply hasn't appeared in any of the 16 real
    scraped rounds yet (a fringe player the bookmaker still prices
    speculatively).
  - "James Schiller" -- ALSO not a name mismatch. The exact name
    "James Schiller" exists in nrl_master.csv with 2 real games logged
    (round 8 and round 16, both for the Knights) -- but 2 games falls
    below the 3-game minimum xtry_model.py's calling code requires
    before modelling a player, so he never entered the candidate pool
    to be matched against in the first place. Confirms
    unmatched_in_model does double duty: it catches genuine name
    mismatches AND legitimately-named players who simply haven't
    cleared a modelling threshold yet -- worth distinguishing these
    by hand when reviewing real output, not assuming every entry in
    that list is a data bug.

WHAT THIS MODULE DOES:
  1. get_upcoming_events() -- lists real upcoming NRL fixtures with
     their the-odds-api.com event IDs and real team names.
  2. resolve_event_for_fixture() -- matches a (home, away) pair (in
     EITHER team_aliases.json short form or canonical full form) to
     the real event ID, using team_aliases.json so it doesn't matter
     which name format the caller has on hand.
  3. fetch_h2h_and_tryscorer_odds() -- the actual odds call for one
     event, returning the raw real response.
  4. extract_h2h_for_consensus() -- reshapes the real response into the
     bookmaker_odds dict shape odds_probability.py's
     consensus_true_probability() expects:
     {bookmaker_key: {outcome_name: decimal_price}}.
  5. extract_try_scorer_odds() -- reshapes the real response into the
     shape edge_finder.py's find_edges_for_match() expects:
     {bookmaker_key: {player_description: decimal_price}}.

WHAT THIS MODULE DOES NOT DO:
  - Does not call calculate_edge(), normalise_match_xtry(), or any
    other downstream function -- this module's job ends at "here is
    real odds data, reshaped into the format the other modules want."
    Wiring fetched odds into an actual edge calculation is the
    caller's job (e.g. a future weekly-automation script).
  - Does not decide WHEN to fetch (the open question flagged in
    STATUS.md about timing across the Thu-Sun window) -- caller decides
    when to call this.
  - Does not handle the totals line-mismatch problem (also still open,
    see STATUS.md) -- this module only handles h2h and
    player_try_scorer_anytime, the two markets actually validated
    against real data so far.
"""

import json
import urllib.request
import urllib.error


BASE_URL = "https://api.the-odds-api.com/v4"
SPORT_KEY = "rugbyleague_nrl"


def _get(url):
    """
    Minimal GET wrapper, no external dependencies (matches the
    project's existing preference for plain urllib over requests where
    reasonable -- see send_round_digest.py's own User-Agent fix, which
    was needed for exactly this reason: urllib doesn't set one by
    default, unlike most HTTP client libraries). Raises with the real
    response body on a non-200, rather than swallowing the error --
    a silent failure here would look identical to "no odds available"
    to a caller, which is a meaningfully different situation.
    """
    req = urllib.request.Request(url, headers={"User-Agent": "nrl-bet-bot-v2/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"the-odds-api.com returned HTTP {e.code}: {body}") from e


def get_upcoming_events(api_key):
    """
    Real endpoint: /v4/sports/rugbyleague_nrl/events/. Confirmed
    2026-06-24 against a real call -- returns id, commence_time,
    home_team, away_team for every upcoming NRL fixture, no markets
    data (this is the free "discover the event ID" call, separate from
    the priced odds call). Does NOT cost a usage credit per the-odds-
    api.com's own docs for /events endpoints.

    Returns the real list of dicts as the API returns them: each has
    id, sport_key, sport_title, commence_time, home_team, away_team.
    """
    url = f"{BASE_URL}/sports/{SPORT_KEY}/events/?apiKey={api_key}"
    return _get(url)


def resolve_event_for_fixture(events, home_team, away_team, team_aliases):
    """
    Matches a (home_team, away_team) pair to a real event from
    get_upcoming_events()'s output, regardless of which name format the
    caller has on hand (team_aliases.json short form like "Knights", or
    canonical full form like "Newcastle Knights" -- both resolve to the
    same comparison). Confirmed real 2026-06-24: the-odds-api.com's own
    team name strings for this match ("Newcastle Knights", "Wests
    Tigers") matched team_aliases.json's canonical form exactly for
    this fixture -- but matching defensively via the alias map rather
    than assuming exact string equality, since 3 of 17 real team names
    needed the alias map's help when this was checked for the h2h
    market earlier in the project (see team_aliases.json's "Canterbury
    Bulldogs" fix).

    Returns the matching event dict, or None if no real upcoming event
    matches both teams -- never guesses or returns a partial match.
    """
    home_canonical = team_aliases.get(home_team, home_team)
    away_canonical = team_aliases.get(away_team, away_team)

    for event in events:
        event_home_canonical = team_aliases.get(event["home_team"], event["home_team"])
        event_away_canonical = team_aliases.get(event["away_team"], event["away_team"])
        if event_home_canonical == home_canonical and event_away_canonical == away_canonical:
            return event
    return None


def fetch_h2h_and_tryscorer_odds(api_key, event_id, regions="au"):
    """
    Real endpoint: /v4/sports/rugbyleague_nrl/events/{id}/odds. This
    DOES cost usage credits (unlike get_upcoming_events()) -- confirmed
    real cost shape per the-odds-api.com's docs: cost scales with
    [markets] x [regions]. Requesting 3 markets x 1 region (au) here
    (h2h, player_try_scorer_anytime, spreads -- spreads added 2026-06-24
    specifically to support a real margin-vs-market comparison; see
    extract_single_bookmaker_spread()'s docstring for why this is read
    from ONE bookmaker rather than pooled across all of them).

    Returns the real raw response dict: id, sport_key, commence_time,
    home_team, away_team, bookmakers (list of {key, title, markets:
    [{key, last_update, outcomes}]}).
    """
    url = (
        f"{BASE_URL}/sports/{SPORT_KEY}/events/{event_id}/odds"
        f"?apiKey={api_key}&regions={regions}&markets=h2h,player_try_scorer_anytime,spreads"
        f"&oddsFormat=decimal"
    )
    return _get(url)


def extract_h2h_for_consensus(odds_response, team_aliases=None):
    """
    Reshapes the real odds_response into the
    {bookmaker_key: {outcome_name: decimal_price}} shape
    odds_probability.py's consensus_true_probability() and
    de_margin() expect.

    REAL BUG FOUND AND FIXED 2026-06-24: the original version of this
    function assumed every bookmaker's h2h outcome name already matches
    team_aliases.json's canonical form, based on the one real fixture
    confirmed that day (Newcastle Knights v Wests Tigers -- outcomes
    were genuinely "Newcastle Knights"/"Wests Tigers", an exact
    canonical match). That was an untested assumption masquerading as a
    confirmed fact: a SECOND real fixture (Gold Coast Titans v
    Canterbury Bulldogs, confirmed live 2026-06-24) showed every single
    one of 10 real bookmakers using "Canterbury Bulldogs" (no hyphen),
    never "Canterbury-Bankstown Bulldogs" -- the SAME real gap already
    found and fixed in team_aliases.json's aliases dict for event
    discovery, but this function never actually consulted that alias
    map, so the fix didn't help here. Real consequence: every
    bookmaker got silently excluded from consensus_true_probability()
    (its own `any(p is None...)` check correctly excludes a bookmaker
    missing an expected outcome key -- doing exactly what it was
    designed to do, given outcome names that didn't match), producing
    a real, silent "no h2h data" for that fixture with no error
    surfaced anywhere until a human noticed the email was missing it.

    Fix: every outcome name is now resolved through team_aliases.json
    BEFORE being used as a dict key, exactly the same alias-resolution
    discipline already applied everywhere else in this project (team
    short-name -> canonical, position label -> canonical code) --
    this function was the one real place still assuming, rather than
    enforcing, canonical naming. If team_aliases is None (not supplied),
    falls back to the original unresolved name -- explicit opt-in
    needed since this function has no other dependency on
    team_aliases.json and shouldn't assume a path silently.

    Skips any bookmaker that doesn't have an h2h market at all (real,
    confirmed case: playup had h2h but not every bookmaker carries
    every market -- never assume a bookmaker present in the response
    has every requested market).
    """
    result = {}
    for bookmaker in odds_response.get("bookmakers", []):
        for market in bookmaker.get("markets", []):
            if market["key"] == "h2h":
                outcomes = {}
                for outcome in market["outcomes"]:
                    name = outcome["name"]
                    if team_aliases is not None:
                        name = team_aliases.get(name, name)
                        # .get(name, name): if this exact string isn't a
                        # real key in the alias map, fall back to the
                        # raw name rather than silently dropping it --
                        # a genuinely new/unmapped real bookmaker string
                        # should surface as a visible mismatch downstream
                        # (consensus_true_probability's own exclusion
                        # logic), not be swallowed here.
                    outcomes[name] = outcome["price"]
                result[bookmaker["key"]] = outcomes
    return result


def extract_try_scorer_odds(odds_response):
    """
    Reshapes the real odds_response into the
    {bookmaker_key: {player_description: decimal_price}} shape
    edge_finder.py's find_edges_for_match() expects. Confirmed real
    shape 2026-06-24: player_try_scorer_anytime outcomes are ALL
    name="Yes" (never "No" -- confirmed real, not a data gap, see
    odds_probability.py's yes_no_market_probability() docstring), with
    the actual player's full name in the description field, not name.

    Only 7 of the 11 real bookmakers in the validated response actually
    had this market priced at all (sportsbet, tab, pointsbetau, neds,
    ladbrokes_au, tabtouch, unibet -- betright, betr_au, betfair_ex_au,
    playup had h2h only) -- confirmed real, handled naturally here since
    bookmakers without the market key simply contribute nothing, not an
    empty/error entry.
    """
    result = {}
    for bookmaker in odds_response.get("bookmakers", []):
        for market in bookmaker.get("markets", []):
            if market["key"] == "player_try_scorer_anytime":
                player_prices = {}
                for outcome in market["outcomes"]:
                    # Confirmed real: every outcome here is name="Yes".
                    # description holds the player's real full name.
                    # Still check name=="Yes" explicitly rather than
                    # assuming -- if a "No" ever genuinely appears (a
                    # bookmaker quirk not yet seen in real data), this
                    # skips it rather than silently treating it as a
                    # second "Yes" price for the same player.
                    if outcome.get("name") == "Yes":
                        player_prices[outcome["description"]] = outcome["price"]
                if player_prices:
                    result[bookmaker["key"]] = player_prices
    return result


def extract_single_bookmaker_spread(odds_response, home_team_full, preferred_bookmaker="sportsbet",
                                     team_aliases=None):
    """
    Returns ONE real bookmaker's spread line for the home team, rather
    than pooling across bookmakers -- DELIBERATE, not a shortcut.
    Confirmed real data 2026-06-24 (Knights v Wests Tigers): real
    spreads points are NOT standardised across bookmakers (3 distinct
    real lines seen for one match: -6.5, -7.5, -8.5). Pooling these
    into a consensus would average together genuinely different bets,
    not find a real edge -- the same problem already documented for
    `totals`. Reading a single named bookmaker's own real line sidesteps
    this entirely: it's always an internally-consistent real number
    (one bookmaker's own price + point for their own market), just not
    a market-wide consensus. Sam explicitly chose this trade-off over
    waiting for a real line-grouping fix (2026-06-24).

    REAL BUG FOUND AND FIXED 2026-06-24 (same root cause as
    extract_h2h_for_consensus's own fix, see its docstring for the full
    real story): this function's `outcome["name"] == home_team_full`
    check is an exact string comparison against the CANONICAL name,
    but real bookmakers don't always use canonical-matching strings
    (confirmed: "Canterbury Bulldogs" vs canonical "Canterbury-
    Bankstown Bulldogs"). Fixed the same way -- resolve each real
    outcome name through team_aliases.json before comparing, rather
    than comparing the raw API string directly against the canonical
    target.

    Falls back to whichever real bookmaker actually has a spreads
    market for this fixture if the preferred one doesn't (mirrors
    build_predictions_digest's same real fallback pattern for try-
    scorer coverage) -- never silently returns nothing if a real spread
    exists from ANY bookmaker.

    Returns (bookmaker_used, home_team_point, home_team_price) or
    (None, None, None) if no real bookmaker has a spreads market for
    this fixture at all.
    """
    spreads_by_bookmaker = {}
    for bookmaker in odds_response.get("bookmakers", []):
        for market in bookmaker.get("markets", []):
            if market["key"] == "spreads":
                for outcome in market["outcomes"]:
                    real_name = outcome["name"]
                    if team_aliases is not None:
                        real_name = team_aliases.get(real_name, real_name)
                    if real_name == home_team_full:
                        spreads_by_bookmaker[bookmaker["key"]] = (
                            outcome.get("point"), outcome.get("price")
                        )

    if not spreads_by_bookmaker:
        return None, None, None

    if preferred_bookmaker in spreads_by_bookmaker:
        bookmaker_used = preferred_bookmaker
    else:
        bookmaker_used = next(iter(spreads_by_bookmaker))

    point, price = spreads_by_bookmaker[bookmaker_used]
    return bookmaker_used, point, price


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python3 odds_fetcher.py <api_key> [home_team] [away_team]")
        print("Without home/away, lists all real upcoming events and their IDs.")
        sys.exit(1)

    api_key = sys.argv[1]
    events = get_upcoming_events(api_key)

    if len(sys.argv) >= 4:
        home_team, away_team = sys.argv[2], sys.argv[3]
        team_aliases = json.load(open("data/team_aliases.json"))["aliases"]
        event = resolve_event_for_fixture(events, home_team, away_team, team_aliases)
        if event is None:
            print(f"No real upcoming event found matching {home_team} v {away_team}")
            sys.exit(1)
        print(f"Resolved event: {event['home_team']} v {event['away_team']} (id={event['id']})")

        odds = fetch_h2h_and_tryscorer_odds(api_key, event["id"])
        h2h = extract_h2h_for_consensus(odds)
        try_scorer = extract_try_scorer_odds(odds)

        print(f"\nh2h ({len(h2h)} bookmakers):")
        print(json.dumps(h2h, indent=2))
        print(f"\nplayer_try_scorer_anytime ({len(try_scorer)} bookmakers):")
        print(json.dumps(try_scorer, indent=2))
    else:
        print(f"Real upcoming events ({len(events)} found):")
        for e in events:
            print(f"  {e['commence_time']}  {e['home_team']} v {e['away_team']}  (id={e['id']})")
