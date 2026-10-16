"""
build_weekly_picks.py
=====================
Turns a round's predictions into the week's ranked picks: the list Studio OS's
BetBot app shows (top 8) and keeps as pretend money.

What counts as a pick (one list across three markets the bot already prices):
  - try_scorer: anytime try scorer, from fixture["try_scorer_edges"]
  - winner:     a team to win, from fixture["h2h"] (the side with a positive edge)
  - margin:     the home team on its points line, from fixture["h2h"]'s spread
                (the bot's predicted margin and its typical error give a chance
                of covering the line; the price is the bookie's own)

Ranking: biggest edge first, the gap between the bot's chance and the bookie's
chance in our favour. A try scorer's edge is first shrunk by the bot's own small-
sample discount (the same 1/sqrt(games) the decision engine uses). Nothing is
hidden because it looks risky: shaky picks are FLAGGED ("few games", "long shot",
"estimated price") so Sam decides in the app. There are no price cut-offs.

The sample rule: a player's games are the rounds he has played this season
BEFORE the round being predicted (never the future), plus last season's rounds
while the round being predicted is 5 or earlier (the start of a season).

Output:
  data/weekly_picks.json                      the current week (top 20 kept, so a
                                              removed pick has replacements)
  data/picks_history/<season>_round_<n>.json  the same, saved every week, so the
                                              prices at pick time are never lost

Status in the file:
  ok          picks written
  no_picks    prices exist but nothing has a positive edge
  no_prices   the price service had no upcoming event for any fixture. The
              file says so, nothing is archived, and the script exits 2 so the
              run turns red (a progress check: an empty week must never look
              like a successful one).

Usage:
    python3 scripts/build_weekly_picks.py                 # reads data/predictions_current.json
    python3 scripts/build_weekly_picks.py --predictions data/predictions_history/2026_round_19.json \\
        --out /tmp/picks.json --history-dir /tmp/hist     # replay a saved round
"""

import argparse
import csv
import json
import math
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from decision_engine import CORRELATION_DISCOUNT, _ev, _kelly_fraction_stake  # noqa: E402

TOP_N = 8                 # what the app shows
KEEP = 20                 # what the file keeps, so removed picks have replacements
MIN_GAMES = 5             # the sample rule
PRIOR_SEASON_UNTIL_ROUND = 5   # last season's games count while predicting round <= this
LONG_SHOT_PRICE = 12.0    # flag, never hide
SQRT_PI_OVER_2 = math.sqrt(math.pi / 2)   # turns a mean absolute error into a standard deviation

EXIT_NO_PRICES = 2


# ------------------------------------------------------------------ sample rule

def load_games(master_path):
    """{player_name: {season: set(rounds)}} from nrl_master.csv (one row per player per match)."""
    games = {}
    if not os.path.exists(master_path):
        return games
    with open(master_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                season, rnd = int(row["season"]), int(row["round"])
            except (KeyError, TypeError, ValueError):
                continue
            games.setdefault(row.get("player_name", ""), {}).setdefault(season, set()).add(rnd)
    return games


def sample_games(games, player, season, rnd):
    """Rounds played before `rnd` this season, plus last season's while rnd <= 5."""
    seasons = games.get(player, {})
    n = sum(1 for r in seasons.get(season, ()) if r < rnd)
    if rnd <= PRIOR_SEASON_UNTIL_ROUND:
        n += len(seasons.get(season - 1, ()))
    return n


# ------------------------------------------------------------------ maths

def normal_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def chance_to_cover(point, predicted_margin, margin_mae):
    """P(home margin + point > 0), margin ~ Normal(predicted, mae * sqrt(pi/2))."""
    sigma = max(margin_mae, 1.0) * SQRT_PI_OVER_2
    return 1.0 - normal_cdf((-point - predicted_margin) / sigma)


def pct(p):
    return f"{round(p * 100)}%"


# ------------------------------------------------------------------ candidates

def _flag(code, text):
    return {"code": code, "text": text}


def _common(market, fixture, selection, bet, price, price_is_estimate, bookmaker, our_p, mkt_p, edge,
            effective_edge, n_games, flags, why, extra=None):
    kelly = _kelly_fraction_stake(our_p, mkt_p)
    ev = _ev(our_p, mkt_p)
    if kelly is None or ev is None:
        return None
    pick = {
        "market": market,
        "fixture": fixture,
        "selection": selection,
        "bet": bet,
        "price": round(price, 2),
        "price_is_estimate": price_is_estimate,
        "bookmaker": bookmaker,
        "our_probability": round(our_p, 4),
        "market_probability": round(mkt_p, 4),
        "edge": round(edge, 4),
        "effective_edge": round(effective_edge, 4),
        "ev_per_unit": ev,
        "kelly_fraction": kelly,
        "n_games": n_games,
        "flags": flags,
        "why": why,
    }
    if price >= LONG_SHOT_PRICE:
        pick["flags"] = flags + [_flag("long_shot", f"Long shot (${price:.2f})")]
    if extra:
        pick.update(extra)
    return pick


def try_scorer_candidates(fixture, games, season, rnd):
    home, away = fixture.get("home_team"), fixture.get("away_team")
    label = f"{home} v {away}"
    best = {}
    for e in fixture.get("try_scorer_edges", []):
        edge = e.get("edge") or 0
        our_p, mkt_p = e.get("our_probability"), e.get("market_probability")
        if edge <= 0 or not our_p or not mkt_p:
            continue
        name = e.get("player_name")
        n = sample_games(games, name, season, rnd)
        penalty = min(1.0, 1.0 / math.sqrt(max(n, 1)))
        eff = edge * (1.0 - penalty)
        flags = []
        if n < MIN_GAMES:
            flags.append(_flag("few_games", f"Only {n} game{'s' if n != 1 else ''} to go on"))
        price = 1.0 / mkt_p
        pick = _common("try_scorer", label, f"{name}, anytime try scorer", f"{name} anytime try scorer",
                       price, False, e.get("bookmaker", "unknown"), our_p, mkt_p, edge, eff, n, flags,
                       f"Bot says {pct(our_p)} to score, bookie says {pct(mkt_p)} (${price:.2f})",
                       {"player_name": name, "team": e.get("team"), "position_code": e.get("position_code")})
        if pick is None:
            continue
        # One entry per player: keep the bookmaker with the best expected value.
        if name not in best or pick["ev_per_unit"] > best[name]["ev_per_unit"]:
            best[name] = pick
    return list(best.values())


def winner_candidate(fixture):
    home, away = fixture.get("home_team"), fixture.get("away_team")
    h = fixture.get("h2h") or {}
    our_home, mkt_home = h.get("our_home_win_prob"), h.get("market_home_win_prob")
    if our_home is None or mkt_home is None:
        return None
    sides = [(home, our_home, mkt_home), (away, 1.0 - our_home, 1.0 - mkt_home)]
    team, our_p, mkt_p = max(sides, key=lambda s: s[1] - s[2])
    edge = our_p - mkt_p
    if edge <= 0:
        return None
    price = 1.0 / mkt_p
    return _common("winner", f"{home} v {away}", f"{team} to win", f"{team} to win", price, True,
                   "market consensus", our_p, mkt_p, edge, edge,
                   None, [_flag("estimated_price", "Price is the market's fair price, not a bookie's")],
                   f"Bot gives {team} {pct(our_p)} to win, the market {pct(mkt_p)}",
                   {"team": team})


def margin_candidate(fixture):
    home, away = fixture.get("home_team"), fixture.get("away_team")
    h = fixture.get("h2h") or {}
    point, price = h.get("market_spread_point"), h.get("market_spread_price")
    pred, mae = h.get("our_predicted_margin"), h.get("margin_mae")
    if None in (point, price, pred, mae) or not price or price <= 1.0:
        return None
    our_p = chance_to_cover(point, pred, mae)
    mkt_p = 1.0 / price          # includes the bookie's margin, so this is a cautious edge
    edge = our_p - mkt_p
    if edge <= 0:
        return None
    sign = f"{point:+.1f}".replace("+-", "-")
    return _common("margin", f"{home} v {away}", f"{home} {sign}", f"{home} {sign} on the points line", price, False,
                   h.get("market_spread_bookmaker", "unknown"), our_p, mkt_p, edge, edge,
                   None, [], f"Bot expects {home} by {pred:+.0f} ({pct(our_p)} to cover); the line is {sign} at ${price:.2f}",
                   {"team": home, "line": point})


# ------------------------------------------------------------------ build

def load_predictions(path):
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    if isinstance(raw, dict) and "results" in raw:
        return raw.get("season"), raw.get("round"), raw["results"]
    fixtures = raw if isinstance(raw, list) else []
    return (fixtures[0].get("season") if fixtures else None), (fixtures[0].get("round") if fixtures else None), fixtures


def build(predictions_path, master_path, now=None):
    season, rnd, fixtures = load_predictions(predictions_path)
    games = load_games(master_path)
    if now is None:   # a replay of a saved round keeps the time it was predicted
        try:
            with open(predictions_path, encoding="utf-8") as f:
                saved = json.load(f).get("archived_at")
            now = datetime.fromisoformat(saved) if saved else datetime.now(timezone.utc)
        except (OSError, ValueError, AttributeError):
            now = datetime.now(timezone.utc)
    priced = [f for f in fixtures if f.get("status") in ("ok", None)]

    out = {
        "season": season, "round": rnd, "generated_at": now.isoformat(),
        "top_n": TOP_N, "keep": KEEP,
        "parameters": {"min_games": MIN_GAMES, "prior_season_until_round": PRIOR_SEASON_UNTIL_ROUND,
                       "long_shot_price": LONG_SHOT_PRICE},
        "calibration_warning": ("The bot's chances are not calibrated yet, so edges are estimates. "
                                "The pretend-money line is what shows whether they hold up."),
        "fixtures_total": len(fixtures), "fixtures_priced": len(priced),
        "picks": [],
    }
    if not priced:
        out.update(status="no_prices",
                   reason="The price service had no upcoming event for any fixture this round (prices only exist "
                          "before kickoff, so the run was probably too late or the round has no games yet).")
        return out

    candidates = []
    for f in priced:
        found = try_scorer_candidates(f, games, season, rnd)
        found += [c for c in (winner_candidate(f), margin_candidate(f)) if c]
        for c in found:   # scoring later needs the two teams of every pick
            c["home_team"], c["away_team"] = f.get("home_team"), f.get("away_team")
        candidates += found
    candidates.sort(key=lambda c: (c["effective_edge"], c["ev_per_unit"]), reverse=True)
    kept = candidates[:KEEP]
    # The bot's own stake rule (decision_engine.py): a try scorer whose team is also picked to win or cover
    # in the same match is a correlated bet, so its stake is halved. kelly_fraction stays the raw number.
    backed = {(c["fixture"], c.get("team")) for c in kept if c["market"] in ("winner", "margin")}
    for i, c in enumerate(kept, 1):
        c["rank"] = i
        discounted = c["market"] == "try_scorer" and (c["fixture"], c.get("team")) in backed
        c["correlated_with_team_pick"] = discounted
        c["stake_weight"] = round(c["kelly_fraction"] * (CORRELATION_DISCOUNT if discounted else 1.0), 5)
        out["picks"].append(c)
    if out["picks"]:
        out.update(status="ok", reason=f"{len(out['picks'])} picks kept, the top {TOP_N} are shown.")
    else:
        out.update(status="no_picks", reason="Prices exist but nothing has a positive edge this round.")
    return out


def write(result, out_path, history_dir):
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    if result["status"] != "no_prices" and result.get("season") and result.get("round"):
        os.makedirs(history_dir, exist_ok=True)
        hp = os.path.join(history_dir, f"{result['season']}_round_{result['round']}.json")
        with open(hp, "w", encoding="utf-8") as f:
            json.dump(dict(result, archived_at=result["generated_at"]), f, indent=2)
        return hp
    return None


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--data-dir", default="data")
    p.add_argument("--predictions", default=None)
    p.add_argument("--master", default=None)
    p.add_argument("--out", default=None)
    p.add_argument("--history-dir", default=None)
    a = p.parse_args(argv)
    d = a.data_dir
    result = build(a.predictions or os.path.join(d, "predictions_current.json"),
                   a.master or os.path.join(d, "nrl_master.csv"))
    hp = write(result, a.out or os.path.join(d, "weekly_picks.json"), a.history_dir or os.path.join(d, "picks_history"))
    print(f"Round {result['round']} ({result['season']}): {result['status']}. {result['reason']}")
    for c in result["picks"][:TOP_N]:
        flags = f"  [{'; '.join(x['text'] for x in c['flags'])}]" if c["flags"] else ""
        print(f"  {c['rank']}. {c['bet'][:44]:44s} ${c['price']:<6.2f} edge={c['edge']:+.3f}{flags}")
    if hp:
        print(f"Saved {hp}")
    if result["status"] == "no_prices":
        print("::error::No prices this round, so no picks were saved. See weekly_picks.json.")
        return EXIT_NO_PRICES
    return 0


if __name__ == "__main__":
    sys.exit(main())
