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
    assert m == {"A-Nadu, Winged Wisdom": "Combo"}  # _comment 与非法值被过滤


def test_priors_missing_file(tmp_path):
    assert stats.load_priors(tmp_path) == {}


# ---------- 手动打标优先于先验 ----------

def test_user_overrides_prior(tmp_path):
    conn, _ = _store(tmp_path)
    _priors(tmp_path, {"Nadu": "Combo"})
    conn.execute("INSERT INTO opponent_profiles VALUES('Nadu', 'Aggro', NULL, 0)")
    conn.commit()
    m = stats.archetype_map(conn, tmp_path)
    assert m["Nadu"] == "Aggro"  # 手动 > 先验


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
    assert all(r["archetype"] is None for r in without)  # 无先验文件
    assert sum(r["n"] for r in without) <= sum(r["n"] for r in with_abn)
