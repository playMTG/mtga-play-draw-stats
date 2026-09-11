# -*- coding: utf-8 -*-
"""grpId → 卡名映射的自动同步：发现没见过的 grpId 就地从 Scryfall 拉取。

设计原则：
- 只拉 stats 库里出现过的 grpId（commanders / command_history），缓存永久有效；
- Scryfall 限速 10 req/s，逐个请求 + 120ms 间隔，走 curl（系统代理）；
- 面板启动时和监听到新对局后周期性调用 sync_pending_cards()，
  保证"第一次遇到的对手主将"自动补全卡名——无需手动跑脚本。

原逻辑在 tools/update_cards.py，已上移到本模块（CLI 保留为薄封装）。
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

SCRYFALL_API = "https://api.scryfall.com/cards/arena/{gid}"
SCRYFALL_ZH = "https://api.scryfall.com/cards/{set}/{cn}/zhs"  # zhs=简体中文

# cards 表的权威结构定义（单一事实源）。
# store.connect() 会 import 它来给 cards_db 里的表建 DDL（见 R12.5），
# 修改这里时两边自动保持一致，避免 schema 漂移。
CARDS_SCHEMA = """
CREATE TABLE IF NOT EXISTS cards (
  grp_id TEXT PRIMARY KEY,
  name TEXT,
  type_line TEXT,
  colors TEXT,
  fetched_at INTEGER,
  set_code TEXT,
  collector_number TEXT,
  name_zh TEXT,
  source TEXT,
  zh_tried INTEGER NOT NULL DEFAULT 0
);
"""

# 兼容旧名（模块内部使用）
_CARDS_SCHEMA = CARDS_SCHEMA


def cards_db_connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(_CARDS_SCHEMA)
    # 迁移（M4）：中文卡名 + 定位信息（set/collector_number，用于查本地化）
    # 迁移（R12.1）：source 记录卡名来源（client=本机客户端库 / scryfall / 快照）；
    # zh_tried 记录中文译名是否已查询过，避免「本就无中文印刷」的卡每轮重试
    cols = {r[1] for r in conn.execute("PRAGMA table_info(cards)")}
    for col in ("set_code", "collector_number", "name_zh", "source"):
        if col not in cols:
            conn.execute(f"ALTER TABLE cards ADD COLUMN {col} TEXT")
    if "zh_tried" not in cols:
        conn.execute("ALTER TABLE cards ADD COLUMN zh_tried INTEGER NOT NULL DEFAULT 0")
    conn.commit()
    return conn


def stats_grpids(stats_conn: sqlite3.Connection) -> set[str]:
    """stats 库里出现过的全部 grpId（主将 + 历史主将），只保留数字形态。"""
    gids = {r["grp_id"] for r in stats_conn.execute(
        "SELECT DISTINCT grp_id FROM commanders")}
    if _has_table(stats_conn, "command_history"):
        gids |= {r["grp_id"] for r in stats_conn.execute(
            "SELECT DISTINCT grp_id FROM command_history")}
    return {str(g) for g in gids if g and str(g).isdigit()}


def pending_grpids(stats_conn: sqlite3.Connection,
                   cards_conn: sqlite3.Connection) -> list[str]:
    """stats 库里出现过、卡名库还没有的 grpId。"""
    known = {r["grp_id"] for r in cards_conn.execute("SELECT grp_id FROM cards")}
    return sorted(g for g in stats_grpids(stats_conn) if g not in known)


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def _curl_json_checked(url: str) -> tuple[bool, dict | None]:
    """curl 发请求（走系统代理，urllib 在本机环境被 Scryfall 拒绝）。

    返回 (是否拿到响应, 响应内容)。`ok=False` 表示网络/解析失败——
    调用方需要区分「明确没有这条数据」和「这次没问成」，避免把临时
    故障记成永久结论（R12.1 的 zh_tried 依赖这个区别）。
    """
    try:
        proc = subprocess.run(
            ["curl", "-s", "--max-time", "15", url],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        text = proc.stdout.strip()
        if not text:
            return (False, None)
        return (True, json.loads(text))
    except (OSError, json.JSONDecodeError) as e:
        print(f"  !! {url}: {e}", file=sys.stderr)
        return (False, None)


def _curl_json(url: str) -> dict | None:
    """兼容旧调用点：只关心内容、不关心成败时用它。"""
    ok, data = _curl_json_checked(url)
    return data if ok else None


def fetch_card(gid: str) -> dict | None:
    ok, data = _curl_json_checked(SCRYFALL_API.format(gid=gid))
    if not ok or data is None:
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
    路由下查不到本地化；不剥掉前缀冒用原版印刷，缺译名时保留英文。
    """
    return _fetch_zh_definitive(set_code, collector_number)[1]


def _fetch_zh_definitive(set_code: str, collector_number: str) -> tuple[bool, str | None]:
    """(是否得到明确答复, 中文名)。网络失败时 definitive=False，可安全重试。"""
    data_ok, data = _curl_json_checked(
        SCRYFALL_ZH.format(set=set_code, cn=collector_number))
    if not data_ok or data is None:
        return (False, None)
    if data.get("object") == "error":
        return (True, None)  # 该编号在 Scryfall 无中文印刷，是明确结论
    # 双面卡：printed_name 在 card_faces 里；单面卡在顶层
    name = data.get("printed_name")
    if not name and data.get("card_faces"):
        # 多名称牌只要一面有译名即可；其他面明确保留英文。
        if not any(f.get("printed_name") for f in data["card_faces"]):
            return (True, None)
        name = " // ".join(
            f.get("printed_name") or f.get("name") or ""
            for f in data["card_faces"]
        )
    if name and all(part.strip() for part in name.split(" // ")):
        return (True, name)
    return (True, None)


def backfill_zh(cards_conn: sqlite3.Connection, scope=None) -> int:
    """为缺中文名的卡补 name_zh；缺 set/collector_number 的先补 arena 元数据。

    scope 给定时只处理这些 grpId（监听线程只关心 stats 里出现过的卡，
    否则会去查整张卡名库）。`zh_tried=1` 的卡不再重试：Scryfall 明确
    没有中文印刷的卡（如 Arena 专属 A- 编号）否则每轮都会重来一遍。
    """
    sql = ("SELECT grp_id, name, set_code, collector_number FROM cards "
           "WHERE (name_zh IS NULL OR name_zh = '') AND zh_tried = 0")
    args: list = []
    if scope is not None:
        ids = [str(g) for g in scope]
        if not ids:
            return 0
        sql += f" AND grp_id IN ({','.join('?' * len(ids))})"
        args = ids
    rows = cards_conn.execute(sql, args).fetchall()
    ok = 0
    for r in rows:
        set_code, cn = r["set_code"], r["collector_number"]
        if not set_code or not cn:
            card = fetch_card(r["grp_id"])
            if not card or not card.get("set_code"):
                continue  # 元数据没拿到（多为网络问题）：不标记，下轮重试
            set_code, cn = card["set_code"], card["collector_number"]
            cards_conn.execute(
                "UPDATE cards SET set_code=?, collector_number=? WHERE grp_id=?",
                (set_code, cn, r["grp_id"]),
            )
            cards_conn.commit()
            time.sleep(0.12)
        definitive, zh = _fetch_zh_definitive(set_code, cn)
        if not definitive:
            continue  # 网络失败：保持 zh_tried=0，下轮重试
        if zh:
            cards_conn.execute(
                "UPDATE cards SET name_zh=?, zh_tried=1 WHERE grp_id=?",
                (zh, r["grp_id"]))
            ok += 1
            print(f"  {r['name']} -> {zh}")
        else:
            cards_conn.execute(
                "UPDATE cards SET zh_tried=1 WHERE grp_id=?", (r["grp_id"],))
            print(f"  {r['name']}: 无中文印刷，保留英文")
        cards_conn.commit()
        time.sleep(0.12)
    return ok


def sync_pending_cards(stats_conn: sqlite3.Connection,
                       cards_conn: sqlite3.Connection,
                       with_zh: bool = True) -> tuple[int, int]:
    """补全所有缺失 grpId（可选带中文名）。返回 (成功数, 待拉总数)。

    中文补全不再以「本轮拉到过英文」为条件：离线客户端库（R12.1）会先把
    英文名补齐，此时 pending 为空，但中文仍需要单独去查——所以 with_zh
    一律按 stats 里出现过的 grpId 走一遍（受 zh_tried 约束，不会反复重试）。
    """
    gids = pending_grpids(stats_conn, cards_conn)
    ok = 0
    for gid in gids:
        card = fetch_card(gid)
        if card:
            cards_conn.execute(
                """INSERT INTO cards(grp_id,name,type_line,colors,set_code,
                                     collector_number,name_zh,source,fetched_at)
                   VALUES(?,?,?,?,?,?,NULL,'scryfall',?)
                   ON CONFLICT(grp_id) DO UPDATE SET
                     name=COALESCE(excluded.name, cards.name),
                     type_line=COALESCE(excluded.type_line, cards.type_line),
                     colors=COALESCE(excluded.colors, cards.colors),
                     set_code=COALESCE(excluded.set_code, cards.set_code),
                     collector_number=COALESCE(excluded.collector_number,
                                               cards.collector_number),
                     source='scryfall',
                     fetched_at=excluded.fetched_at""",
                (card["grp_id"], card["name"], card["type_line"],
                 card["colors"], card["set_code"], card["collector_number"],
                 card["fetched_at"]),
            )
            cards_conn.commit()
            ok += 1
            print(f"  {gid} -> {card['name']}")
        time.sleep(0.12)  # Scryfall 限速保护
    if with_zh:
        backfill_zh(cards_conn, scope=stats_grpids(stats_conn))
    return ok, len(gids)
