# -*- coding: utf-8 -*-
"""V1 套牌旅程时间轴。"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.deck_detail import _deck_kind, _journey, deck_detail
from app import store


def _row(day_offset, i, result="win", pd="play", ver="v1"):
    ts = int((datetime(2026, 9, 1) + timedelta(days=day_offset)).replace(hour=10).timestamp() * 1000) + i
    return {
        "id": i,
        "match_id": f"m-{day_offset}-{i}",
        "start_time": ts,
        "my_result": result,
        "play_draw": pd,
        "my_deck_version": ver,
        "event_id": "Play_Brawl_Historic",
    }


def test_journey_groups_by_day_chronological():
    rows = [_row(2, 1), _row(0, 1, result="loss"), _row(0, 2), _row(1, 1)]
    j = _journey(rows)
    assert [d["date"] for d in j["days"]] == ["2026-09-01", "2026-09-02", "2026-09-03"]
    assert j["days"][0]["n"] == 2 and j["days"][0]["wins"] == 1
    assert j["day_count"] == 3 and j["span_days"] == 3


def test_journey_version_marks():
    rows = [
        _row(0, 1, ver="v1"),
        _row(0, 2, ver="v1"),
        _row(2, 1, ver="v2"),
        _row(3, 1, ver="v2"),
    ]
    j = _journey(rows)
    assert len(j["version_marks"]) == 2
    assert j["version_marks"][0]["version"] == "v1" and j["version_marks"][0]["n_after"] == 2
    assert j["version_marks"][1]["version"] == "v2" and j["version_marks"][1]["n_after"] == 2


def test_journey_skips_unknown_date():
    rows = [_row(0, 1)]
    bad = dict(rows[0], start_time=None, match_id="m-x")
    j = _journey(rows + [bad])
    assert j["day_count"] == 1 and j["unknown_day"] == 1


def test_deck_detail_includes_journey(tmp_path):
    db = store.connect(tmp_path / "t.db")
    db.execute(
        """INSERT INTO matches(match_id, source, event_id, start_time, my_seat,
               play_draw, my_result, my_deck_tag, my_deck_id, my_deck_version, match_mode)
           VALUES('a','log','Play_Brawl_Historic', 1725150000000, 1,
                  'play','win','测试牌','d1','v1','BO1')"""
    )
    db.execute(
        """INSERT INTO matches(match_id, source, event_id, start_time, my_seat,
               play_draw, my_result, my_deck_tag, my_deck_id, my_deck_version, match_mode)
           VALUES('b','log','Play_Brawl_Historic', 1725236400000, 1,
                  'draw','loss','测试牌','d1','v2','BO1')"""
    )
    db.commit()
    detail = deck_detail(db, deck_id="d1", scope="all")
    j = detail["journey"]
    assert j["day_count"] >= 1
    assert "days" in j and "version_marks" in j
    assert detail["deck_kind"]["kind"] == "brawl"
    db.close()


def test_deck_kind_limited_and_constructed():
    def r(eid, i=0):
        return {"event_id": eid, "start_time": 1000 + i, "id": i}
    assert _deck_kind([r("PremierDraft_LCI")] * 4)["kind"] == "limited"
    assert _deck_kind([r("Ladder")] * 4)["kind"] == "constructed"
    assert _deck_kind([])["kind"] == "unknown"
