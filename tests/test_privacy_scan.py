# -*- coding: utf-8 -*-
"""R12.4 隐私扫描工具的出口语义与覆盖范围。

两个曾经的问题：
1. `TEXT_EXT` 不含脚本类扩展名（.bat/.cmd/.cjs/.ps1/.vbs），仓库里这些文件
   夹带的用户名或路径扫不到；
2. 空暂存区和「扫描通过」共用 return 0——什么都没 staged 时也绿灯，
   看起来像扫过了。

这里断言：脚本类扩展名在扫描范围内、三种出口的返回码互不相同。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools import check_privacy


def test_script_extensions_are_scanned():
    """脚本类扩展名必须进 TEXT_EXT，否则内容不会被查。"""
    for ext in (".bat", ".cmd", ".cjs", ".ps1", ".vbs"):
        assert ext in check_privacy.TEXT_EXT, f"{ext} 未被隐私扫描覆盖"
    # 原有的文本类型不能因此丢失
    for ext in (".py", ".js", ".md", ".json", ".html"):
        assert ext in check_privacy.TEXT_EXT


def test_scan_flags_username_in_bat_file(tmp_path, monkeypatch):
    """.bat 里的用户名要被抓到（这正是补齐扩展名的目的）。"""
    monkeypatch.setattr(check_privacy, "REPO", tmp_path)
    bat = tmp_path / "start.bat"
    bat.write_text("@echo off\r\ncd C:\\Users\\someone\\MTGA\r\n", encoding="utf-8")

    problems = check_privacy.scan([bat])
    assert any("WINPATH" in p or "用户" in p or "someone" in p for p in problems), problems


def test_empty_staging_is_not_success(monkeypatch, capsys):
    """空暂存区必须返回非 0，且不打印「通过」。"""
    monkeypatch.setattr(check_privacy, "staged_files", lambda: [])
    rc = check_privacy.main([])
    out = capsys.readouterr().out
    assert rc == 2, "空暂存区不应与「通过」共用出口"
    assert "通过" not in out
    assert "暂存区为空" in out or "没有扫描任何文件" in out


def test_main_returns_zero_on_clean_files(tmp_path, monkeypatch, capsys):
    """干净的暂存区才会返回 0 并打印通过。"""
    clean = tmp_path / "ok.py"
    clean.write_text("print('hello')\n", encoding="utf-8")
    monkeypatch.setattr(check_privacy, "REPO", tmp_path)
    monkeypatch.setattr(check_privacy, "staged_files", lambda: [clean])
    rc = check_privacy.main([])
    out = capsys.readouterr().out
    assert rc == 0
    assert "通过" in out


def test_all_flag_scans_repo_but_skips_ignored():
    """--all 扫仓库内容，但不把 gitignored 的本机配置算进去。"""
    files = check_privacy.all_text_files()
    rels = {f.relative_to(check_privacy.REPO).as_posix() for f in files}
    assert rels, "仓库里应该扫到文件"
    # config.json / data/ 是本机私有的 gitignored 路径，不该出现在待发布清单里
    assert "config.json" not in rels
    assert not any(r.startswith("data/") for r in rels)
    # 仓库自身的源码必须在
    assert "app/main.py" in rels
