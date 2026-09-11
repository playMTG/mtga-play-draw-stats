# -*- coding: utf-8 -*-
"""R12.2 回填/监听水位线：不再变化的日志整份跳过，且只在安全边界落盘。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import fixtures
from app import store
from app.backfill import backfill
from app.config import Config
from app.events import SessionBuilder
from app.ingest_marks import IngestMarks
from app.watcher import LogWatcher


def _cfg(tmp_path: Path, player_log: Path | None = None) -> Config:
    return Config(
        {
            "log_paths": {
                "player_log": str(player_log or tmp_path / "Player.log"),
                "prev_log": str(tmp_path / "Player-prev.log"),
                "steam_session_logs": str(tmp_path / "no_steam"),
                "session_logs_extra": [],
            },
            "db_path": str(tmp_path / "db.sqlite"),
            "my_player_id": fixtures.ME,
        },
        root=tmp_path,
    )


def _write_log(path: Path, *match_ids: str) -> None:
    text = "".join(
        line for mid in match_ids for line in fixtures.bo1_match_lines(mid))
    path.write_text(text, encoding="utf-8")


def test_second_backfill_skips_unchanged_file(tmp_path):
    log = tmp_path / "UTC_Log-2026-09-01.log"
    _write_log(log, "m-001")
    cfg = _cfg(tmp_path)

    first = backfill(cfg, [log])
    assert first["new"] == 1 and first["skipped"] == 0
    assert [name for name, _, _ in first["per_file"]] == [log.name]

    second = backfill(cfg, [log])
    assert second["skipped"] == 1
    assert second["new"] == 0 and second["updated"] == 0
    assert second["per_file"] == []          # 整份没有解析
    assert second["stats"]["matches"] == 1   # 数据仍在


def test_grown_file_is_parsed_again(tmp_path):
    log = tmp_path / "UTC_Log-2026-09-01.log"
    _write_log(log, "m-001")
    cfg = _cfg(tmp_path)
    backfill(cfg, [log])

    _write_log(log, "m-001", "m-002")
    again = backfill(cfg, [log])
    assert again["skipped"] == 0 and again["new"] == 1
    assert again["stats"]["matches"] == 2


def test_rewritten_file_with_same_size_is_detected(tmp_path):
    """大小没变但被原地改写（mtime 变化）时不能误判为「没变化」。"""
    log = tmp_path / "UTC_Log-2026-09-01.log"
    _write_log(log, "m-001")
    cfg = _cfg(tmp_path)
    backfill(cfg, [log])

    _write_log(log, "m-002")
    os.utime(log, (1_700_000_000, 1_700_000_000))   # 明确改写时间
    again = backfill(cfg, [log])
    assert again["skipped"] == 0 and again["new"] == 1
    assert again["stats"]["matches"] == 2


def test_replaced_file_is_parsed_from_start(tmp_path):
    """轮换：路径被换成另一个文件（inode 变了）→ 从头解析。"""
    log = tmp_path / "Player.log"
    _write_log(log, "m-001")
    cfg = _cfg(tmp_path)
    backfill(cfg, [log])

    log.unlink()
    _write_log(log, "m-009")
    assert backfill(cfg, [log])["skipped"] == 0


def test_marks_roundtrip(tmp_path):
    log = tmp_path / "x.log"
    log.write_text("hello\n", encoding="utf-8")
    conn = store.connect(tmp_path / "m.db")
    marks = IngestMarks(conn)
    assert marks.resume_offset(log) == 0          # 没有记录 → 从头

    size = log.stat().st_size
    marks.put(log, size, last_ts=123)
    conn.commit()
    assert marks.resume_offset(log) == size
    assert marks.is_unchanged(log) is True

    log.write_text("hello\nworld\n", encoding="utf-8")
    assert marks.resume_offset(log) == 0          # 变大了 → 从头
    assert marks.is_unchanged(log) is False

    marks.forget(log)
    assert marks.resume_offset(log) == 0
    conn.close()


def test_watcher_resumes_from_offset(tmp_path):
    log = tmp_path / "Player.log"
    first = "".join(fixtures.bo1_match_lines("m-001"))
    log.write_text(first, encoding="utf-8")
    # 必须用真实文件字节数：文本模式写入会把 \n 翻成 \r\n，
    # 水位线记录的是 iter_lines 给出的真实字节偏移
    offset = log.stat().st_size

    watcher = LogWatcher(log, start_offset=offset)
    assert list(watcher.poll()) == []             # 已消费完，没有新内容

    log.write_text(first + "".join(fixtures.bo1_match_lines("m-002")),
                   encoding="utf-8")
    texts = [rec.text for rec in watcher.poll()]
    assert len(texts) == len(fixtures.bo1_match_lines("m-002"))


def test_watcher_without_mark_reads_from_start(tmp_path):
    log = tmp_path / "Player.log"
    log.write_text("".join(fixtures.bo1_match_lines("m-001")), encoding="utf-8")
    assert len(list(LogWatcher(log).poll())) == len(fixtures.bo1_match_lines("m-001"))


def test_builder_reports_in_progress_for_safe_marks():
    """水位线只在没有未闭合对局时落盘，这个判断靠 in_progress。"""
    sb = SessionBuilder(source="log", my_player_id=fixtures.ME)
    assert sb.in_progress is False
    sb.feed(fixtures.match_start("m-001"))
    assert sb.in_progress is True                  # 开局后、闭合前不能落盘
    sb.feed(fixtures.match_completed())
    assert sb.in_progress is False
    assert sb.last_ts is not None
