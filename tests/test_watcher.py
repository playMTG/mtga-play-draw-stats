# -*- coding: utf-8 -*-
"""watcher 增量读取与滚动切换单测。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.events import SessionBuilder
from app.watcher import LogWatcher

import fixtures as fx


def _drain(w: LogWatcher) -> list[str]:
    return [r.text for r in w.poll()]


def test_poll_reads_new_lines_only(tmp_path):
    p = tmp_path / "Player.log"
    p.write_text("line1\nline2\n", encoding="utf-8")
    w = LogWatcher(p, poll_sec=0)
    assert len(_drain(w)) == 2
    assert _drain(w) == []          # 无新内容
    with open(p, "a", encoding="utf-8") as f:
        f.write("line3\n")
    got = _drain(w)
    assert len(got) == 1 and "line3" in got[0]


def test_rotation_truncated_file_restarts_from_head(tmp_path):
    """模拟滚动：文件被重建变小 → 从头重读（入库层幂等去重）。"""
    p = tmp_path / "Player.log"
    p.write_text("old-a\nold-b\nold-c\n", encoding="utf-8")
    w = LogWatcher(p, poll_sec=0)
    assert len(_drain(w)) == 3
    # MTGA 重启：文件被替换为新的小文件
    p.write_text(fx.match_start(), encoding="utf-8")
    got = _drain(w)
    assert len(got) == 1
    assert "MatchGameRoomStateType_Playing" in got[0] or "matchGameRoomStateChangedEvent" in got[0]


def test_multiline_json_block_assembled(tmp_path):
    """回归：跨行 pretty-printed JSON 必须合并为一条逻辑记录。

    逐物理行喂入会让括号不平衡的块被解析器丢弃——这正是监听重放
    冲坏 mulligans 数据的根因（与 backfill 的 iter_records 语义一致）。
    """
    p = tmp_path / "Player.log"
    block = (
        '[UnityCrossThreadLogger]Client ==> {"mulliganResp":{\n'
        '  "decision":"MulliganOption_AcceptHand"\n'
        "}}\n"
    )
    p.write_text("plain line\n" + block, encoding="utf-8")
    w = LogWatcher(p, poll_sec=0)
    got = _drain(w)
    # 普通行 1 条 + 合并后的完整 JSON 块 1 条（若按行拆会得到 3 条残块）
    assert len(got) == 2
    assert got[0] == "plain line" or got[0].startswith("plain line")
    assert got[1].startswith("[UnityCrossThreadLogger]Client ==> {")
    assert '"decision"' in got[1] and got[1].rstrip().endswith("}}")


def test_multiline_block_spanning_polls(tmp_path):
    """跨 poll 轮次的块：首行到了、后续行下轮才到 → 块完整后一并产出。"""
    p = tmp_path / "Player.log"
    w = LogWatcher(p, poll_sec=0)
    p.write_text('{"a":{\n', encoding="utf-8")
    assert _drain(w) == []          # 块未闭合，先不出
    with open(p, "a", encoding="utf-8") as f:
        f.write('"k":1}}\n')
    got = _drain(w)
    assert len(got) == 1
    assert got[0].startswith('{"a":{')


def test_deleted_file_poll_is_safe(tmp_path):
    p = tmp_path / "Player.log"
    p.write_text("x\n", encoding="utf-8")
    w = LogWatcher(p, poll_sec=0)
    _drain(w)
    p.unlink()
    assert _drain(w) == []  # 文件消失不抛异常


# ---------- SessionBuilder.take：监听线程 flush 语义 ----------

def test_feed_sets_dirty_flag():
    sb = SessionBuilder(my_player_id=fx.ME)
    assert sb.dirty is False
    sb.feed("not an event line\n")
    assert sb.dirty is True


def test_take_returns_completed_and_clears_buffer():
    """take = 取走已完成对局并清空；再 take 为空（幂等 flush 前提）。"""
    sb = SessionBuilder(my_player_id=fx.ME)
    for text in fx.bo1_match_lines():
        sb.feed(text)
    r1 = sb.take()
    assert len(r1.matches) == 1
    assert r1.matches[0].match_id == "m-001"
    assert sb.take().matches == []      # 缓冲已清空，不重复返回
    assert sb.take().ranks == []


def test_take_keeps_in_progress_match_alive():
    """关键：take 不得闭合进行中的对局——否则后续事件因 _cur 为 None 全丢。

    模拟监听节奏：开局 → flush(拿到 0 场) → 后续 GRE/结果 → MatchCompleted
    → flush(拿到完整 1 场)。
    """
    sb = SessionBuilder(my_player_id=fx.ME)
    sb.feed(fx.match_start())
    # 中途 flush（如 2 秒轮询窗口到了）
    assert sb.take().matches == []  # 进行中对局不被提前落库
    # 对局继续进行，事件不丢
    sb.feed(fx.turn_info(turn=1, active=1))
    sb.feed(fx.final_result(winner_match=1))
    sb.feed(fx.match_completed())
    r = sb.take()
    assert len(r.matches) == 1
    m = r.matches[0]
    assert m.my_result == "win"
    assert m.play_draw == "play"
    assert m.end_ms is not None
