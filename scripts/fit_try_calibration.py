"""
fit_try_calibration.py
======================
Fits the try-scorer calibration (see xtry_model.calibrate_try_probability) from a season's backtest: what the model said
before each round against what each player really did, using only data before that round. Writes
data/try_scorer_calibration.json (rising knots: model chance -> real rate) and prints a check that fits on early rounds
and scores on the later ones.

Run it again when there is a lot more data (for example after round 5 of next season, with last season's rounds too).

Usage:
    python3 scripts/fit_try_calibration.py --season 2026
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from backtest_season import predict_round  # noqa: E402
from generate_predictions import load_real_baselines  # noqa: E402
from xtry_model import CALIBRATION_FILE, calibrate_try_probability, safe_int  # noqa: E402

SLICES = 18   # quantile slices before pooling, enough for a smooth curve from ~6,500 players


def pool_rising(points):
    """Pool-adjacent-violators: make the real rate rise with the model's chance. points = [(chance, rate, weight)]."""
    out = []
    for p, y, w in sorted(points):
        out.append([p, y, w])
        while len(out) > 1 and out[-2][1] > out[-1][1]:
            a, b = out[-2], out[-1]
            t = a[2] + b[2]
            out[-2:] = [[(a[0] * a[2] + b[0] * b[2]) / t, (a[1] * a[2] + b[1] * b[2]) / t, t]]
    return out


def fit_knots(rows):
    rows = sorted(rows, key=lambda r: r["p"])
    n = len(rows)
    slices = []
    for i in range(SLICES):
        g = rows[i * n // SLICES:(i + 1) * n // SLICES]
        if g:
            slices.append((sum(r["p"] for r in g) / len(g), sum(r["y"] for r in g) / len(g), len(g)))
    return [[round(p, 4), round(y, 4)] for p, y, _ in pool_rising(slices)]


def brier(rows, f):
    return sum((f(r["p"]) - r["y"]) ** 2 for r in rows) / len(rows)


def collect(season, data_dir):
    bl = load_real_baselines(data_dir)
    rounds = sorted({safe_int(m["round"]) for m in bl["match_rows"] if int(m["season"]) == season})
    rows = []
    for rnd in rounds:
        pr = predict_round(season, rnd, bl, bl["master_rows"], bl["match_rows"])
        # The backtest asks for the raw (uncalibrated) chance so this never fits on its own output.
        rows += [{"r": rnd, "p": s["uncalibrated_probability"], "y": 1 if s["scored"] else 0} for s in pr["scorers"]]
    return rows


def main(argv=None):
    a = argparse.ArgumentParser()
    a.add_argument("--season", type=int, required=True)
    a.add_argument("--data-dir", default="data")
    a.add_argument("--out", default=None)
    args = a.parse_args(argv)
    rows = collect(args.season, args.data_dir)
    if len(rows) < 1000:
        print(f"Only {len(rows)} player-games: too few to fit a calibration. Nothing saved.")
        return 1
    last = max(r["r"] for r in rows)
    split = round(last * 2 / 3)
    early, late = [r for r in rows if r["r"] <= split], [r for r in rows if r["r"] > split]
    k_early = fit_knots(early)
    before = brier(late, lambda p: p)
    after = brier(late, lambda p: calibrate_try_probability(p, k_early))
    print(f"Check: fitted on rounds 1-{split} ({len(early)} players), scored on rounds {split + 1}-{last} ({len(late)}): "
          f"Brier {before:.4f} -> {after:.4f} (lower is better).")
    knots = fit_knots(rows)
    out = args.out or os.path.join(args.data_dir, "try_scorer_calibration.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"season": args.season, "fitted_at": datetime.now(timezone.utc).isoformat(), "players": len(rows),
                   "check": {"fit_rounds": [1, split], "test_rounds": [split + 1, last], "brier_before": round(before, 4),
                             "brier_after": round(after, 4)},
                   "knots": knots}, f, indent=2)
    print(f"Saved {len(knots)} knots to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
