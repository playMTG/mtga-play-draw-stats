# -*- coding: utf-8 -*-
"""R11.5：CSV 公式转义、空套牌标签可覆盖。"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import stats, store
from app.config import Config
from app.events import MatchRecord


def test_csv_safe_formula_prefixes():
    assert stats._csv_safe("=cmd|'/C calc'!A0") == "'=cmd|'/C calc'!A0"
    assert stats._csv_safe("+1+1") == "'+1+1"
    assert stats._csv_safe("-2+3") == "'-2+3"
    assert stats._csv_safe("@SUM(A1)") == "'@SUM(A1)"
    assert stats._csv_safe("  =HYPERLINK(x)") == "'=HYPERLINK(x)"
    assert stats._csv_safe("normal name") == "normal name"
    assert stats._csv_safe(42) == 42
    assert stats._csv_safe(None) == ""
    assert stats._csv_safe("") == ""


def test_export_escapes_opponent_name(tmp_path):
    cfg = Config({"port": 8765, "db_path": "m.db", "my_player_id": "ME",
                  "abnormal_match": {"max_duration_sec": 1, "max_turns": 1},
                  "log_paths": {}}, tmp_path)
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(store._SCHEMA)
    conn.execute(
        """INSERT INTO matches(match_id, source, event_id, my_result, opponent_name)
           VALUES('m1','log','Ladder','win','=HYPERLINK("http://evil")')"""
    )
    conn.commit()
    headers, rows = stats.export_rows(conn, "matches")
    opp_idx = headers.index("对手名")
    assert rows[0][opp_idx].startswith("'=")
    conn.close()


def test_empty_deck_tag_does_not_block_later_name(tmp_path):
    """R11.5/M4：空字符串套牌名不得挡住后续正确名称。"""
    cfg = Config({"port": 8765, "db_path": "x.db", "my_player_id": "ME",
                  "abnormal_match": {"max_duration_sec": 1, "max_turns": 1},
                  "log_paths": {}}, tmp_path)
    conn = store.connect(tmp_path / "t.db")
    m = MatchRecord(match_id="m-tag", my_deck_tag="")
    store.upsert_match(conn, m, cfg)
    m2 = MatchRecord(match_id="m-tag", my_deck_tag="拿杜套牌")
    store.upsert_match(conn, m2, cfg)
    row = conn.execute(
        "SELECT my_deck_tag FROM matches WHERE match_id='m-tag'"
    ).fetchone()
    assert row["my_deck_tag"] == "拿杜套牌"
    conn.close()
