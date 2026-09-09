# -*- coding: utf-8 -*-
"""被针对指数测试：统计原语精度 + 合成数据端到端。"""
from __future__ import annotations

import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import stats, store
from app.targeting import (binom_cdf, binom_sf, chi2_sf, luck_label,
                           max_loss_streak, p_to_score, streak_sf)


# ---------- 统计原语 ----------

def test_chi2_sf_known_values():
    assert abs(chi2_sf(3.841, 1) - 0.050) < 2e-3
    assert abs(chi2_sf(5.991, 2) - 0.050) < 2e-3
    assert abs(chi2_sf(10.828, 1) - 0.001) < 2e-4
    assert chi2_sf(0, 5) == 1.0
    assert chi2_sf(1000, 1) < 1e-100


def test_binom_complement_symmetry():
    for n, k, p in [(100, 30, 0.5), (40, 5, 0.1), (200, 150, 0.5)]:
        cdf = binom_cdf(k, n, p)
        sf = binom_sf(k + 1, n, p)
        assert abs(cdf + sf - 1.0) < 1e-9
    assert binom_cdf(0, 40, 0.5) == abs(0.5 ** 40)
    assert binom_sf(0, 10, 0.3) == 1.0
    assert binom_cdf(10, 10, 0.3) == 1.0


def test_p_to_score_mapping():
    assert p_to_score(0.5) == 50.0
    assert p_to_score(0.10) == 50.0
    assert p_to_score(1e-5) == 100.0
    assert p_to_score(1e-3) > p_to_score(1e-2) > p_to_score(0.05) >= 50
    assert p_to_score(float("nan")) == 50.0


def test_streak_helpers():
    assert max_loss_streak(["win", "loss", "loss", "win", "loss"]) == 2
    assert max_loss_streak(["loss"] * 5) == 5
    assert max_loss_streak([]) == 0
    # 连败越长越不可能；胜率越低长连败越常见
    assert streak_sf(15, 100, 0.5) < streak_sf(8, 100, 0.5)
    assert streak_sf(8, 100, 0.3) > streak_sf(8, 100, 0.6)
    assert streak_sf(1, 100, 0.5) == 1.0


def test_luck_label_bands():
    assert luck_label(10) == "欧皇"
    assert luck_label(40) == "手气不错"
    assert luck_label(60) == "正常人"
    assert luck_label(80) == "有点邪门"
    assert luck_label(95) == "建议卸载重装"


# ---------- 合成数据端到端 ----------

_NOW = int(time.time() * 1000)


def _conn(tmp_path):
    return store.connect(tmp_path / "t.db")


def _match(conn, i, *, pd="play", res="win", ts=None, mull=0, grp=None):
    ts = ts or _NOW - 5 * 86_400_000
    conn.execute(
        "INSERT INTO matches(match_id, my_seat, play_draw, my_result, "
        "start_time, is_abnormal, is_bot) VALUES(?,?,?,?,?,0,0)",
        (f"m{i}", 0, pd, res, ts),
    )
    if mull:
        conn.execute(
            "INSERT INTO mulligans(match_id, game_no, seat, kept_on) "
            "VALUES(?,?,?,?)", (f"m{i}", 1, 0, mull))
    if grp:
        conn.execute(
            "INSERT INTO commanders(match_id, seat, grp_id) VALUES(?,?,?)",
            (f"m{i}", 1, grp))


def test_balanced_luck_scores_normal(tmp_path):
    conn = _conn(tmp_path)
    for i in range(60):
        _match(conn, i, pd="play" if i % 2 == 0 else "draw",
               res="win" if i % 2 == 0 else "loss")
    conn.commit()
    r = stats.targeting_index(conn, window_days=None)
    a = r["dimensions"]["play_draw"]
    c = r["dimensions"]["mulligan"]
    d = r["dimensions"]["streak"]
    assert a["enough"] and a["score"] <= 50
    assert not c["enough"] and c["score"] is None  # 缺失不再当未调度
    assert d["score"] is None  # 混合连败仅描述
    assert r["composite"] is None


def test_draw_heavy_and_mulligan_cursed(tmp_path):
    conn = _conn(tmp_path)
    for i in range(100):
        _match(conn, i, pd="draw", res="loss" if i % 5 else "win", mull=2)
    conn.commit()
    r = stats.targeting_index(conn, window_days=None)
    assert r["dimensions"]["play_draw"]["score"] == 100.0  # 0/100 先手
    assert r["dimensions"]["mulligan"]["n"] == 100
    assert r["dimensions"]["mulligan"]["score"] is None  # 无可比基线不判异常
    assert r["composite"] is None


def test_insufficient_sample_excluded(tmp_path):
    conn = _conn(tmp_path)
    for i in range(10):
        _match(conn, i, pd="draw", res="loss")
    conn.commit()
    r = stats.targeting_index(conn, window_days=None)
    assert all(not d["enough"] for d in r["dimensions"].values())
    assert r["composite"] is None


def test_window_filters_old_matches(tmp_path):
    conn = _conn(tmp_path)
    for i in range(30):  # 全部 40 天前
        _match(conn, i, pd="draw", res="loss", ts=_NOW - 40 * 86_400_000)
    conn.commit()
    r7 = stats.targeting_index(conn, window_days=7)
    assert r7["dimensions"]["play_draw"]["n"] == 0
    rall = stats.targeting_index(conn, window_days=None)
    assert rall["dimensions"]["play_draw"]["n"] == 30


def test_nemeses_detected(tmp_path):
    conn = _conn(tmp_path)
    # 克星主将：3+ 场全败
    for i in range(30):
        _match(conn, i, pd="draw", res="loss", grp=900001)
    for i in range(100, 115):  # 另一个常胜对手
        _match(conn, i, pd="play", res="win", grp=900002)
    conn.execute("UPDATE matches SET event_id='Play_Brawl_Historic'")
    conn.commit()
    r = stats.targeting_index(conn, window_days=None, root=None)
    names = [x["name"] for x in r["nemeses"]]
    assert "grpId:900001" in names
    assert "grpId:900002" not in names
    assert r["nemeses"][0]["wr"] <= 40


def test_abnormal_and_bot_excluded(tmp_path):
    conn = _conn(tmp_path)
    for i in range(25):
        _match(conn, i, pd="draw", res="loss")
    conn.execute("UPDATE matches SET is_abnormal=1 WHERE match_id='m0'")
    conn.execute("UPDATE matches SET is_bot=1 WHERE match_id='m1'")
    conn.commit()
    r = stats.targeting_index(conn, window_days=None)
    assert r["dimensions"]["play_draw"]["n"] == 23
    r_all = stats.targeting_index(conn, window_days=None,
                                  exclude_abnormal=False, exclude_bot=False)
    assert r_all["dimensions"]["play_draw"]["n"] == 25
