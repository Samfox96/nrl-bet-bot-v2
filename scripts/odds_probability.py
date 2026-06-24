"""
odds_probability.py

Phase 8: converts bookmaker decimal odds into de-margined ("true")
implied probabilities, so they can be fairly compared against our own
model's probability for the same outcome. This is the market-agnostic
core of the odds pipeline -- it works the same way for h2h, totals,
player_try_scorer_anytime, or any other market, since every market is
structurally just "a price for an outcome."

REAL DATA FINDINGS THIS WAS BUILT AGAINST (2026-06-24, via real
the-odds-api.com calls against an actual upcoming NRL fixture --
Newcastle Knights v Wests Tigers, Round 17):

  - Discovered via /events/{id}/markets that NOT every bookmaker offers
    every market. Of 11 AU bookmakers on this fixture, all 11 offer
    h2h; only 7 offer player_try_scorer_anytime; only 1 (Bet Right)
    offers halftime_fulltime; only 1 (PointsBet) offers odd_even. This
    means any "best edge across the market" comparison must handle a
    market with anywhere from 1 to 11 real bookmaker prices -- never
    assume a minimum count.

  - Standard AU fixed-odds bookmakers showed a real, consistent 4.9-6.1%
    overround on this match's h2h market (Sportsbet, Bet Right, Betr,
    TAB, PointsBet, Neds, Ladbrokes, TABtouch, Unibet, PlayUp all
    clustered tightly) -- confirms the de-margining approach below
    against real, sane numbers before trusting it on anything else.

  - Betfair Exchange (the originally-planned "true market, no margin"
    anchor) showed a 36.3% apparent overround on this SAME match,
    4 days before kickoff -- a back price of 1.01 alongside a lay price
    of 1000.0 on the other outcome, which is the signature of an
    illiquid/stale order book, not a genuine market-clearing price.
    CONCLUSION: an exchange's price is only trustworthy as a "true
    market" anchor when its own implied overround is close to zero --
    when it's not, the exchange is showing a thin/stale price and
    should be treated as unavailable for that match, not blindly
    trusted just because it's "an exchange". See
    is_exchange_price_reliable() below.

WHAT THIS MODULE DOES NOT DO:
  - Does not fetch odds itself (see odds_fetcher.py for the actual API
    calls) -- this module only does the probability math, so it can be
    tested and reused independently of network calls.
  - Does not compute OUR side of any comparison (our own model's
    probability for a given outcome) -- per the agreed build order,
    that's wired in market-by-market as a separate, later step. This
    module's job ends at "here is the bookmaker's true implied
    probability for this outcome."
"""


def implied_probability(decimal_odds):
    """
    Raw implied probability from a single decimal odds price, before
    any de-margining. E.g. 2.00 -> 0.50, 1.50 -> 0.667.

    This is NOT a fair probability by itself -- it includes the
    bookmaker's margin. Use overround() and de_margin() below to get
    a genuinely comparable probability.
    """
    if decimal_odds <= 1.0:
        raise ValueError(
            f"Invalid decimal odds: {decimal_odds}. Decimal odds must be "
            f"> 1.0 (a price of 1.0 would mean a guaranteed loss for the "
            f"bettor with zero possible return)."
        )
    return 1.0 / decimal_odds


def overround(decimal_odds_list):
    """
    The bookmaker's total margin across all outcomes of a market, e.g.
    a 2-outcome h2h market with odds [1.42, 2.90] returns ~0.049 (4.9%).

    A genuinely fair, zero-margin market would sum to exactly 1.0
    (0% overround). Real fixed-odds bookmakers on a real NRL h2h
    market were confirmed (2026-06-24) to sit at 4.9-6.1% -- useful as
    a sanity reference range for what a NORMAL bookmaker margin looks
    like on this sport.
    """
    return sum(implied_probability(o) for o in decimal_odds_list) - 1.0


def de_margin(decimal_odds_list):
    """
    Returns a list of de-margined ("true") probabilities for each
    outcome, proportionally scaled down so they sum to exactly 1.0.
    This is the standard, simplest de-margining method (proportional/
    multiplicative) -- splits the bookmaker's margin evenly across
    outcomes in proportion to their raw implied probability.

    E.g. raw implied probabilities of [0.704, 0.345] (summing to 1.049,
    a 4.9% overround) become [0.671, 0.329] (summing to exactly 1.0).
    """
    raw_probs = [implied_probability(o) for o in decimal_odds_list]
    total = sum(raw_probs)
    return [p / total for p in raw_probs]


def is_exchange_price_reliable(decimal_odds_list, max_acceptable_overround=0.08):
    """
    Sanity check for exchange prices (Betfair Exchange and similar),
    added 2026-06-24 after a real Betfair h2h price on an actual
    upcoming fixture showed a 36.3% apparent overround -- the
    signature of an illiquid/stale order book days before kickoff, not
    a genuine market-clearing price. A real exchange should show a
    near-zero overround (no bookmaker margin); a real fixed-odds
    bookmaker normally shows roughly 4-7% on this sport (confirmed
    against real data above). 8% is a deliberately generous ceiling --
    comfortably above what a normal exchange OR a normal soft
    bookmaker would show, so this filter only catches genuinely
    anomalous/illiquid prices, not ordinary variation.

    Returns False (untrustworthy) if the overround is negative (also
    a sign of a broken/stale quote) or exceeds max_acceptable_overround.
    """
    margin = overround(decimal_odds_list)
    if margin < 0:
        return False
    return margin <= max_acceptable_overround


def yes_no_market_probability(decimal_odds):
    """
    For independent yes/no propositions (e.g. player_try_scorer_anytime,
    odd_even, first_team_to_score) -- markets where the bookmaker only
    ever quotes the "Yes" side, with no corresponding "No" price
    anywhere in the API response.

    REAL FINDING (2026-06-24): confirmed against an actual fetched
    player_try_scorer_anytime market for a real fixture -- every single
    outcome had name="Yes", none had name="No", across all bookmakers
    that offer this market. Summing implied probabilities even across
    a handful of players in this market badly exceeds 1.0 (confirmed:
    9 players alone summed to 3.87), proving this is NOT a mutually
    exclusive outcome set like h2h -- it's a series of independent
    bets, one per player, each its own separate proposition.

    The correct handling, clarified directly: this is not "a market
    missing its other side that needs de-margining" -- it's simply a
    single yes/no proposition, the same shape as "will it rain
    tomorrow." There is no second outcome to net against, because "the
    player doesn't score" isn't a separate thing anyone is betting on
    in this market -- it's just the absence of "yes". The bookmaker's
    quoted price for "Yes" already IS their complete stated probability
    for this proposition, margin and all baked in as a single number,
    not something to be split across two sides.

    This function is just implied_probability() under a name that
    makes this distinction explicit at the call site, so it's never
    confused with the de_margin() path used for h2h/totals/spreads.
    Do NOT attempt to de-margin a yes/no market -- there is no second
    side to de-margin against.
    """
    return implied_probability(decimal_odds)


def calculate_edge(our_probability, market_probability):
    """
    The actual "where do we have the advantage" number, for ANY market
    type -- mutually exclusive (post de_margin()/consensus_true_probability())
    or independent yes/no (post yes_no_market_probability()). Once both
    sides are expressed as a 0-1 probability for the SAME outcome, the
    comparison is identical regardless of which kind of market it came
    from -- this is the one function that doesn't need to know or care
    which market shape produced its inputs.

    Returns a dict with the raw edge (positive = our model thinks this
    outcome is MORE likely than the market does, i.e. a potential value
    bet; negative = the market thinks it's more likely than we do) and
    the implied "fair" decimal odds our own probability would justify,
    so it's directly comparable to the bookmaker's actual price.
    """
    if not (0 < our_probability < 1):
        raise ValueError(f"our_probability must be between 0 and 1, got {our_probability}")
    if not (0 < market_probability < 1):
        raise ValueError(f"market_probability must be between 0 and 1, got {market_probability}")

    edge = our_probability - market_probability
    fair_odds_for_our_probability = 1 / our_probability

    return {
        "our_probability": our_probability,
        "market_probability": market_probability,
        "edge": edge,
        "fair_odds_implied_by_our_model": round(fair_odds_for_our_probability, 3),
    }



    """
    Given odds from multiple bookmakers for the same market, returns
    the best (highest) price available for each outcome, and which
    bookmaker offers it. This is the "shop around for the best price"
    view -- separate from, and complementary to, the "best EDGE vs our
    model" view, which needs de-margined probabilities instead.

    bookmaker_odds: dict of bookmaker_key -> {outcome_name: decimal_odds}
    Returns: dict of outcome_name -> {"price": float, "bookmaker": str}
    """
    best = {}
    for bookmaker, outcomes in bookmaker_odds.items():
        for outcome_name, price in outcomes.items():
            if outcome_name not in best or price > best[outcome_name]["price"]:
                best[outcome_name] = {"price": price, "bookmaker": bookmaker}
    return best


def best_price_per_outcome(bookmaker_odds):
    """
    Given odds from multiple bookmakers for the same market, returns
    the best (highest) price available for each outcome, and which
    bookmaker offers it. This is the "shop around for the best price"
    view -- separate from, and complementary to, the "best EDGE vs our
    model" view, which needs de-margined probabilities instead.

    bookmaker_odds: dict of bookmaker_key -> {outcome_name: decimal_odds}
    Returns: dict of outcome_name -> {"price": float, "bookmaker": str}
    """
    best = {}
    for bookmaker, outcomes in bookmaker_odds.items():
        for outcome_name, price in outcomes.items():
            if outcome_name not in best or price > best[outcome_name]["price"]:
                best[outcome_name] = {"price": price, "bookmaker": bookmaker}
    return best


def consensus_true_probability(bookmaker_odds, outcome_names, exclude_unreliable_exchanges=True, exchange_keys=("betfair_ex_au", "betfair_ex_uk", "betfair_ex_eu")):
    """
    The core function for Phase 8's edge calculation: averages the
    de-margined probability for each outcome ACROSS all bookmakers
    that price this market, to get a consensus "true market" view --
    more robust than trusting any single bookmaker, and the natural
    fallback now that Betfair alone can't always reliably serve as
    the single "true market" anchor (see module docstring).

    bookmaker_odds: dict of bookmaker_key -> {outcome_name: decimal_odds}
        (only bookmakers that actually price this specific market --
        callers should already have filtered to that, since real data
        confirms not every bookmaker offers every market)
    outcome_names: ordered list of outcome names for this market, e.g.
        ["Newcastle Knights", "Wests Tigers"]
    exclude_unreliable_exchanges: if True, any bookmaker in
        exchange_keys whose own overround fails is_exchange_price_reliable()
        is dropped from the consensus entirely for this market, rather
        than having its distorted probability pull the average off.

    Returns: dict of outcome_name -> consensus_true_probability (float),
    plus "_bookmakers_used" and "_bookmakers_excluded" lists so callers
    can see exactly what went into (or was dropped from) the consensus,
    not just trust a black-box number.
    """
    bookmakers_used = []
    bookmakers_excluded = []
    all_demargined = []

    for bookmaker, outcomes in bookmaker_odds.items():
        prices = [outcomes.get(name) for name in outcome_names]
        if any(p is None for p in prices):
            # This bookmaker doesn't price all outcomes of this market
            # (shouldn't normally happen for a real h2h/totals market,
            # but never assume -- skip rather than crash or guess).
            bookmakers_excluded.append((bookmaker, "missing outcome price"))
            continue

        if exclude_unreliable_exchanges and bookmaker in exchange_keys:
            if not is_exchange_price_reliable(prices):
                bookmakers_excluded.append((bookmaker, "unreliable exchange price (illiquid/stale)"))
                continue

        demargined = de_margin(prices)
        all_demargined.append(demargined)
        bookmakers_used.append(bookmaker)

    if not all_demargined:
        return {
            "_bookmakers_used": [],
            "_bookmakers_excluded": bookmakers_excluded,
            "_error": "No reliable bookmaker prices available for this market.",
        }

    consensus = {}
    for i, name in enumerate(outcome_names):
        consensus[name] = sum(d[i] for d in all_demargined) / len(all_demargined)

    consensus["_bookmakers_used"] = bookmakers_used
    consensus["_bookmakers_excluded"] = bookmakers_excluded
    return consensus


if __name__ == "__main__":
    # Self-test against the REAL h2h odds fetched 2026-06-24 for
    # Newcastle Knights v Wests Tigers (Round 17).
    real_h2h_odds = {
        "sportsbet": {"Newcastle Knights": 1.47, "Wests Tigers": 2.70},
        "betright": {"Newcastle Knights": 1.45, "Wests Tigers": 2.75},
        "betr_au": {"Newcastle Knights": 1.42, "Wests Tigers": 2.90},
        "tab": {"Newcastle Knights": 1.42, "Wests Tigers": 2.90},
        "pointsbetau": {"Newcastle Knights": 1.42, "Wests Tigers": 2.80},
        "neds": {"Newcastle Knights": 1.44, "Wests Tigers": 2.80},
        "ladbrokes_au": {"Newcastle Knights": 1.44, "Wests Tigers": 2.80},
        "betfair_ex_au": {"Newcastle Knights": 1.01, "Wests Tigers": 2.68},  # known unreliable
        "tabtouch": {"Newcastle Knights": 1.43, "Wests Tigers": 2.80},
        "unibet": {"Newcastle Knights": 1.43, "Wests Tigers": 2.80},
        "playup": {"Newcastle Knights": 1.43, "Wests Tigers": 2.85},
    }

    print("=== Individual bookmaker overrounds (sanity check) ===")
    for bookmaker, outcomes in real_h2h_odds.items():
        prices = list(outcomes.values())
        margin = overround(prices)
        reliable = is_exchange_price_reliable(prices) if bookmaker.startswith("betfair") else "n/a (not an exchange)"
        print(f"  {bookmaker}: overround={margin:.1%}, exchange_reliable={reliable}")

    print()
    print("=== Consensus true probability (excluding unreliable exchanges) ===")
    consensus = consensus_true_probability(
        real_h2h_odds, ["Newcastle Knights", "Wests Tigers"]
    )
    for name, prob in consensus.items():
        if not name.startswith("_"):
            print(f"  {name}: {prob:.1%}")
    print(f"  Bookmakers used: {consensus['_bookmakers_used']}")
    print(f"  Bookmakers excluded: {consensus['_bookmakers_excluded']}")

    print()
    print("=== Best price per outcome (shop-around view) ===")
    best = best_price_per_outcome(real_h2h_odds)
    for name, info in best.items():
        print(f"  {name}: {info['price']} @ {info['bookmaker']}")
