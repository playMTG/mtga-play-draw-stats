# -*- coding: utf-8 -*-
"""时间范围（顶部「今天/本周/本月/总对局」与底部「本周」）的口径与边界。

用户口径（2026-09-20）：「这里也像底下一样，按今天、本周、本月、总对局来分类
筛选。下面的除了今天、昨天外，加上本周的筛选。」

两条容易写错、这里专门盯住的：
① **本周从周一起算**（与 `trend_weekly` 的分组一致），不是「最近 7 天」；
② `overview` 的 `today` 块**恒为今天**，与所选范围无关——三张卡下面那行
   「今日…」靠它，否则范围切到「本周」时那行会拿本周的数字自称「今日」。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from app import stats, store
from app.insights import _range_plain, daily_report


@pytest.fixture
def db(tmp_path):
    c = store.connect(tmp_path / 'ranges.db')
    yield c
    c.close()


def add(c, mid, day: date, result='win', pd='play'):
    ts = int(datetime.combine(day, datetime.min.time()).timestamp() * 1000)
    c.execute(
        'INSERT INTO matches(match_id,start_time,event_id,my_deck_tag,play_draw,'
        'my_result,my_seat) VALUES(?,?,?,?,?,?,1)',
        (mid, ts, 'Play_Brawl_Historic', 'test', pd, result))


TODAY = datetime.now().date()
MONDAY = TODAY - timedelta(days=TODAY.weekday())

# `stats.overview` 的 `today` 可注入，所以这一组用固定的「今天」（2026-09-20，周日）
# 建库——否则测试撞上周一那天，「本周」与「今天」就是同一天，断言会失去区分度。
FIXED = date(2026, 9, 20)
FIXED_MON = date(2026, 9, 14)      # 那一周的周一
FIXED_SUN_BEFORE = date(2026, 9, 13)


def test_week_starts_on_monday_and_ends_today():
    assert stats.range_bounds("week", TODAY) == (MONDAY, TODAY)
    # 周日（weekday=6）往前推 6 天；周一（weekday=0）就是它自己——别写成「最近 7 天」
    for offset in range(7):
        ref = MONDAY + timedelta(days=offset)
        lo, hi = stats.range_bounds("week", ref)
        assert lo == MONDAY and hi == ref, f"周内第 {offset} 天算错了"


def test_range_bounds_keywords_and_dates():
    assert stats.range_bounds(None, TODAY) is None
    assert stats.range_bounds("all", TODAY) is None
    assert stats.range_bounds("today", TODAY) == (TODAY, TODAY)
    assert stats.range_bounds("yesterday", TODAY) == (TODAY - timedelta(days=1),
                                                     TODAY - timedelta(days=1))
    assert stats.range_bounds("month", TODAY) == (TODAY.replace(day=1), TODAY)
    assert stats.range_bounds("2026-01-08", TODAY) == (date(2026, 1, 8), date(2026, 1, 8))


def test_range_cond_shape_and_invalid_values():
    assert stats.range_cond(None) == ("", [])
    assert stats.range_cond("all") == ("", [])
    sql, args = stats.range_cond("today", TODAY)
    assert sql.endswith("= ?") and args == [TODAY.isoformat()]
    sql, args = stats.range_cond("week", TODAY)
    assert "BETWEEN ? AND ?" in sql and args == [MONDAY.isoformat(), TODAY.isoformat()]
    # 非法值必须抛 ValueError，接口层才好回 422；静默退回「全部」会让页面显示错数据
    for bad in ("下周", "2026-13-01", "week_ago"):
        with pytest.raises(ValueError):
            stats.range_bounds(bad, TODAY)


def test_overview_week_matches_manual_count(db):
    add(db, 'mon', FIXED_MON)
    add(db, 'mon2', FIXED_MON, result='loss')
    add(db, 'today', FIXED, pd='draw')
    add(db, 'last-sunday', FIXED_SUN_BEFORE)               # 上一周，不该算进来
    add(db, 'tomorrow', FIXED + timedelta(days=1))         # 本周还没到的日子
    db.commit()

    week = stats.overview(db, range_key="week", today=FIXED)
    assert week["range"] == "week"
    assert week["total"]["n"] == 3, "本周应只算周一至今"
    assert week["total"]["wins"] == 2
    assert week["play_draw_rates"]["play"] == 2
    assert week["play_draw_rates"]["draw"] == 1
    # 全史仍是 5 场（含上周日与明天）
    assert stats.overview(db, range_key="all", today=FIXED)["total"]["n"] == 5
    # 单日
    assert stats.overview(db, range_key="today", today=FIXED)["total"]["n"] == 1
    # 上一周那几天归上一周
    assert stats.overview(db, range_key="week",
                          today=FIXED - timedelta(days=7))["total"]["n"] == 1


def test_overview_today_block_is_today_not_the_range(db):
    add(db, 'mon', FIXED_MON, result='loss')
    add(db, 'today', FIXED)
    add(db, 'older', FIXED_MON - timedelta(days=3), result='loss')
    db.commit()

    week = stats.overview(db, range_key="week", today=FIXED)
    assert week["today"]["total"]["n"] == 1, "today 块必须恒为今天"
    assert week["today"]["total"]["wins"] == 1
    # 范围是「本周」时两块数字不同，前端才能一眼看出有没有串
    assert week["total"]["n"] == 2
    assert week["total"]["wins"] == 1
    assert week["today"]["total"]["n"] != week["total"]["n"]
    # 换成「本月」也一样：today 块不跟着走
    month = stats.overview(db, range_key="month", today=FIXED)
    assert month["today"]["total"]["n"] == 1
    assert month["total"]["n"] == 3


def test_match_list_week_only_returns_this_week(db):
    add(db, 'mon', MONDAY)
    add(db, 'today', TODAY)
    add(db, 'last-sunday', MONDAY - timedelta(days=1))
    db.commit()

    got = {r["match_id"] for r in stats.match_list(db, range_key="week")["rows"]}
    assert got == {"mon", "today"}
    assert stats.match_list(db, range_key="week")["total"] == 2
    assert stats.match_list(db)["total"] == 3
    # day= 与 range= 是求交：给了具体某天就只剩那天
    assert stats.match_list(db, day=TODAY.isoformat(), range_key="week")["total"] == 1
    # 上一周的周日不在本周里
    assert "last-sunday" not in got


def test_daily_report_week_is_a_summary_not_a_daily_broadcast(db):
    add(db, 'mon', MONDAY)
    add(db, 'mon2', MONDAY, result='loss', pd='draw')
    add(db, 'today', TODAY)
    add(db, 'last-sunday', MONDAY - timedelta(days=1), result='loss')
    db.commit()

    r = daily_report(db, range_key="week")
    assert r["range"] == "week", "响应要回显范围，前端据此不回写日期控件"
    assert r["date"] == TODAY.isoformat(), "范围报告的 date 是范围末"
    assert r["summary"]["n"] == 3
    assert r["highlights"] == [], "周报不跑按天写的选材引擎（模板里全是「今天」）"
    assert r["plain"].startswith("本周 ")
    assert "共 3 场" in r["plain"] and "2 胜 1 负" in r["plain"]
    assert "先手胜率" in r["plain"] and "后手胜率" in r["plain"]
    # 比较基线必须落在所选范围之前，不能与范围本身重叠
    assert "范围之前 30 个自然日" in r["comparison"]["baseline_window"]
    assert "last-sunday" not in {x["match_id"] for x in r["highlights"]}


def test_daily_report_week_of_one_day_still_summarises(db):
    """本周只打了一天也要出汇总句，不能退化成「没有对局」。"""
    add(db, 'today', TODAY)
    db.commit()
    r = daily_report(db, range_key="week")
    assert r["summary"]["n"] == 1
    assert "1 天有对局" in r["plain"], r["plain"]


def test_daily_report_single_day_is_unchanged(db):
    add(db, 'today', TODAY)
    db.commit()
    r = daily_report(db, TODAY.isoformat())
    assert r["range"] is None
    assert r["date"] == TODAY.isoformat()
    assert "所选日期之前 30 个自然日" in r["comparison"]["baseline_window"]


def test_range_plain_empty_and_labels():
    assert _range_plain("week", {"n": 0}, 0, {}) == "本周在当前筛选下没有已记录对局。"
    assert _range_plain("month", {"n": 0}, 0, {}) == "本月在当前筛选下没有已记录对局。"
    text = _range_plain("week", {"n": 10, "wins": 6, "losses": 4, "win_rate": {"wr": 60.0}},
                        3, {"play_wr": {"wr": 50.0, "n": 4}, "draw_wr": {"wr": 66.7, "n": 6}})
    assert text == ("本周 3 天有对局，共 10 场 · 6 胜 4 负 · 胜率 60.0%；"
                    "先手胜率 50.0%（4 场），后手胜率 66.7%（6 场）。")
    # 某一边一场都没有时不要写「后手胜率 None%（0 场）」
    only_play = _range_plain("week", {"n": 4, "wins": 2, "losses": 2, "win_rate": {"wr": 50.0}},
                             2, {"play_wr": {"wr": 50.0, "n": 4}, "draw_wr": {"wr": None, "n": 0}})
    assert "后手" not in only_play and "先手胜率 50.0%（4 场）" in only_play


def test_api_rejects_bad_range(db, monkeypatch):
    """接口层要把非法范围变成 422，而不是静默按「全部」返回。"""
    from fastapi.testclient import TestClient
    from app import main

    monkeypatch.setattr(main, "get_conn", lambda: db)
    client = TestClient(main.app)
    assert client.get("/api/overview", params={"range": "下周"}).status_code == 422
    assert client.get("/api/matches", params={"range": "2026-13-01"}).status_code == 422
    assert client.get("/api/daily", params={"range": "2026-13-01"}).status_code == 422
