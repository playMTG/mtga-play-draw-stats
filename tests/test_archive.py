# -*- coding: utf-8 -*-
"""日志归档测试（app.archive）。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import fixtures as fx
import pytest
from app.archive import archive_session_logs, archived_files
from app.config import Config


@pytest.fixture(autouse=True)
def _isolate_install_detection(tmp_path, monkeypatch):
    """屏蔽真实安装路径探测（本机可能有 Steam 库/官方客户端），
    保证归档测试只作用于 tmp 目录。"""
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "no_pf"))
    monkeypatch.setenv("ProgramFiles(x86)", str(tmp_path / "no_pf86"))


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


def test_archive_multiple_source_dirs(tmp_path, monkeypatch):
    """官方客户端 + Steam 多目录来源全部归档（session_log_dirs 候选机制）。"""
    steam = tmp_path / "steam_logs"
    official = tmp_path / "official_logs"
    steam.mkdir()
    official.mkdir()
    (steam / "UTC_Log-A.log").write_text("a" * 10, encoding="utf-8")
    (official / "UTC_Log-B.log").write_text("b" * 20, encoding="utf-8")

    # 通过 session_logs_extra 注入两个目录（自动探测的环境变量路径在测试机不存在）
    cfg = Config(
        {"log_paths": {
            "player_log": str(tmp_path / "no_player.log"),
            "prev_log": str(tmp_path / "no_prev.log"),
            "steam_session_logs": str(steam),
            "session_logs_extra": [str(official)],
         }, "db_path": str(tmp_path / "db.sqlite")},
        root=tmp_path,
    )
    got = archive_session_logs(cfg)
    assert sorted(got) == ["UTC_Log-A.log", "UTC_Log-B.log"]

    # backfill 收集来源时同样覆盖两个目录且不与归档重复
    from app.backfill import collect_sources
    names = sorted(f.name for f in collect_sources(cfg))
    assert names == ["UTC_Log-A.log", "UTC_Log-B.log"]
