# -*- coding: utf-8 -*-
"""M3 单测：主将档案聚合、先验映射、手动打标优先级。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json

import pytest

import fixtures as fx
from app.events import SessionBuilder
from app.parser import LineRecord
from app.store import connect, upsert_match
from app import stats


def feed(lines, my_id=fx.ME):
    sb = SessionBuilder(my_player_id=my_id)
    for i, t in enumerate(lines, 1):
        sb.feed(t)
    return sb.close()


def _cfg(tmp_path):
    from app.config import Config
    return Config({"db_path": str(tmp_path / "t.db"),
                   "abnormal_match": {"max_duration_sec": 150, "max_turns": 2}}, tmp_path)


def _store(tmp_path, n=1, play_draw="play"):
    cfg = _cfg(tmp_path)
    conn = connect(cfg.db_path)
    for i in range(n):
        my_active = 1 if play_draw == "play" else 2
        r = feed(fx.bo1_match_lines(match_id=f"m-{i:03d}", my_active=my_active))
        for m in r.matches:
            upsert_match(conn, m, cfg)
    conn.commit()
    return conn, cfg


def _priors(tmp_path, data):
    (tmp_path / "commander_archetypes.json").write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8")


# ---------- 先验映射 ----------

def test_priors_loading(tmp_path):
    _priors(tmp_path, {"A-Nadu, Winged Wisdom": "Combo", "_comment": "x", "坏值": "Bogus"})
    m = stats.load_priors(tmp_path)
    assert m == {"A-Nadu, Winged Wisdom": ["Combo"]}  # _comment 与非法值被过滤


def test_priors_supports_multi_label(tmp_path):
    """值可以是数组：多轴卡组（如始霸埃泰力 = Ramp + Combo）。"""
    _priors(tmp_path, {
        "Etali, Primal Conqueror": ["Combo", "Ramp"],
        "Nadu": "Combo",
    })
    m = stats.load_priors(tmp_path)
    assert m["Etali, Primal Conqueror"] == ["Combo", "Ramp"]
    assert m["Nadu"] == ["Combo"]


def test_priors_drops_only_bad_label(tmp_path):
    """数组里混入非法标签时只丢那一个，不整条作废。"""
    _priors(tmp_path, {"X": ["Ramp", "Bogus"]})
    assert stats.load_priors(tmp_path) == {"X": ["Ramp"]}


def test_parse_tags_accepts_all_shapes():
    assert stats.parse_tags(None) == []
    assert stats.parse_tags("") == []
    assert stats.parse_tags("Ramp") == ["Ramp"]
    assert stats.parse_tags("Ramp,Combo") == ["Ramp", "Combo"]
    assert stats.parse_tags(["Combo", "Ramp"]) == ["Combo", "Ramp"]
    assert stats.parse_tags("Ramp,Bogus") == ["Ramp"]
    assert stats.parse_tags("Ramp,Ramp") == ["Ramp"]  # 去重
    assert stats.parse_tags(123) == []


def test_join_tags_normalizes():
    assert stats.join_tags(["Ramp", "Combo"]) == "Ramp,Combo"
    assert stats.join_tags("Combo") == "Combo"
    assert stats.join_tags([]) == ""
    assert stats.join_tags("Bogus") == ""


def test_priors_missing_file(tmp_path):
    assert stats.load_priors(tmp_path) == {}


# ---------- 手动打标优先于先验 ----------

def test_user_overrides_prior(tmp_path):
    conn, _ = _store(tmp_path)
    _priors(tmp_path, {"Nadu": "Combo"})
    conn.execute("INSERT INTO opponent_profiles VALUES('Nadu', 'Aggro', NULL, 0)")
    conn.commit()
    m = stats.archetype_map(conn, tmp_path)
    assert m["Nadu"] == ["Aggro"]  # 手动 > 先验


def test_user_multi_tag_overrides_prior(tmp_path):
    """手动标多标签时，整体覆盖先验（不是追加）。"""
    conn, _ = _store(tmp_path)
    _priors(tmp_path, {"X": "Combo"})
    conn.execute("INSERT INTO opponent_profiles VALUES('X', 'Ramp,Combo', NULL, 0)")
    conn.commit()
    m = stats.archetype_map(conn, tmp_path)
    assert m["X"] == ["Ramp", "Combo"]


def test_profiles_table_missing_degrades(tmp_path):
    """旧库无 profiles 表时 archetype_map 不崩溃。"""
    conn, _ = _store(tmp_path)
    conn.execute("DROP TABLE opponent_profiles")
    m = stats.archetype_map(conn, tmp_path)
    assert isinstance(m, dict)


# ---------- matchups 细分 ----------

def test_matchups_play_draw_split(tmp_path):
    conn, _ = _store(tmp_path)
    rows = stats.matchups(conn, exclude_abnormal=False)
    assert rows, "应至少聚合出一个对手主将"
    r = rows[0]
    assert r["on_play"]["n"] + r["on_draw"]["n"] <= r["n"]
    # fixtures 的对手主将 grpId 应出现在 key 里
    assert all(r["key"].isdigit() for r in rows)


def test_matchups_excludes_abnormal(tmp_path):
    conn, _ = _store(tmp_path, n=3, play_draw="draw")
    with_abn = stats.matchups(conn, exclude_abnormal=False)
    without = stats.matchups(conn, exclude_abnormal=True)
    # fixtures 造的对局可能被判异常，口径开关应有效（排除后 <= 全量）
    assert all(r["archetype"] == [] for r in without)  # 无先验文件 → 空标签集合
    assert sum(r["n"] for r in without) <= sum(r["n"] for r in with_abn)


def test_matchups_sort_modes(tmp_path):
    """sort="count" 按场次降序（默认）；sort="recent" 按最近相遇时间降序。

    打标场景要的是后者：最近碰到的对手排在最前，不用翻页找。
    """
    conn, _ = _store(tmp_path)
    conn.execute("DELETE FROM commanders")
    conn.execute("DELETE FROM matches")
    for mid, ts, gid in [("m1", 1000, "111"), ("m2", 2000, "111"),
                         ("m3", 3000, "111"), ("m4", 9000, "222")]:
        conn.execute("INSERT INTO matches(match_id, my_seat, start_time, my_result) "
                     "VALUES(?, 1, ?, 'win')", (mid, ts))
        conn.execute("INSERT INTO commanders(match_id, seat, grp_id) VALUES(?, 2, ?)",
                     (mid, gid))
    conn.commit()

    by_count = stats.matchups(conn, sort="count")
    assert [r["key"] for r in by_count] == ["111", "222"]    # 3 场 > 1 场
    by_recent = stats.matchups(conn, sort="recent")
    assert [r["key"] for r in by_recent] == ["222", "111"]   # 9000 比 3000 新

    assert by_recent[0]["last_time"] == 9000
    assert by_count[0]["last_time"] == 3000


def test_matchups_recent_puts_null_time_last(tmp_path):
    """start_time 缺失的记录不能排到有时间的记录前面。"""
    conn, _ = _store(tmp_path)
    conn.execute("DELETE FROM commanders")
    conn.execute("DELETE FROM matches")
    for mid, ts, gid in [("m1", 5000, "111"), ("m2", None, "222")]:
        conn.execute("INSERT INTO matches(match_id, my_seat, start_time, my_result) "
                     "VALUES(?, 1, ?, 'win')", (mid, ts))
        conn.execute("INSERT INTO commanders(match_id, seat, grp_id) VALUES(?, 2, ?)",
                     (mid, gid))
    conn.commit()

    by_recent = stats.matchups(conn, sort="recent")
    assert [r["key"] for r in by_recent] == ["111", "222"], "NULL 时间应排最后"
    assert by_recent[1]["last_time"] is None


def test_commanders_api_accepts_both_sorts(tmp_path, monkeypatch):
    """接口层回归：`sort` 只属于 rows，不能一并传给 `commander_coverage`。

    `stats.matchups` 有 sort 参数而 `commander_coverage` 没有。早前把同一个
    kwargs 词典传给两者，`/api/commanders` 直接 TypeError → **整个接口 500**
    （对手主将档案页全白）。单测只覆盖到 stats 层，接口层是空白，所以补这条。
    """
    from fastapi.testclient import TestClient

    from app import main
    from app.config import Config

    conn, _ = _store(tmp_path)
    conn.execute("DELETE FROM commanders")
    conn.execute("DELETE FROM matches")
    for mid, ts, gid in [("m1", 1000, "111"), ("m2", 2000, "111"),
                         ("m3", 9000, "222")]:
        conn.execute("INSERT INTO matches(match_id, my_seat, start_time, my_result) "
                     "VALUES(?, 1, ?, 'win')", (mid, ts))
        conn.execute("INSERT INTO commanders(match_id, seat, grp_id) VALUES(?, 2, ?)",
                     (mid, gid))
    conn.commit()

    monkeypatch.setattr(main, "_conn", conn)
    monkeypatch.setattr(main, "cfg",
                        Config({"db_path": str(tmp_path / "t.db")}, tmp_path))
    client = TestClient(main.app)

    r = client.get("/api/commanders", params={"sort": "count"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert [row["key"] for row in body["rows"]] == ["111", "222"]  # 2 场 > 1 场
    assert "coverage" in body and "total" in body["coverage"]

    r = client.get("/api/commanders", params={"sort": "recent"})
    assert r.status_code == 200, r.text
    assert [row["key"] for row in r.json()["rows"]] == ["222", "111"]

    assert client.get("/api/commanders", params={"sort": "bogus"}).status_code == 422
    client.close()
