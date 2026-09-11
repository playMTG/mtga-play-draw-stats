# -*- coding: utf-8 -*-
"""grpId → 卡名映射 CLI（薄封装，核心逻辑在 app/cards_sync.py 与 app/client_cards.py）。

用法：
    python -m tools.update_cards              # 离线：读本机 MTGA 客户端的卡牌库补英文卡名
    python -m tools.update_cards --online     # 联网：Scryfall 补英文 + 中文
    python -m tools.update_cards --zh         # 只补中文译名（联网）
    python -m tools.update_cards --no-zh      # 联网补英文但跳过中文
    python -m tools.update_cards --retry-zh   # 重置「已查过中文」标记，配合 --zh/--online 重试
    python -m tools.update_cards --client-db D:\\MTGA\\MTGA_Data\\Downloads\\Raw

默认是离线的：MTGA 客户端的 Raw_CardDatabase 含全部英文卡名，直接只读读取即可，
不联网、不改客户端文件。中文译名不在客户端库里，需要联网或本地快照导入。

面板运行时也会自动做同样的离线补齐（app/main.py 的 _cards_loop），
本脚本用于手动核对与一次性补全。
"""
from __future__ import annotations

import argparse
import sqlite3
import sys

from app.cards_sync import backfill_zh, cards_db_connect, sync_pending_cards
from app.client_cards import seed_cards_db
from app.config import load_config


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--online", action="store_true",
                    help="联网走 Scryfall 补英文与中文（默认只离线读本机客户端库）")
    ap.add_argument("--zh", action="store_true", help="只补中文译名（联网）")
    ap.add_argument("--no-zh", action="store_true", help="联网补英文，但不补中文")
    ap.add_argument("--retry-zh", action="store_true",
                    help="先清空「已查过中文」标记，让 --zh/--online 重试全部卡")
    ap.add_argument("--client-db", default=None,
                    help="客户端 Raw 目录；默认自动探测（含 Steam 多库）")
    args = ap.parse_args()

    cfg = load_config()
    stats_conn = sqlite3.connect(cfg.db_path)
    stats_conn.row_factory = sqlite3.Row
    cards_conn = cards_db_connect(cfg.root / "data" / "mtga_cards.db")

    if args.retry_zh:
        n = cards_conn.execute(
            "UPDATE cards SET zh_tried=0 WHERE name_zh IS NULL OR name_zh=''"
        ).rowcount
        cards_conn.commit()
        print(f"已重置 {n} 张卡的中文查询标记")

    if args.zh:
        n = backfill_zh(cards_conn)
        print(f"中文卡名完成：{n}")
        return 0

    # 离线补齐：客户端库只有英文名，先把能离线拿到的拿全
    raw_dirs = [cfg.expand(args.client_db)] if args.client_db else cfg.client_raw_dirs()
    r = seed_cards_db(cards_conn, stats_conn, raw_dirs)
    if r["client_db"]:
        print(f"本机客户端卡名库：{r['client_db']}")
    else:
        print("未找到本机 MTGA 客户端卡名库（Raw_CardDatabase_*.mtga）")
    print(f"离线补齐：新增 {r['seeded']} 张，仍缺 {r['unresolved']} 张"
          f"（待补总数 {r['pending']}）")
    if r["error"]:
        print(f"  !! 错误：{r['error']}", file=sys.stderr)

    if args.online or args.no_zh:
        ok, total = sync_pending_cards(stats_conn, cards_conn,
                                       with_zh=not args.no_zh)
        print(f"联网补全：{ok}/{total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
