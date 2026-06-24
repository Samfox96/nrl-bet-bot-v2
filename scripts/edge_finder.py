"""
edge_finder.py

The actual point where Phase 8's two previously-separate halves meet:
xtry_model.py produces "our probability" for a player to score, and
odds_probability.py already has calculate_edge(our_probability,
market_probability) waiting for exactly that input -- this module is
the connective layer between them, since neither existing module
should import the other (each is independently complete and tested;
xtry_model.py has zero knowledge of bookmaker odds, odds_probability.py
has zero knowledge of player stats -- that separation is deliberate
and worth keeping).

WHAT THIS MODULE DOES:
  1. Takes xtry_model's normalise_match_xtry() output (player_name ->
     display_probability) for one match.
  2. Takes real bookmaker odds for that same match's
     player_try_scorer_anytime market, in the-odds-api.com's real
     response shape (confirmed 2026-06-24 via the MLB batter_home_runs
     example, which is structurally identical to how an NRL anytime
     try-scorer market would be returned: outcomes shaped like
     {"name": "Yes", "description": "<player full name>", "price": ...}
     -- description holds the player's name, not name itself, which
     just says "Yes" for every row in this market type).
  3. Matches player names between the two sources EXPLICITLY and
     VISIBLY -- never assumes exact string equality silently succeeds.
     nrl_master.csv's player_name and the bookmaker's description field
     are two independently-sourced strings; team names had real,
     confirmed spelling mismatches (see team_aliases.json's "Canterbury
     Bulldogs" fix, 2026-06-24) and there's no reason to assume player
     names are cleaner without checking. This module surfaces
     unmatched names rather than silently dropping them.
  4. Converts the bookmaker's "Yes" price to a probability via
     yes_no_market_probability() (NOT de_margin() -- confirmed in
     odds_probability.py's own real findings that try-scorer markets
     are independent yes/no propositions with no second side to
     de-margin against).
  5. Calls calculate_edge() for every successfully-matched player,
     returning a sorted list (biggest edge first) plus an explicit
     unmatched-names list so nothing silently vanishes.

WHAT THIS MODULE DOES NOT DO:
  - Does not fetch live odds itself -- caller supplies the real
    bookmaker_odds_for_market dict, same pattern as odds_probability.py
    itself (network calls happen elsewhere; this stays testable without
    live API access, same reasoning that's applied throughout this
    project's modules).
  - Does not pick a single "best" bookmaker price for the edge
    calculation by default -- uses EACH bookmaker's price separately
    (the spec for try-scorer markets, per odds_probability.py's
    yes_no_market_probability(), compares OUR number directly against
    each book's stated probability, since there's no consensus/
    de-margining step for this market shape). A caller wanting one
    edge-per-player across multiple books should pick which bookmaker's
    price to use, or call this for each book and pick the best edge --
    that's a presentation-layer decision, not implemented here as a
    silent default.
"""

import sys
import os

# Both sibling modules live in the same scripts/ directory in the real
# repo -- import them directly rather than duplicating their logic.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from xtry_model import normalise_match_xtry  # noqa: E402
from odds_probability import (  # noqa: E402
    yes_no_market_probability,
    calculate_edge,
)


def find_edges_for_match(
    home_team_raw_scores,
    away_team_raw_scores,
    real_avg_tries_per_team,
    bookmaker_odds_for_market,
):
    """
    home_team_raw_scores, away_team_raw_scores: lists of per-player dicts
        as returned by xtry_model.calculate_player_xtry_raw() for every
        modelled player on each side of one match.
    real_avg_tries_per_team: from
        xtry_model.compute_real_avg_tries_per_team_per_game().
    bookmaker_odds_for_market: dict of
        bookmaker_key -> {player_description_string: decimal_price}
        for ONE try-scorer market from ONE bookmaker snapshot. Caller
        is responsible for having already filtered the real API
        response down to this shape (extracting "description" as the
        key and "price" as the value from each "Yes" outcome) -- this
        module doesn't parse the raw API JSON itself, to keep it
        testable without a live response on hand.

    Returns a dict:
      {
        "edges": [ {player_name, team, our_probability,
                     market_probability, edge, fair_odds_implied_by_our_model,
                     bookmaker} , ... ]  -- sorted by edge descending
                     (biggest "we think this is more likely than the
                     market does" first)
        "unmatched_in_odds": [player names xtry_model modelled but no
                     bookmaker had odds for -- not necessarily a
                     problem, e.g. low-profile bench players often
                     aren't priced by any book, but worth surfacing]
        "unmatched_in_model": [bookmaker player descriptions that
                     couldn't be matched to any xtry_model player --
                     THIS is the one worth real attention, since it
                     usually means a name-format mismatch (see module
                     docstring) rather than a genuinely unmodelled
                     player, and silently dropping these would hide a
                     real data-matching bug]
      }
    """
    our_probabilities = normalise_match_xtry(
        home_team_raw_scores, away_team_raw_scores, real_avg_tries_per_team
    )

    edges = []
    unmatched_in_odds = []
    matched_bookmaker_names = set()

    for player_name, our_info in our_probabilities.items():
        our_probability = our_info["display_probability"]

        found_for_player = False
        for bookmaker_key, outcomes in bookmaker_odds_for_market.items():
            price = outcomes.get(player_name)
            if price is None:
                continue
            found_for_player = True
            matched_bookmaker_names.add(player_name)

            market_probability = yes_no_market_probability(price)

            edge_result = calculate_edge(our_probability, market_probability)
            edges.append({
                "player_name": player_name,
                "team": our_info["team"],
                "position_code": our_info["position_code"],
                "bookmaker": bookmaker_key,
                **edge_result,
            })

        if not found_for_player:
            unmatched_in_odds.append(player_name)

    # Any bookmaker player description that never matched ANY of our
    # modelled players, across ANY bookmaker -- surfaced explicitly
    # rather than silently ignored, since this is the one category
    # most likely to indicate a real name-matching bug (see module
    # docstring) rather than an expected gap.
    all_bookmaker_player_names = set()
    for outcomes in bookmaker_odds_for_market.values():
        all_bookmaker_player_names.update(outcomes.keys())
    unmatched_in_model = sorted(all_bookmaker_player_names - matched_bookmaker_names)

    edges.sort(key=lambda e: e["edge"], reverse=True)

    return {
        "edges": edges,
        "unmatched_in_odds": sorted(unmatched_in_odds),
        "unmatched_in_model": unmatched_in_model,
    }
