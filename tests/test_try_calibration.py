import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import xtry_model  # noqa: E402
from fit_try_calibration import fit_knots, pool_rising  # noqa: E402

KNOTS = [(0.05, 0.10), (0.25, 0.23), (0.45, 0.30), (0.65, 0.45)]


def test_low_chances_are_left_alone():
    assert xtry_model.calibrate_try_probability(0.05, KNOTS) == 0.05
    assert xtry_model.calibrate_try_probability(0.19, KNOTS) == 0.19


def test_high_chances_come_down_between_knots():
    assert abs(xtry_model.calibrate_try_probability(0.35, KNOTS) - 0.265) < 1e-9
    assert xtry_model.calibrate_try_probability(0.65, KNOTS) == 0.45


def test_it_never_raises_a_chance():
    for p in [i / 100 for i in range(0, 66)]:
        assert xtry_model.calibrate_try_probability(p, KNOTS) <= p
    assert xtry_model.calibrate_try_probability(0.3, [(0.1, 0.9), (0.9, 0.95)]) == 0.3


def test_no_knots_changes_nothing():
    assert xtry_model.calibrate_try_probability(0.6, []) == 0.6


def test_missing_file_changes_nothing(tmp_path):
    assert xtry_model.load_calibration_knots(str(tmp_path / "nope.json")) == []


def test_pooling_makes_the_rate_rise():
    out = pool_rising([(0.1, 0.2, 10), (0.2, 0.1, 10), (0.3, 0.4, 10)])
    rates = [y for _, y, _ in out]
    assert rates == sorted(rates)
    assert abs(out[0][1] - 0.15) < 1e-9


def test_fit_pulls_an_overconfident_top_down():
    rows = [{"p": 0.6, "y": 1 if i % 5 < 2 else 0} for i in range(500)] + [{"p": 0.1, "y": 1 if i % 10 == 0 else 0} for i in range(500)]
    knots = fit_knots(rows)
    assert abs(xtry_model.calibrate_try_probability(0.6, knots) - 0.4) < 0.02


def test_the_saved_file_is_usable():
    knots = xtry_model.load_calibration_knots()
    assert knots and all(a[0] <= b[0] and a[1] <= b[1] for a, b in zip(knots, knots[1:]))


def test_match_output_keeps_the_raw_chance_and_calibrates():
    home = [{"player_name": "A", "team": "X", "position_code": "WG", "raw_xtry": 3.0, "components": {}},
            {"player_name": "B", "team": "X", "position_code": "FB", "raw_xtry": 0.1, "components": {}}]
    out = xtry_model.normalise_match_xtry(home, [], 3.0)
    raw = xtry_model.normalise_match_xtry(home, [], 3.0, calibrate=False)
    assert out["A"]["uncalibrated_probability"] == raw["A"]["display_probability"] == 0.65
    assert out["A"]["display_probability"] < 0.65


def test_nobody_who_takes_the_field_has_a_zero_chance():
    team = [{"player_name": "Star", "team": "X", "position_code": "WG", "raw_xtry": 5.0, "components": {}},
            {"player_name": "Prop", "team": "X", "position_code": "PR", "raw_xtry": 0.0001, "components": {}}]
    out = xtry_model.normalise_match_xtry(team, [], 4.0)
    assert out["Prop"]["display_probability"] == xtry_model.MIN_TRY_CHANCE == 0.03
    assert out["Prop"]["uncalibrated_probability"] == 0.03
    assert out["Star"]["display_probability"] > 0.3
