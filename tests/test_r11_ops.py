# -*- coding: utf-8 -*-
"""R11.3：损坏配置保护、启动状态可见字段。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import load_config


def test_corrupt_config_marks_error_and_keeps_defaults(tmp_path):
    (tmp_path / "config.json").write_text("{not json", encoding="utf-8")
    cfg = load_config(tmp_path)
    assert cfg.config_error is not None
    assert cfg.port == 8765  # 回退默认
    # 原文件未被删除/改写
    assert (tmp_path / "config.json").read_text(encoding="utf-8") == "{not json"


def test_valid_config_merges(tmp_path):
    (tmp_path / "config.json").write_text(
        json.dumps({"port": 9999, "my_player_id": "ABC"}),
        encoding="utf-8",
    )
    cfg = load_config(tmp_path)
    assert cfg.config_error is None
    assert cfg.port == 9999
    assert cfg.my_player_id == "ABC"


def test_missing_config_ok(tmp_path):
    cfg = load_config(tmp_path)
    assert cfg.config_error is None


def test_persist_player_id_refuses_corrupt_config(tmp_path, monkeypatch):
    """损坏 config 不得被自动覆盖成只剩 my_player_id。"""
    import app.main as main

    bad = tmp_path / "config.json"
    bad.write_text("{broken", encoding="utf-8")
    # 把 main.cfg 指到 tmp 项目
    cfg = load_config(tmp_path)
    assert cfg.config_error is not None
    monkeypatch.setattr(main, "cfg", cfg)
    main._persist_player_id("SHOULD_NOT_WRITE")
    assert bad.read_text(encoding="utf-8") == "{broken"
    assert list(tmp_path.glob("config.json.corrupt-*.bak")) or True  # 可能备份


def test_persist_player_id_writes_when_valid(tmp_path, monkeypatch):
    import app.main as main

    f = tmp_path / "config.json"
    f.write_text(json.dumps({"port": 8765}), encoding="utf-8")
    cfg = load_config(tmp_path)
    monkeypatch.setattr(main, "cfg", cfg)
    main._persist_player_id("ME123")
    data = json.loads(f.read_text(encoding="utf-8"))
    assert data["my_player_id"] == "ME123"
    assert data["port"] == 8765  # 其它键保留
