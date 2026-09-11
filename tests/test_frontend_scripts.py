# -*- coding: utf-8 -*-
"""把 web/app.js 的前端测试（tests/*.cjs）纳入 pytest 收集。

这些脚本在 node 里用 `vm` 跑 `web/app.js` 的片段做断言，原本只能手动执行，
不在 `python -m pytest tests/` 的收集范围内（C3）——于是它们会在改 UI 时
静默失效：哨兵字符串一旦对不上，`slice(-1)` 会把整份源码喂进 vm 而崩在
`document is not defined`，看起来像脚本坏了而不是测试失败。

这里把它们逐个作为子进程跑一遍，退出码非 0 即失败，并把 node 的报错原样带出来。
没有 node 时用 skip 而不是 fail，保证纯后端环境仍能跑完测试。
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")

# 逐个列举而非 glob：新增脚本时显式登记，避免夹带无关文件
CJS_TESTS = [
    "test_daily_ui.cjs",
    "test_r9_ui.cjs",
    "test_deck_ui.cjs",
    "test_match_ui.cjs",
    "test_opponent_types_ui.cjs",
    "test_card_names_ui.cjs",
]


@pytest.mark.skipif(NODE is None, reason="未安装 node，跳过前端脚本测试")
@pytest.mark.parametrize("name", CJS_TESTS)
def test_frontend_script(name: str) -> None:
    script = ROOT / "tests" / name
    assert script.is_file(), f"缺少前端测试脚本：{name}"

    # cwd 必须是仓库根：脚本内部用 'web/app.js' 相对路径读取源码
    proc = subprocess.run(
        [NODE, str(script)],
        cwd=str(ROOT), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=120,
    )
    if proc.returncode != 0:
        pytest.fail(
            f"{name} 失败（exit={proc.returncode}）\n"
            f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
        )
