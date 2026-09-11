# -*- coding: utf-8 -*-
"""V3 赛制焦点。"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import store
from app.stats import format_focus


def _insert(db, mid, eid, day_ago=0, result="win"):
    ts = int((datetime.now() - timedelta(days=day_ago)).timestamp() * 1000)
    db.execute(
        """INSERT INTO matches(match_id, source, event_id, start_time, my_seat,
               play_draw, my_result) VALUES(?,?,?,?,1,'play',?)""",
        (mid, "log", eid, ts, result),
    )


def test_focus_prefers_brawl_when_mostly_brawl(tmp_path):
    db = store.connect(tmp_path / "a.db")
    for i in range(20):
        _insert(db, f"b{i}", "Play_Brawl_Historic", day_ago=1)
    for i in range(5):
        _insert(db, f"l{i}", "Ladder", day_ago=1)
    db.commit()
    f = format_focus(db)
    assert f["primary"] == "争锋"
    assert f["show_commanders"] is True
    assert f["show_rank"] is False
    db.close()


def test_focus_rank_when_ladder(tmp_path):
    db = store.connect(tmp_path / "b.db")
    for i in range(15):
        _insert(db, f"l{i}", "Ladder", day_ago=1)
    db.commit()
    f = format_focus(db)
    assert f["primary"] == "排位天梯"
    assert f["show_rank"] is True
    assert f["show_commanders"] is False
    db.close()


def test_focus_limited(tmp_path):
    db = store.connect(tmp_path / "c.db")
    for i in range(12):
        _insert(db, f"d{i}", "PremierDraft_LCI", day_ago=1)
    db.commit()
    f = format_focus(db)
    assert f["primary"] == "轮抽"
    assert f["show_commanders"] is False
    db.close()


def test_focus_empty_db(tmp_path):
    db = store.connect(tmp_path / "d.db")
    f = format_focus(db)
    assert f["primary"] == "unknown"
    db.close()
