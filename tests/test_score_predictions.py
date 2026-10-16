"""
test_score_predictions.py
==========================
Regression test for a real crash in print_cumulative_summary() (found
2026-10-13 while backfilling rounds 21-27 and the 2026 finals).

The bug: an f-string tried to put a conditional expression INSIDE a
format spec -- `f"{wb_mkt:.4f if wb_mkt is not None else 'n/a'}"`.
Python treats everything after the `:` in an f-string as a literal
format spec, not code, so this raised:

    ValueError: Invalid format specifier '.4f if wb_mkt is not None
    else 'n/a'' for object of type 'float'

every single time wb_mkt (the market Brier score) was a real float --
which is the normal case once two or more rounds have market odds data.
It only stayed hidden until now because score_predictions.py had only
ever been run for one round at a time (round 20), so the "market" Brier
branch at the SEASON level (which needs at least one round's real
market data) never actually got hit before.

The ledger entry for the round being scored is written by
update_ledger() BEFORE this function runs, so no real data was lost --
but the script exited non-zero, which a caller running it once per
round in a loop (e.g. a catch-up/backfill script) would treat as a
real failure and could stop a backfill run partway through for no real
data reason.

Run with: python3 -m unittest tests/test_score_predictions.py
(No third-party test framework needed -- uses only the standard
library, same as the rest of this repo's scripts.)
"""

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import score_predictions  # noqa: E402  (import after sys.path tweak, deliberately)


class PrintCumulativeSummaryTests(unittest.TestCase):
    def _write_ledger(self, entries):
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        path = Path(tmpdir.name) / "accuracy_ledger.json"
        path.write_text(json.dumps(entries))
        return str(path)

    def test_does_not_crash_when_market_brier_scores_are_real_floats(self):
        # Two rounds, both with real winner AND market Brier scores --
        # exactly the state that triggered the real crash (round 18 +
        # round 19 both scored, both with market odds present).
        ledger_path = self._write_ledger([
            {
                "season": 2026, "round": 18,
                "fixtures_scored_for_winner": 5, "correct_winner_pct": 40.0,
                "margin_mae": 11.2, "due_watch_flagged": 20,
                "due_watch_hit_rate_pct": 10.0, "try_scorer_edges_flagged": 158,
                "try_scorer_edge_hit_rate_pct": 31.0,
                "brier_winner_ours": 0.2752, "brier_winner_market": 0.2752,
                "brier_tryscorer_ours": 0.1243, "brier_tryscorer_market": 0.1349,
            },
            {
                "season": 2026, "round": 19,
                "fixtures_scored_for_winner": 7, "correct_winner_pct": 57.1,
                "margin_mae": 19.1, "due_watch_flagged": 28,
                "due_watch_hit_rate_pct": 17.9, "try_scorer_edges_flagged": 23,
                "try_scorer_edge_hit_rate_pct": 13.0,
                "brier_winner_ours": 0.1945, "brier_winner_market": 0.23,
                "brier_tryscorer_ours": 0.1539, "brier_tryscorer_market": 0.1484,
            },
        ])

        buf = io.StringIO()
        with redirect_stdout(buf):
            score_predictions.print_cumulative_summary(ledger_path)  # must not raise

        output = buf.getvalue()
        self.assertIn("Brier (winner):", output)
        self.assertIn("market=0.2", output)  # a real formatted float, not a crash

    def test_still_prints_na_when_market_brier_is_genuinely_absent(self):
        # Only our own Brier score is present (no market data for that
        # round) -- the "n/a" fallback branch must still work.
        ledger_path = self._write_ledger([
            {
                "season": 2026, "round": 20,
                "fixtures_scored_for_winner": 1, "correct_winner_pct": 100.0,
                "margin_mae": 2.0, "due_watch_flagged": 0,
                "due_watch_hit_rate_pct": None, "try_scorer_edges_flagged": 0,
                "try_scorer_edge_hit_rate_pct": None,
                "brier_winner_ours": 0.1, "brier_winner_market": None,
                "brier_tryscorer_ours": None, "brier_tryscorer_market": None,
            },
        ])

        buf = io.StringIO()
        with redirect_stdout(buf):
            score_predictions.print_cumulative_summary(ledger_path)  # must not raise

        self.assertIn("market=n/a", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
