import pytest

from app.deck_observations import deck_observations, run_scan_probability


def row(match_id, ts, side="draw", result="loss"):
    return {
        "match_id": match_id,
        "start_time": ts,
        "play_draw": side,
        "my_result": result,
    }


def no_commanders():
    return {"rows": [], "known": 0}


def test_scan_probability_distinguishes_whole_range_from_fixed_window():
    assert run_scan_probability([7], 7) == pytest.approx(1 / 128)
    assert run_scan_probability([8], 8) == pytest.approx(1 / 256)
    assert run_scan_probability([8], 7) == pytest.approx(3 / 256)
    assert run_scan_probability([2], 3) == 0


def test_eight_draws_are_a_legendary_numbered_observation():
    rows = [row(f"m{i}", i + 1) for i in range(8)]
    result = deck_observations(rows, no_commanders(), {})
    item = result["items"][0]
    assert item["key"] == "streak-draw"
    assert item["level"] == "legendary"
    assert item["headline"] == "连续 8 把后手：离谱级连庄"
    assert item["probability"]["scan"] == pytest.approx(1 / 256)
    assert item["probability"]["scan_percent"] == 0.39
    assert item["probability"]["fixed_percent"] == 0.39
    assert item["match_ids"] == [f"m{i}" for i in range(8)]


def test_three_streak_starts_evaluation_and_unknown_breaks_probability_blocks():
    rows = [row("a", 1, "play"), row("b", 2, "play"), row("c", 3, "play"),
            row("gap", 4, None),
            row("d", 5, "draw"), row("e", 6, "draw"), row("f", 7, "draw")]
    result = deck_observations(rows, no_commanders(), {})
    by_key = {item["key"]: item for item in result["items"]}
    assert set(by_key) == {"streak-play", "streak-draw"}
    assert by_key["streak-play"]["headline"] == "连续 3 把先手：值得记录"
    assert by_key["streak-draw"]["probability"]["scan"] == pytest.approx(15 / 64)
    assert by_key["streak-draw"]["probability"]["blocks"] == 2
    assert "未知先后手会打断" in by_key["streak-draw"]["probability"]["explanation"]


def test_unknown_timestamp_prevents_streak_claim_but_keeps_summary():
    rows = [row("a", None), row("b", 2), row("c", 3)]
    result = deck_observations(rows, no_commanders(), {})
    assert [item["key"] for item in result["items"]] == ["range-summary"]


def test_repeated_commander_observation_includes_matchup_record():
    rows = [row("a", 1, "play", "win"), row("b", 2, "draw", "win"),
            row("c", 3, "draw", "win"), row("d", 4, "play", "loss")]
    commanders = {"known": 4, "rows": [{
        "key": "100", "name": "第一主将", "n": 3, "share_known": 75,
        "wins": 3, "losses": 0, "unknown_result": 0,
        "play": 1, "draw": 2, "unknown_play_draw": 0,
    }]}
    by_match = {"a": {"100"}, "b": {"100"}, "c": {"100"}, "d": {"200"}}
    result = deck_observations(rows, commanders, by_match)
    item = next(item for item in result["items"] if item["kind"] == "commander_matchup")
    assert item["headline"] == "对阵 第一主将，3 战全胜"
    assert item["match_ids"] == ["a", "b", "c"]
    assert "75%" in item["text"]
