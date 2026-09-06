# -*- coding: utf-8 -*-
"""日志防丢归档（DESIGN P0）：启动时把 Steam 会话日志复制到 data/archive/。

背景：MTGA 客户端会自动清理旧日志（UTC_Log-*.log 每会话一份，含完整
对局事件），这些历史数据不可再生。归档是唯一防丢手段。

幂等策略：目标文件已存在且大小一致 → 跳过；大小不一致（客户端追加）
→ 重新覆盖复制。Player.log/Player-prev.log 是持续增长的滚动文件，
体积大且内容会被 tail 实时入库，不归档。
"""
from __future__ import annotations

import shutil
from pathlib import Path

from .config import Config


def archive_session_logs(cfg: Config) -> list[str]:
    """把 steam_logs_dir 下的 UTC_Log*.log 归档到 data/archive/。

    返回本次实际（重新）复制的文件名列表；无来源目录返回空表。
    """
    src_dir = cfg.steam_logs_dir
    if not src_dir.is_dir():
        return []
    dst_dir = cfg.root / "data" / "archive"
    dst_dir.mkdir(parents=True, exist_ok=True)

    archived: list[str] = []
    for f in sorted(src_dir.glob("UTC_Log*.log")):
        try:
            src_size = f.stat().st_size
        except OSError:
            continue
        dst = dst_dir / f.name
        if dst.exists() and dst.stat().st_size == src_size:
            continue  # 已归档且大小一致
        try:
            shutil.copy2(f, dst)
        except OSError:
            continue  # 单文件失败不阻塞启动（可能正被客户端写入）
        archived.append(f.name)
    return archived


def archived_files(cfg: Config) -> list[Path]:
    """列出归档目录中的日志文件（按文件名排序）。"""
    d = cfg.root / "data" / "archive"
    if not d.is_dir():
        return []
    return sorted(d.glob("UTC_Log*.log"))
