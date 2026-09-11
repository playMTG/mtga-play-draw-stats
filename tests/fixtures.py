# -*- coding: utf-8 -*-
"""合成日志片段：结构对齐真实 MTGA 详细日志（脱敏，纯虚构）。"""
from __future__ import annotations

ME = "ME1234567890ABCDEF"
OPP = "OPP9876543210FEDCBA"

T0, T1, T2, T3, T4 = (
    "1788599000000", "1788599001000", "1788599050000",
    "1788599100000", "1788599110000",
)


def _players(me_seat=1, opp_seat=2):
    return (
        f'{{"systemSeatId":{me_seat},"teamId":{me_seat},"playerName":"Tester",'
        f'"userId":"{ME}"}},'
        f'{{"systemSeatId":{opp_seat},"teamId":{opp_seat},"playerName":"Opponent",'
        f'"platformId":"PC","userId":"{OPP}"}}'
    )


def match_start(match_id="m-001", ts=T0, me_seat=1, opp_seat=2):
    return (
        '[UnityCrossThreadLogger]9/5/2026 20:00:00 ==> '
        '{"transactionId":"tx-' + match_id + '","timestamp":"' + ts + '",'
        '"matchGameRoomStateChangedEvent":{"gameRoomInfo":{'
        '"state":"MatchGameRoomStateType_Playing",'
        '"gameRoomConfig":{'
        '"matchId":"' + match_id + '","eventId":"Play_Brawl_Historic",'
        '"reservedPlayers":[' + _players(me_seat, opp_seat) + ']}}}}}\n'
    )


def turn_info(turn=1, active=1, ts=T1, commanders=False):
    zone = ""
    if commanders:
        zone = (',{"zoneId":3,"type":"ZoneType_Command","ownerSeatId":2,'
                '"objectInstanceIds":[101,102]}')
    return (
        '[UnityCrossThreadLogger]{"timestamp":"' + ts + '","greToClientEvent":{'
        '"greToClientMessages":[{"type":"GREMessageType_GameStateMessage",'
        '"gameStateMessage":{"turnInfo":{"turnNumber":' + str(turn) +
        ',"activePlayer":' + str(active) + '},'
        '"zones":[{"zoneId":1,"type":"ZoneType_Hand","ownerSeatId":1}' + zone + '],'
        '"gameObjects":[{"instanceId":101,"grpId":"96352"},'
        '{"instanceId":102,"grpId":"96353"}]}}]}}\n'
    )


def final_result(ts=T3, winner_match=1, games=((1, "ResultReason_Concede"),),
                 match_id=None):
    """真实日志的 finalMatchResult 带 matchId；match_id=None 时模拟旧格式。"""
    entries = [
        '{"scope":"MatchScope_Match","winningTeamId":' + str(winner_match) +
        ',"reason":"ResultReason_Concede"}'
    ]
    for gwin, greason in games:
        entries.append(
            '{"scope":"MatchScope_Game","winningTeamId":' + str(gwin) +
            ',"reason":"' + greason + '"}'
        )
    mid = f'"matchId":"{match_id}",' if match_id else ""
    return (
        '[UnityCrossThreadLogger]{"timestamp":"' + ts + '",'
        '"finalMatchResult":{' + mid + '"resultList":[' + ",".join(entries) + ']}}\n'
    )


def game_result(winner=1, match_id=None, ts=T3,
                reason="ResultReason_Concede"):
    """BO3 中途：仅 MatchScope_Game（无 MatchScope_Match）。"""
    mid = f'"matchId":"{match_id}",' if match_id else ""
    return (
        '[UnityCrossThreadLogger]{"timestamp":"' + ts + '",'
        '"finalMatchResult":{' + mid +
        '"resultList":[{"scope":"MatchScope_Game","result":"ResultType_WinLoss",'
        '"winningTeamId":' + str(winner) + ',"reason":"' + reason + '"}]}}\n'
    )


def match_completed(ts=T4):
    return (
        '[UnityCrossThreadLogger]{"timestamp":"' + ts + '",'
        '"matchGameRoomStateChangedEvent":{"gameRoomInfo":{'
        '"state":"MatchGameRoomStateType_MatchCompleted"}}}}\n'
    )


def mulligan(kept_on=1, ts=T1):
    """真实格式：每次决策一条。

    kept_on=0 直接保留（Keep），>0 表示先调度 kept_on 次再保留。
    合成日志用 Mulligan*kept_on + Keep 序列还原该结果。
    """
    out = []
    for i in range(kept_on):
        out.append(
            '[UnityCrossThreadLogger]{"timestamp":"' + ts + '",'
            '"mulliganResp":{"decision":"MulliganOption_Mulligan"}}\n'
        )
    out.append(
        '[UnityCrossThreadLogger]{"timestamp":"' + ts + '",'
        '"mulliganResp":{"decision":"MulliganOption_Keep"}}\n'
    )
    return "".join(out)


def rank_info(ts=T0, cls="Gold", level=4):
    return (
        '[UnityCrossThreadLogger]{"timestamp":"' + ts + '",'
        '"RankGetCombinedRankInfo":{"constructedClass":"' + cls +
        '","constructedLevel":' + str(level) +
        ',"limitedClass":"Bronze","limitedLevel":4}}\n'
    )


def corrupted_line(ts=T1):
    return '[UnityCrossThreadLogger]{"timestamp":"' + ts + '","broken": [{"unclosed": 1\n'


def bo1_match_lines(match_id="m-001", my_active=1):
    """完整 BO1：开局 → turn1(定先后手) → turn2 → 结果(我胜) → 完结"""
    return [
        match_start(match_id),
        turn_info(1, my_active, commanders=True),
        turn_info(2, 3 - my_active),
        final_result(winner_match=1, games=((1, "ResultReason_Concede"),)),
        match_completed(),
    ]


def bo3_match_lines(match_id="m-bo3"):
    """BO3：第1局我后手负，第2局换边我先手胜（match 层冗余取第 1 局）。

    中途局结果用仅 MatchScope_Game 的块（与真实日志一致）；
    MatchScope_Match 只在整场结束时出现。
    """
    return [
        match_start(match_id),
        turn_info(1, 2, commanders=True),      # 第1局：activePlayer=2，我在 seat1 → 后手
        turn_info(2, 1),
        game_result(winner=2, match_id=match_id),  # 第1局对手胜
        turn_info(1, 1),                        # 第2局换边：我先手
        turn_info(2, 2),
        game_result(winner=1, match_id=match_id),  # 第2局我胜
        final_result(winner_match=1, games=(), match_id=match_id),  # 整场我胜
        match_completed(),
    ]
