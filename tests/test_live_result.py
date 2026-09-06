# -*- coding: utf-8 -*-
"""监听路径回归：take() 之后迟到的 finalMatchResult 必须能回填（2026-09-06
今日场次胜负全丢的根因），且内容级去重不误判。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import fixtures as fx
from app.events import SessionBuilder


def test_late_final_result_after_take_is_reemitted():
    sb = SessionBuilder(source="log", my_player_id=fx.ME)
    sb.feed(fx.match_start())
    sb.feed(fx.turn_info(turn=1, active=2))
    sb.feed(fx.match_completed())
    first = sb.take()
    assert len(first.matches) == 1
    assert first.matches[0].my_result is None  # 结果还没到就闭合了

    # 迟到的 finalMatchResult（真实 Brawl 场次实测会晚于 MatchCompleted）
    sb.feed(fx.final_result(winner_match=1))
    second = sb.take()
    assert len(second.matches) == 1, "迟到结果必须随下轮 take 重新带上"
    assert second.matches[0].match_id == first.matches[0].match_id
    assert second.matches[0].my_result == "win"

    # 已回填且无新数据 → 不再重复带上
    third = sb.take()
    assert third.matches == []


def test_final_result_content_dedup_not_id_based():
    sb = SessionBuilder(source="log", my_player_id=fx.ME)
    sb.feed(fx.match_start())
    sb.feed(fx.final_result(winner_match=1))
    sb.feed(fx.turn_info(turn=1, active=1))
    sb.feed(fx.match_completed())
    res = sb.close()
    assert len(res.matches) == 1
    assert res.matches[0].my_result == "win"
    assert res.matches[0].end_reason == "Concede"


def test_identical_result_blocks_across_matches():
    """同一天多场同结论（内容完全相同的 resultList）不得互相误判为重复。"""
    sb = SessionBuilder(source="log", my_player_id=fx.ME)
    for mid in ("m-1", "m-2", "m-3"):
        sb.feed(fx.match_start(match_id=mid))
        sb.feed(fx.final_result(winner_match=1))  # 三场内容完全一样
        sb.feed(fx.match_completed())
    res = sb.close()
    assert [m.my_result for m in res.matches] == ["win", "win", "win"]
    assert all(m.end_reason == "Concede" for m in res.matches)


def test_different_results_both_processed():
    """两场不同内容的finalResult（地址可能复用）不得互相误判为重复。"""
    sb = SessionBuilder(source="log", my_player_id=fx.ME)
    for mid, winner in (("m-1", 1), ("m-2", 2)):
        sb.feed(fx.match_start(match_id=mid))
        sb.feed(fx.final_result(winner_match=winner))
        sb.feed(fx.match_completed())
    res = sb.close()
    assert [m.my_result for m in res.matches] == ["win", "loss"]
