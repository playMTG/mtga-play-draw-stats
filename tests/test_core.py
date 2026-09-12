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


# ---------- events：主将区的类型过滤（R13.1） ----------

def _command_zone_line(objs: list[tuple[int, str, str | None]]) -> str:
    """构造一条带 ZoneType_Command 的状态行。

    objs: [(instanceId, grpId, type)]，type=None 表示该 gameObject 不带 type 字段
    （合成日志与旧格式的真实形态）。
    """
    game_objects = ",".join(
        '{"instanceId":%d,"grpId":"%s"%s,"ownerSeatId":2}'
        % (iid, grp, (',"type":"%s"' % t) if t else "")
        for iid, grp, t in objs
    )
    zone_ids = ",".join(str(iid) for iid, _, _ in objs)
    return (
        '[UnityCrossThreadLogger]{"timestamp":"' + fx.T1 + '","greToClientEvent":{'
        '"greToClientMessages":[{"type":"GREMessageType_GameStateMessage",'
        '"gameStateMessage":{"turnInfo":{"turnNumber":1,"activePlayer":1},'
        '"zones":[{"zoneId":1,"type":"ZoneType_Hand","ownerSeatId":1},'
        '{"zoneId":3,"type":"ZoneType_Command","objectInstanceIds":[' + zone_ids + ']}],'
        '"gameObjects":[' + game_objects + ']}}]}}\n'
    )


def _brawl_lines(objs: list[tuple[int, str, str | None]]) -> list[str]:
    return [
        fx.match_start("m-zone"),
        _command_zone_line(objs),
        fx.final_result(winner_match=1, games=((1, "ResultReason_Concede"),)),
        fx.match_completed(),
    ]


def test_emblem_in_command_zone_is_not_a_commander():
    """客户端会把徽记（Emblem）误写进主将区，不能被当成主将。

    全量实测 33 份归档：Command 区只有 Card(317) 与 Emblem(16)，
    后者恒为 grpId=2 / objectSourceGrpId=87496。
    """
    r = feed_lines(_brawl_lines([
        (101, "96352", "GameObjectType_Card"),
        (102, "2", "GameObjectType_Emblem"),
    ]))
    opp = [c for c in r.matches[0].commanders if c["seat"] == 2]
    assert {c["grp_id"] for c in opp} == {"96352"}, "徽记不该被当成主将"


def test_emblem_only_command_zone_yields_no_commander():
    """主将区只有徽记时，应解析出 0 个主将，而不是 1 个伪主将。"""
    r = feed_lines(_brawl_lines([(102, "2", "GameObjectType_Emblem")]))
    opp = [c for c in r.matches[0].commanders if c["seat"] == 2]
    assert opp == []


def test_two_card_commanders_survive_filter():
    """伙伴双主将（都是 Card）不受类型过滤影响。"""
    r = feed_lines(_brawl_lines([
        (101, "96352", "GameObjectType_Card"),
        (102, "96353", "GameObjectType_Card"),
    ]))
    opp = [c for c in r.matches[0].commanders if c["seat"] == 2]
    assert {c["grp_id"] for c in opp} == {"96352", "96353"}


def test_missing_gameobject_type_is_tolerated():
    """无 type 字段时必须照常解析——兼容合成日志与旧格式。"""
    r = feed_lines(_brawl_lines([(101, "96352", None), (102, "96353", None)]))
    opp = [c for c in r.matches[0].commanders if c["seat"] == 2]
    assert {c["grp_id"] for c in opp} == {"96352", "96353"}


def test_emblem_grpid_purged_on_connect(tmp_path):
    """历史脏数据：徽记 grpId=2 曾被写成主将，重连时应被迁移清掉。

    解析侧已按 GameObjectType 过滤（上面几条），但库里可能残留旧解析产物——
    对手主将档案里那个永远查不到卡名的条目。迁移负责清历史数据。
    """
    db = tmp_path / "s.db"
    conn = connect(db)
    conn.execute("INSERT INTO matches(match_id) VALUES('m1')")
    conn.execute("INSERT INTO commanders(match_id, seat, grp_id) VALUES('m1', 2, '2')")
    conn.execute("INSERT INTO commanders(match_id, seat, grp_id) VALUES('m1', 2, '96352')")
    conn.commit()
    conn.close()

    conn2 = connect(db)  # 重连触发 _migrate
    got = {r[0] for r in conn2.execute("SELECT grp_id FROM commanders")}
    conn2.close()
    assert got == {"96352"}, f"徽记 grpId=2 应被清理，实得 {got}"


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


def test_zero_turn_match_counts_normally(tmp_path):
    """2026-09-07 口径：秒退/投降是正常结果 → 0 回合局也照常计分，不标异常。"""
    cfg = _cfg(tmp_path)
    conn = connect(cfg.db_path)

    # 0 回合：开局后对手直接离开，GRE 从未到来 → 正常计分
    sb = SessionBuilder(source="log", my_player_id=fx.ME)
    for t in (fx.match_start("m-zero"), fx.final_result(winner_match=1),
              fx.match_completed()):
        sb.feed(t)
    (m,) = sb.close().matches
    upsert_match(conn, m, cfg)
    r = conn.execute(
        "SELECT is_abnormal, abnormal_reason FROM matches WHERE match_id='m-zero'"
    ).fetchone()
    assert r["is_abnormal"] == 0 and r["abnormal_reason"] is None

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

    # 历史库迁移：旧 no_game 标记在 connect() 时被清除
    conn.execute(
        "UPDATE matches SET is_abnormal=1, abnormal_reason='no_game' "
        "WHERE match_id='m-short'"
    )
    conn.commit()
    conn2 = connect(cfg.db_path)
    r = conn2.execute(
        "SELECT is_abnormal, abnormal_reason FROM matches WHERE match_id='m-short'"
    ).fetchone()
    assert r["is_abnormal"] == 0 and r["abnormal_reason"] is None
    conn.close()
    conn2.close()


def test_set_player_id_backfills_open_and_last_match():
    """身份晚到：启动时没有 userId，对局已解析但无座位/胜负；补挂后必须能确认。"""
    # 无身份：能收到结束原因，但分不清我方 → seat/pd/result 全空
    sb = SessionBuilder(source="log", my_player_id=None)
    for t in (fx.match_start("m-late"), fx.turn_info(turn=1, active=1),
              fx.final_result(winner_match=1), fx.match_completed()):
        sb.feed(t)
    closed = sb.take().matches
    assert len(closed) == 1
    assert closed[0].my_seat is None
    assert closed[0].my_result is None
    assert closed[0].end_reason == "Concede"

    # 进行中的对局（尚无 MatchCompleted）
    sb.feed(fx.match_start("m-open"))
    sb.feed(fx.turn_info(turn=1, active=2, ts=fx.T2))
    assert sb._cur is not None and sb._cur.my_seat is None

    sb.set_player_id(fx.ME)
    assert sb.my_player_id == fx.ME
    assert sb._cur.my_seat == 1 and sb._cur.opponent_name == "Opponent"
    assert sb._last.my_seat == 1
    # 最近闭合场被标记重发，监听 flush 会带上已补全的座位
    assert sb._last_revised is True
    again = sb.take().matches
    assert any(m.match_id == "m-late" and m.my_seat == 1 for m in again)


def test_collect_sources_skips_inaccessible_player_log(tmp_path, monkeypatch):
    """Player.log 被独占时 Path.exists 可能抛 PermissionError，不得让回填整体失败。"""
    from app.backfill import collect_sources

    good = tmp_path / "Player-prev.log"
    good.write_text("x\n", encoding="utf-8")
    locked = tmp_path / "Player.log"
    locked.write_text("y\n", encoding="utf-8")

    class _Cfg:
        root = tmp_path
        player_log = locked
        prev_log = good

        def session_log_dirs(self):
            return []

    original_exists = type(locked).exists

    def boom(self):
        if self == locked:
            raise PermissionError(13, "拒绝访问")
        return original_exists(self)

    monkeypatch.setattr(type(locked), "exists", boom)
    files = collect_sources(_Cfg())
    assert good in files
    assert locked not in files
