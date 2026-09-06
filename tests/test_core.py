# -*- coding: utf-8 -*-
"""解析核心单测：合成日志片段（纯虚构数据，不含任何真实玩家信息）。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Config
from app.events import SessionBuilder
from app.parser import extract_jsons, iter_lines, iter_records
from app.store import connect, stats, upsert_match

import fixtures as fx


def feed_lines(lines: list[str], my_id: str | None = fx.ME, source="log"):
    sb = SessionBuilder(source=source, my_player_id=my_id)
    for text in lines:
        sb.feed(text)
    return sb.close()


# ---------- parser ----------

def test_extract_jsons_nested_and_strings():
    text = 'a {"k":"}{","n":{"x":1}} b {"y":[{},2]} c {"unclosed": 1'
    got = extract_jsons(text)
    import json
    assert len(got) == 2
    assert json.loads(got[0]) == {"k": "}{", "n": {"x": 1}}
    assert json.loads(got[1]) == {"y": [{}, 2]}


def test_iter_lines_carries_timestamp(tmp_path):
    p = tmp_path / "log.txt"
    p.write_text(fx.rank_info() + "no timestamp here\n", encoding="utf-8")
    recs = list(iter_lines(p))
    assert recs[0].ts_ms == int(fx.T0)
    assert recs[1].ts_ms == int(fx.T0)  # 时间戳上下文延续


# ---------- events：BO1 生命周期 ----------

def test_bo1_full_lifecycle():
    r = feed_lines(fx.bo1_match_lines())
    assert len(r.matches) == 1
    m = r.matches[0]
    assert m.match_id == "m-001"
    assert m.my_team == 1 and m.my_seat == 1
    assert m.opponent_name == "Opponent"
    assert m.event_id == "Play_Brawl_Historic"
    assert m.my_result == "win"
    assert m.end_reason == "Concede"
    assert m.play_draw == "play"
    assert m.games[0].play_draw == "play"
    assert m.games[0].result == "win"
    assert m.total_turns == 2
    assert m.start_ms == int(fx.T0) and m.end_ms == int(fx.T4)
    assert m.duration_ms if hasattr(m, "duration_ms") else True


def test_partner_commander_identified():
    r = feed_lines(fx.bo1_match_lines())
    m = r.matches[0]
    cmd = [c for c in m.commanders if c["seat"] == 2]
    assert len(cmd) == 2  # 伙伴双主将：同区两实例
    assert {c["grp_id"] for c in cmd} == {"96352", "96353"}
    assert sorted(c["partner_idx"] for c in cmd) == [0, 1]


def test_play_draw_when_opponent_starts():
    # 我 seat1，第 1 局 activePlayer=2 → 我后手
    lines = fx.bo1_match_lines(my_active=2)
    r = feed_lines(lines)
    m = r.matches[0]
    assert m.play_draw == "draw"


# ---------- events：BO3 换边 ----------

def test_bo3_per_game_play_draw():
    r = feed_lines(fx.bo3_match_lines())
    m = r.matches[0]
    assert len(m.games) == 2
    g1, g2 = m.games
    assert g1.play_draw == "draw" and g1.result == "loss"
    assert g2.play_draw == "play" and g2.result == "win"
    # match 层冗余 = 第 1 局
    assert m.play_draw == "draw"


# ---------- 容错 ----------

def test_corrupted_json_skipped_not_crash():
    lines = [fx.match_start(), fx.corrupted_line(), *fx.bo1_match_lines()[1:]]
    r = feed_lines(lines)
    assert len(r.matches) == 1
    assert r.unparsed_lines >= 1


def test_missing_match_completed_still_closes():
    lines = fx.bo1_match_lines()[:-1]  # 没有 MatchCompleted
    r = feed_lines(lines)
    assert len(r.matches) == 1  # 下一场开始/收尾时兜底闭合


def test_rank_snapshot_parsed():
    r = feed_lines([fx.rank_info()])
    assert len(r.ranks) == 1
    assert r.ranks[0].constructed_class == "Gold"
    assert r.ranks[0].constructed_level == 4


def test_mulligan_recorded():
    lines = [fx.match_start(), fx.mulligan(kept_on=1), *fx.bo1_match_lines()[1:]]
    r = feed_lines(lines)
    assert len(r.matches[0].mulligans) == 1
    assert r.matches[0].mulligans[0]["kept_on"] == 1


# ---------- 多行 JSON 块组装 ----------

def test_record_assembler_merges_pretty_printed_block():
    from app.parser import RecordAssembler
    asm = RecordAssembler()
    block = '{\n  "a": {\n    "b": "x"\n  },\n  "type": "ClientMessageType_MulliganResp"\n}\n'
    out = []
    for ln in block.splitlines(True):
        out.extend(asm.feed(ln))
    assert len(out) == 1
    import json
    assert json.loads(out[0])["a"]["b"] == "x"


def test_iter_records_handles_mixed_content(tmp_path):
    p = tmp_path / "log.txt"
    multi = '{\n "timestamp": "1788599000000",\n "mulliganResp": {"playerSeatId": 1}\n}\n'
    p.write_text(
        fx.match_start() + multi + fx.final_result() + fx.match_completed(),
        encoding="utf-8",
    )
    recs = list(iter_records(p))
    assert len(recs) == 4  # 开局行 + 多行块 + 结果行 + 完结行
    import json
    mull = json.loads(recs[1][0])
    assert mull["mulliganResp"]["playerSeatId"] == 1
    assert recs[1][1] == 1788599000000  # 时间戳上下文从块内提取


# ---------- store：幂等 ----------

def _cfg(tmp_path):
    data = {
        "db_path": str(tmp_path / "t.db"),
        "abnormal_match": {"max_duration_sec": 150, "max_turns": 2},
    }
    return Config(data, tmp_path)


def test_upsert_idempotent(tmp_path):
    cfg = _cfg(tmp_path)
    conn = connect(cfg.db_path)
    lines = fx.bo1_match_lines()
    sb = SessionBuilder(my_player_id=fx.ME)
    for t in lines:
        sb.feed(t)
    r = sb.close()
    m = r.matches[0]
    assert upsert_match(conn, m, cfg) is True
    assert upsert_match(conn, m, cfg) is False  # 二次写入 = 更新
    st = stats(conn)
    assert st["matches"] == 1
    assert st["games"] == 1
    assert st["with_commanders"] == 1
    # 新口径：2 回合但真实发生 → 正常局（旧阈值规则已废弃，速胜不再被隐藏）
    assert st["abnormal"] == 0
    conn.close()


def test_zero_turn_match_is_abnormal(tmp_path):
    """对手秒退（没有任何 GRE 回合）→ 异常局；有回合的速胜 → 正常。"""
    cfg = _cfg(tmp_path)
    conn = connect(cfg.db_path)

    # 0 回合：开局后对手直接离开，GRE 从未到来
    sb = SessionBuilder(source="log", my_player_id=fx.ME)
    for t in (fx.match_start("m-zero"), fx.final_result(winner_match=1),
              fx.match_completed()):
        sb.feed(t)
    (m,) = sb.close().matches
    upsert_match(conn, m, cfg)
    r = conn.execute(
        "SELECT is_abnormal, abnormal_reason FROM matches WHERE match_id='m-zero'"
    ).fetchone()
    assert r["is_abnormal"] == 1 and r["abnormal_reason"] == "no_game"

    # 有回合的短局（对手 2 回合投降）→ 正常局，胜负计入
    sb = SessionBuilder(source="log", my_player_id=fx.ME)
    for t in fx.bo1_match_lines("m-short"):
        sb.feed(t)
    (m,) = sb.close().matches
    upsert_match(conn, m, cfg)
    r = conn.execute(
        "SELECT is_abnormal FROM matches WHERE match_id='m-short'"
    ).fetchone()
    assert r["is_abnormal"] == 0
    conn.close()
