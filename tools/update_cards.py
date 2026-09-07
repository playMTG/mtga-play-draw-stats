# -*- coding: utf-8 -*-
"""grpId → 卡名映射 CLI（薄封装，核心逻辑在 app/cards_sync.py）。

用法：
    python -m tools.update_cards            # 补全 commanders/gameObjects 出现的 grpId
    python -m tools.update_cards --zh       # 仅补全中文卡名（走 Scryfall 本地化接口）
    python -m tools.update_cards --no-zh    # 拉 grpId 时跳过中文补全

面板运行时会自动周期同步（app/main.py 的 _cards_sync_loop），
本脚本用于离线手动补全。
"""
from __future__ import annotations

import sqlite3
import sys

from app.cards_sync import backfill_zh, cards_db_connect, sync_pending_cards
from app.config import load_config


def main() -> int:
    cfg = load_config()
    stats_conn = sqlite3.connect(cfg.db_path)
    stats_conn.row_factory = sqlite3.Row
    cards_conn = cards_db_connect(cfg.root / "data" / "mtga_cards.db")

    if "--zh" in sys.argv:
        n = backfill_zh(cards_conn)
        print(f"中文卡名完成：{n}")
        return 0

    ok, total = sync_pending_cards(stats_conn, cards_conn,
                                   with_zh="--no-zh" not in sys.argv)
    print(f"完成：{ok}/{total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
