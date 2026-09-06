# -*- coding: utf-8 -*-
"""日志归档测试（app.archive）。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import fixtures as fx
from app.archive import archive_session_logs, archived_files
from app.config import Config


def _cfg(tmp_path: Path, steam_dir: Path) -> Config:
    cfg = Config(
        {"log_paths": {"steam_session_logs": str(steam_dir)},
         "db_path": str(tmp_path / "db.sqlite")},
        root=tmp_path,
    )
    return cfg


def test_archive_copies_and_dedups(tmp_path):
    src = tmp_path / "steam"
    src.mkdir()
    (src / "UTC_Log-2026-09-01.log").write_text("a" * 100, encoding="utf-8")
    (src / "UTC_Log-2026-09-02.log").write_text("b" * 200, encoding="utf-8")
    (src / "other.txt").write_text("x", encoding="utf-8")  # 非目标文件

    cfg = _cfg(tmp_path, src)
    got = archive_session_logs(cfg)
    assert sorted(got) == ["UTC_Log-2026-09-01.log", "UTC_Log-2026-09-02.log"]
    arch = archived_files(cfg)
    assert [p.name for p in arch] == ["UTC_Log-2026-09-01.log", "UTC_Log-2026-09-02.log"]
    assert arch[0].read_text(encoding="utf-8") == "a" * 100

    # 幂等：无变化时二次归档为空
    assert archive_session_logs(cfg) == []

    # 客户端追加了内容（大小变化）→ 重新复制
    (src / "UTC_Log-2026-09-01.log").write_text("a" * 150, encoding="utf-8")
    assert archive_session_logs(cfg) == ["UTC_Log-2026-09-01.log"]
    assert (tmp_path / "data" / "archive" / "UTC_Log-2026-09-01.log"
            ).stat().st_size == 150


def test_archive_missing_source(tmp_path):
    cfg = _cfg(tmp_path, tmp_path / "nonexistent")
    assert archive_session_logs(cfg) == []
    assert archived_files(cfg) == []
