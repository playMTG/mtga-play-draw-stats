from datetime import datetime, timedelta

import pytest

from app.comparisons import compare, summarize_by_event
from app.insights import daily_report
from app import store


@pytest.fixture
def db(tmp_path):
    connection = store.connect(tmp_path / "test.db")
    yield connection
    connection.close()


def add(connection, match_id, day, event="Play_Brawl_Historic", deck="test",
        pd="play", result="win"):
    ts = int(datetime.combine(day, datetime.min.time()).timestamp() * 1000)
    connection.execute(
        "INSERT INTO matches(match_id,start_time,event_id,my_deck_tag,play_draw,my_result,my_seat) "
        "VALUES(?,?,?,?,?,?,1)",
        (match_id, ts, event, deck, pd, result),
    )


def _row(event, mode, result, deck="甲", version="v1"):
    return {
        "event_id": event,
        "match_mode": mode,
        "my_result": result,
        "my_deck_tag": deck,
        "my_deck_version": version,
    }


def test_history_summary_groups_by_event_and_mode_with_partial_coverage():
    current = [
        _row("Ladder", "BO1", "win", version="v1"),
        _row("Ladder", "BO1", "loss", version="v2"),
        _row("Ladder", "BO3", "win", version="v1"),
    ]
    history = (
        [_row("Ladder", "BO1", "loss", version="v1") for _ in range(20)]
        + [_row("Ladder", "BO1", "win", version="v2") for _ in range(19)]
        + [_row("Ladder", "BO3", "win", version="v1") for _ in range(20)]
    )
    summary = summarize_by_event(compare(current, history))

    assert len(summary["items"]) == 2
    bo1 = next(item for item in summary["items"] if item["mode"] == "BO1")
    bo3 = next(item for item in summary["items"] if item["mode"] == "BO3")
    assert bo1["total_decided"] == 2 and bo1["comparable_n"] == 1
    assert bo1["delta_pp"] == 100 and bo1["status"] == "higher"
    assert "其中 1/2 场" in bo1["text"]
    assert bo3["delta_pp"] == 0 and bo3["status"] == "similar"
    assert "BO1" in summary["headline"]


def test_history_summary_keeps_first_use_facts_without_a_baseline():
    current = [_row("PremierDraft_TEST", "BO1", "win", deck=None, version=None)]
    summary = summarize_by_event(compare(current, []))

    assert summary["comparable_groups"] == 0
    assert summary["items"][0]["status"] == "no_baseline"
    assert "当天 1 场，1 胜 0 负" in summary["items"][0]["text"]
    assert "暂不比较" in summary["items"][0]["text"]
    assert "暂无足够可比历史" in summary["headline"]


def test_daily_report_exposes_event_mode_history_summary(db):
    today = datetime.now().date()
    for i in range(20):
        add(db, f"past-{i}", today - timedelta(days=1), result="loss")
    add(db, "today", today, result="win")
    db.execute("UPDATE matches SET my_deck_version='v1'")

    report = daily_report(db, today.isoformat())
    item = report["history_summary"]["items"][0]
    assert item["event"] == "Play_Brawl_Historic"
    assert item["mode"] == "BO1"
    assert item["delta_pp"] == 100
    assert "30 天" in report["history_summary"]["note"]
