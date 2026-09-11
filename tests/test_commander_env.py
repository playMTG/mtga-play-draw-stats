# -*- coding: utf-8 -*-
"""V2 主将环境观察。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import store
from app.commander_env import commander_environment
from app.deck_detail import deck_detail


def _setup(tmp_path):
    db = store.connect(tmp_path / "t.db")
    db.execute("ATTACH DATABASE ':memory:' AS cards_db")
    db.execute("CREATE TABLE cards_db.cards(grp_id TEXT, name TEXT, name_zh TEXT)")
    db.executemany(
        "INSERT INTO cards_db.cards VALUES(?,?,?)",
        [("100", "MyCmdr", "我的主将"), ("200", "OppA", "阿耶尼"),
         ("201", "OppB", "对手乙")],
    )
    # 我用 100，4 场遇 200，1 场遇 201
    for i in range(5):
        mid = f"d-{i}"
        opp = "200" if i < 4 else "201"
        db.execute(
            """INSERT INTO matches(match_id, source, event_id, start_time, my_seat,
                   play_draw, my_result, my_deck_tag, my_deck_id, my_deck_version, match_mode)
               VALUES(?, 'log', 'Play_Brawl_Historic', ?, 1, ?, ?, '测试', 'd1', 'v1', 'BO1')""",
            (mid, 1725150000000 + i * 1000, "play" if i % 2 else "draw", "win"),
        )
        db.execute(
            "INSERT INTO commanders(match_id, seat, grp_id) VALUES(?,1,'100')", (mid,)
        )
        db.execute(
            "INSERT INTO commanders(match_id, seat, grp_id) VALUES(?,2,?)", (mid, opp)
        )
    # 全库基线：另有 10 场只遇 201
    for i in range(10):
        mid = f"b-{i}"
        db.execute(
            """INSERT INTO matches(match_id, source, event_id, start_time, my_seat,
                   play_draw, my_result, my_deck_tag, my_deck_id, my_deck_version, match_mode)
               VALUES(?, 'log', 'Play_Brawl_Historic', ?, 1, 'draw', 'loss', '其他', 'd2', 'v9', 'BO1')""",
            (mid, 1725000000000 + i),
        )
        db.execute(
            "INSERT INTO commanders(match_id, seat, grp_id) VALUES(?,2,'201')", (mid,)
        )
    db.commit()
    return db


def test_env_share_and_baseline(tmp_path):
    db = _setup(tmp_path)
    rows = [dict(r) for r in db.execute(
        "SELECT match_id, my_seat, play_draw, my_result, event_id FROM matches WHERE my_deck_id='d1'"
    )]
    env = commander_environment(db, deck_rows=rows, lang="zh", root=tmp_path)
    assert env["known"] == 5
    top = env["rows"][0]
    assert top["key"] == "200" and top["n"] == 4
    assert top["share_known"] == 80.0
    # 基线：15 场已知里 4 场是 200 → 约 26.7%
    assert top["baseline_share"] is not None
    assert top["delta_pp"] > 40
    assert env["play_draw"]["play"] == 2 or env["play_draw"]["play"] == 3
    db.close()


def test_non_brawl_returns_none(tmp_path):
    db = store.connect(tmp_path / "x.db")
    env = commander_environment(
        db,
        deck_rows=[{"match_id": "a", "event_id": "Ladder", "my_seat": 1, "my_result": "win", "play_draw": "play"}],
        baseline_rows=[],
    )
    assert env is None
    db.close()


def test_deck_detail_embeds_env(tmp_path):
    db = _setup(tmp_path)
    detail = deck_detail(db, deck_id="d1", scope="all", root=tmp_path)
    assert detail["commander_env"] is not None
    assert detail["commander_env"]["rows"][0]["n"] == 4
    db.close()
