# -*- coding: utf-8 -*-
"""对局进行中启动面板时，完成事件不能被静默吞掉（2026-09-16 实测的真 BUG）。

现象：2026-09-16 17:57 的一场对局在页面上永远停在「待确认」，先后手也是 `–`。
排查：日志里**有**完整的 `MatchGameRoomStateType_MatchCompleted`（`finalMatchResult`
带 matchId、`winningTeamId=1`、`Reason_Concede`），解析器在一次性回放、分段回放、
以及「每喂一条就 take 一次」的慢轮询下**都能正确算出结果**。

根因：面板是 17:57:23 启动的，而这场 17:57:16 开始。启动**回填**看到了开局并落库
（所以库里有一行、结果是 NULL），随后接手的**监听器是全新的 SessionBuilder**、
从没见过这场；18:01 的 `finalMatchResult` 按 matchId 找不到对局 → 只进
`_pending_fmr` 然后**永远消失**（没有任何日志、没有任何计数）。

所以这里钉住两件事：
1. builder 必须把「认领不了的结果」**传出来**，不能自己吞掉；
2. DB 层要能按 match_id 兜底补写，且**只写还没有结果的**行。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import store
from app.events import SessionBuilder

MYID = "ME"
MID = "m-1"


def completed_record(mid: str = MID, winner: int = 1,
                     reason: str = "ResultReason_Concede") -> str:
    """一条 MatchCompleted 逻辑记录（头部行与 JSON 体在真实日志里是分开的，
    但两者合起来才含 MatchCompleted/finalMatchResult 两个关键串）。"""
    return json.dumps({
        "matchGameRoomStateChangedEvent": {
            "gameRoomInfo": {
                "stateType": "MatchGameRoomStateType_MatchCompleted",
                "finalMatchResult": {
                    "matchId": mid,
                    "resultList": [
                        {"scope": "MatchScope_Game", "result": "ResultType_WinLoss",
                         "winningTeamId": winner, "reason": reason},
                        {"scope": "MatchScope_Match", "result": "ResultType_WinLoss",
                         "winningTeamId": winner, "reason": reason},
                    ],
                },
            }
        }
    })


def test_unclaimed_result_is_handed_out_not_swallowed():
    """builder 没见过这场时，结果必须出现在 `orphan_results` 里。"""
    sb = SessionBuilder(source="log", my_player_id=MYID)
    sb.feed(completed_record())
    res = sb.take()
    assert res.matches == []                       # 这场本来就不归它
    orphans = dict(res.orphan_results)
    assert MID in orphans, "认领不了的结果被静默吞掉了"
    scopes = [e.get("scope") for e in orphans[MID]["resultList"]]
    assert scopes == ["MatchScope_Game", "MatchScope_Match"]


def _add_match(conn, match_id=MID, seat=1, result=None):
    conn.execute(
        """INSERT INTO matches(match_id, source, event_id, start_time, my_seat, my_result)
           VALUES(?, 'log', 'Play_Brawl_Historic', 0, ?, ?)""",
        (match_id, seat, result),
    )
    conn.execute(
        "INSERT INTO games(match_id, game_no, result, reason) VALUES(?, 1, NULL, NULL)",
        (match_id,),
    )
    conn.commit()


@pytest.fixture
def db(tmp_path):
    conn = store.connect(tmp_path / "orphan.db")
    yield conn
    conn.close()


def test_apply_orphan_result_fills_a_pending_match(db):
    """库里那行还没有结果 → 按 id 补上胜负、结束原因与逐局结果。"""
    _add_match(db)
    assert store.apply_orphan_result(db, MID, [
        {"scope": "MatchScope_Game", "winningTeamId": 1, "reason": "ResultReason_Concede"},
        {"scope": "MatchScope_Match", "winningTeamId": 1, "reason": "ResultReason_Concede"},
    ]) is True
    row = db.execute("SELECT my_result, end_reason FROM matches WHERE match_id=?", (MID,)).fetchone()
    assert tuple(row) == ("win", "Concede")
    game = db.execute("SELECT result, reason FROM games WHERE match_id=?", (MID,)).fetchone()
    assert tuple(game) == ("win", "Concede")


def test_apply_orphan_result_is_idempotent_and_never_overwrites(db):
    """重复调用安全；已有结果的绝不覆盖（take() 会反复带出待确认结果）。"""
    _add_match(db)
    payload = [{"scope": "MatchScope_Match", "winningTeamId": 1, "reason": "ResultReason_Concede"}]
    assert store.apply_orphan_result(db, MID, payload) is True
    assert store.apply_orphan_result(db, MID, payload) is False      # 第二次不再写
    # 已经判过负的对局，不能被后到的「胜」改掉
    db.execute("UPDATE matches SET my_result='loss' WHERE match_id=?", (MID,))
    db.commit()
    assert store.apply_orphan_result(db, MID, payload) is False
    assert db.execute("SELECT my_result FROM matches WHERE match_id=?", (MID,)).fetchone()[0] == "loss"


def test_apply_orphan_result_refuses_to_guess(db):
    """没有座位就判不出胜负——宁可不写，也不编一个结果出来。"""
    _add_match(db, match_id="no-seat", seat=None)
    assert store.apply_orphan_result(db, "no-seat", [
        {"scope": "MatchScope_Match", "winningTeamId": 1, "reason": "ResultReason_Concede"},
    ]) is False
    assert db.execute("SELECT my_result FROM matches WHERE match_id='no-seat'").fetchone()[0] is None
    # 库里根本没有这场 → 也不写（交给上层重试）
    assert store.apply_orphan_result(db, "unknown", [
        {"scope": "MatchScope_Match", "winningTeamId": 1, "reason": "ResultReason_Concede"},
    ]) is False


def test_apply_orphan_result_maps_winner_by_seat(db):
    """winningTeamId 与自己的座位不同 → 判负（本项目的既有假设 seat == teamId）。"""
    _add_match(db, match_id="lost", seat=2)
    store.apply_orphan_result(db, "lost", [
        {"scope": "MatchScope_Match", "winningTeamId": 1, "reason": "ResultReason_Concede"},
    ])
    assert db.execute("SELECT my_result FROM matches WHERE match_id='lost'").fetchone()[0] == "loss"
