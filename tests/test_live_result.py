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


def test_c1_late_result_after_next_match_started_routes_by_match_id():
    """C1：下一场已 Playing 后，上一场的 finalMatchResult 不得写入新对局。"""
    sb = SessionBuilder(source="log", my_player_id=fx.ME)
    sb.feed(fx.match_start("m-old"))
    sb.feed(fx.turn_info(1, active=1))
    sb.feed(fx.match_completed())
    sb.feed(fx.match_start("m-new"))
    sb.feed(fx.turn_info(1, active=2))
    # 上一场结果迟到（真实日志带 matchId）
    sb.feed(fx.final_result(winner_match=1, match_id="m-old"))
    res = sb.close()
    by_id = {m.match_id: m for m in res.matches}
    assert by_id["m-old"].my_result == "win"
    assert by_id["m-old"].end_reason == "Concede"
    assert by_id["m-new"].my_result is None
    assert by_id["m-new"].end_reason is None


def test_c1_reverse_order_results_both_assigned():
    """C1：两场结果逆序到达，各自按 matchId 归位。"""
    sb = SessionBuilder(source="log", my_player_id=fx.ME)
    sb.feed(fx.match_start("m-a"))
    sb.feed(fx.turn_info(1, active=1))
    sb.feed(fx.match_completed())
    sb.feed(fx.match_start("m-b"))
    sb.feed(fx.turn_info(1, active=1))
    sb.feed(fx.match_completed())
    # 逆序：先 m-b 后 m-a
    sb.feed(fx.final_result(winner_match=1, match_id="m-b"))
    sb.feed(fx.final_result(winner_match=2, match_id="m-a"))
    res = sb.close()
    by_id = {m.match_id: m for m in res.matches}
    assert by_id["m-a"].my_result == "loss"
    assert by_id["m-b"].my_result == "win"


def test_c1_result_before_target_queued_then_applied():
    """C1：结果先于目标对局可见时入队，目标出现后再写入。"""
    sb = SessionBuilder(source="log", my_player_id=fx.ME)
    # 结果先到（异常但可能发生：监听错过 Playing 后又读到结果行）
    sb.feed(fx.final_result(winner_match=1, match_id="m-late-start"))
    assert sb._pending_fmr  # 尚无目标，先排队
    sb.feed(fx.match_start("m-late-start"))
    res = sb.close()
    (m,) = res.matches
    assert m.my_result == "win"
    assert m.end_reason == "Concede"


def test_c1_legacy_no_match_id_still_targets_unresolved_current():
    """无 matchId 的旧格式：保持兼容，写给尚未有结果的当前对局。

    真实日志 finalMatchResult 均带 matchId（2026-09-11 抽样），
    C1 的串场路径以 matchId 路由为准。
    """
    sb = SessionBuilder(source="log", my_player_id=fx.ME)
    sb.feed(fx.match_start("m-cur"))
    sb.feed(fx.turn_info(1, active=1))
    sb.feed(fx.final_result(winner_match=1, match_id=None))
    res = sb.close()
    (m,) = res.matches
    assert m.match_id == "m-cur"
    assert m.my_result == "win"


def test_c2_bo3_second_game_after_first_turn_concede():
    """C2：第一局仅 turn1 即结束时，第二局先后手不得丢失。"""
    sb = SessionBuilder(source="log", my_player_id=fx.ME)
    mid = "m-bo3-scoop"
    sb.feed(fx.match_start(mid))
    sb.feed(fx.turn_info(1, active=2, ts=fx.T1))  # 第1局：我在 seat1 → 后手
    sb.feed(fx.game_result(winner=2, match_id=mid, ts=fx.T2))  # 第1局对手胜
    sb.feed(fx.turn_info(1, active=1, ts=fx.T3))  # 第2局：我先手
    sb.feed(fx.game_result(winner=1, match_id=mid, ts=fx.T4))  # 第2局我胜
    sb.feed(fx.final_result(winner_match=1, match_id=mid, games=(), ts=fx.T4))
    # 整场结果需单独给：games=() 时仍会有 MatchScope_Match
    res = sb.close()
    (m,) = res.matches
    assert len(m.games) >= 2
    g1, g2 = m.games[0], m.games[1]
    assert g1.play_draw == "draw" and g1.result == "loss"
    assert g2.play_draw == "play" and g2.result == "win"
    assert m.my_result == "win"
    assert m.play_draw == "draw"  # 冗余 = 第1局


def test_c2_duplicate_turn1_same_game_does_not_advance():
    """重复的 turn1（未结束本局）不得误增局号。"""
    sb = SessionBuilder(source="log", my_player_id=fx.ME)
    sb.feed(fx.match_start("m-dup"))
    sb.feed(fx.turn_info(1, active=1, ts=fx.T1))
    sb.feed(fx.turn_info(1, active=1, ts=fx.T1))  # 同一局重复状态
    sb.feed(fx.final_result(winner_match=1, match_id="m-dup"))
    res = sb.close()
    (m,) = res.matches
    assert len([g for g in m.games if g.play_draw or g.result]) >= 1
    assert m.games[0].play_draw == "play"
    assert len(m.games) == 1 or all(g.play_draw is None for g in m.games[1:])

