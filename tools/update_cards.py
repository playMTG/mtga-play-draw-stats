# -*- coding: utf-8 -*-
"""grpId → 卡名映射：按需从 Scryfall arena API 拉取并缓存到 data/mtga_cards.db。

设计原则：
- 只拉库里出现过的 grpId（主将优先，未来扩展到牌表），缓存永久有效（卡牌不变）；
- Scryfall 限速 10 req/s，逐个请求 + 100ms 间隔；
- 数据文件 gitignored，不属于开源仓库内容（开源用户运行本脚本自建）。

用法：
    python -m tools.update_cards            # 补全 commanders/gameObjects 出现的 grpId
    python -m tools.update_cards --all      # 同时补全 Untapped seed 数据里的 grpId
    python -m tools.update_cards --zh       # 补全中文卡名（走 Scryfall 本地化接口）
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

from app.config import load_config

SCRYFALL_API = "https://api.scryfall.com/cards/arena/{gid}"
SCRYFALL_ZH = "https://api.scryfall.com/cards/{set}/{cn}/zhs"  # zhs=简体中文


def cards_db_connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS cards (
          grp_id TEXT PRIMARY KEY,
          name TEXT,
          type_line TEXT,
          colors TEXT,
          fetched_at INTEGER
        );
        """
    )
    # 迁移（M4）：中文卡名 + 定位信息（set/collector_number，用于查本地化）
    cols = {r[1] for r in conn.execute("PRAGMA table_info(cards)")}
    for col in ("set_code", "collector_number", "name_zh"):
        if col not in cols:
            conn.execute(f"ALTER TABLE cards ADD COLUMN {col} TEXT")
    conn.commit()
    return conn


def pending_grpids(stats_conn: sqlite3.Connection,
                   cards_conn: sqlite3.Connection) -> list[str]:
    """stats 库里出现过、卡名库还没有的 grpId。"""
    known = {r["grp_id"] for r in cards_conn.execute("SELECT grp_id FROM cards")}
    gids = {r["grp_id"] for r in stats_conn.execute("SELECT DISTINCT grp_id FROM commanders")}
    gids |= {r["grp_id"] for r in stats_conn.execute(
        "SELECT DISTINCT grp_id FROM command_history")} if _has_table(
        stats_conn, "command_history") else set()
    return sorted(g for g in gids if g and g not in known and g.isdigit())


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def fetch_card(gid: str) -> dict | None:
    """用 curl 发请求（走系统代理，urllib 在本机环境被 Scryfall 拒绝）。"""
    try:
        proc = subprocess.run(
            ["curl", "-s", "--max-time", "15", SCRYFALL_API.format(gid=gid)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        data = json.loads(proc.stdout)
    except (OSError, json.JSONDecodeError) as e:
        print(f"  !! {gid}: {e}", file=sys.stderr)
        return None
    if data.get("object") == "error":
        print(f"  ?? {gid}: Scryfall 无此 arena_id", file=sys.stderr)
        return None
    return {
        "grp_id": gid,
        "name": data.get("name"),
        "type_line": data.get("type_line"),
        "colors": "".join(data.get("colors") or []),
        "set_code": data.get("set"),
        "collector_number": data.get("collector_number"),
        "fetched_at": int(time.time()),
    }


def fetch_zh_name(set_code: str, collector_number: str) -> str | None:
    """从 Scryfall 本地化接口取中文 printed_name（无中文的卡返回 None）。

    Arena 专属印刷编号带 A- 前缀（如 A-193），该编号在 Scryfall 语言
    路由下查不到本地化；剥掉前缀按同编号正印查询作为回退。
    """
    candidates = list(dict.fromkeys(
        [collector_number, collector_number.removeprefix("A-")]))
    for cn in candidates:
        try:
            proc = subprocess.run(
                ["curl", "-s", "--max-time", "15",
                 SCRYFALL_ZH.format(set=set_code, cn=cn)],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
            )
            data = json.loads(proc.stdout)
        except (OSError, json.JSONDecodeError) as e:
            print(f"  !! zh {set_code}#{cn}: {e}", file=sys.stderr)
            return None
        if data.get("object") == "error":
            continue  # 该编号无中文印刷，尝试下一个候选
        # 双面卡：printed_name 在 card_faces 里；单面卡在顶层
        name = data.get("printed_name")
        if not name and data.get("card_faces"):
            name = " // ".join(
                f.get("printed_name") or f.get("name") or ""
                for f in data["card_faces"]
            )
        if name:
            return name
    return None


def backfill_zh(cards_conn: sqlite3.Connection) -> int:
    """为缺中文名的卡补 name_zh；缺 set/collector_number 的先补 arena 元数据。"""
    rows = cards_conn.execute(
        "SELECT grp_id, name, set_code, collector_number, name_zh "
        "FROM cards WHERE grp_id LIKE '%'"
    ).fetchall()
    todo = [r for r in rows if not r["name_zh"]]
    print(f"待补中文卡名 {len(todo)} 张")
    ok = 0
    for r in todo:
        set_code, cn = r["set_code"], r["collector_number"]
        if not set_code or not cn:
            card = fetch_card(r["grp_id"])
            if not card or not card.get("set_code"):
                continue
            set_code, cn = card["set_code"], card["collector_number"]
            cards_conn.execute(
                "UPDATE cards SET set_code=?, collector_number=? WHERE grp_id=?",
                (set_code, cn, r["grp_id"]),
            )
            cards_conn.commit()
            time.sleep(0.12)
        zh = fetch_zh_name(set_code, cn)
        if zh:
            cards_conn.execute(
                "UPDATE cards SET name_zh=? WHERE grp_id=?", (zh, r["grp_id"]))
            cards_conn.commit()
            ok += 1
            print(f"  {r['name']} -> {zh}")
        else:
            print(f"  {r['name']}: 无中文印刷，保留英文")
        time.sleep(0.12)
    print(f"中文卡名完成：{ok}/{len(todo)}")
    return ok


def main() -> int:
    cfg = load_config()
    stats_conn = sqlite3.connect(cfg.db_path)
    stats_conn.row_factory = sqlite3.Row
    cards_conn = cards_db_connect(cfg.root / "data" / "mtga_cards.db")

    if "--zh" in sys.argv:
        backfill_zh(cards_conn)
        return 0

    gids = pending_grpids(stats_conn, cards_conn)
    print(f"待拉取 {len(gids)} 个 grpId")
    ok = 0
    for i, gid in enumerate(gids):
        card = fetch_card(gid)
        if card:
            cards_conn.execute(
                "INSERT OR REPLACE INTO cards(grp_id,name,type_line,colors,"
                "set_code,collector_number,name_zh,fetched_at) VALUES(?,?,?,?,?,?,?,?)",
                (card["grp_id"], card["name"], card["type_line"],
                 card["colors"], card["set_code"], card["collector_number"],
                 None, card["fetched_at"]),
            )
            cards_conn.commit()
            ok += 1
            print(f"  {gid} -> {card['name']}")
        time.sleep(0.12)  # Scryfall 限速保护
    print(f"完成：{ok}/{len(gids)}")
    # 新拉的卡顺手补中文
    if ok and "--no-zh" not in sys.argv:
        backfill_zh(cards_conn)
    return 0


if __name__ == "__main__":
    sys.exit(main())
