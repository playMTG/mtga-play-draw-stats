# -*- coding: utf-8 -*-
"""从本机已安装的 MTGA 客户端离线读取卡名（R12.1）。

背景：卡名此前只有一个来源——`data/mtga_cards.db`，而它由 Scryfall 同步
（`card_sync_enabled` 默认关闭）或社区快照导入（需要用户自己准备快照）填充。
结果是全新解压、未改配置的用户，对手主将全部显示成 `grpId:12345`。

而 MTGA 客户端本身就带一份卡牌数据库：

    MTGA_Data/Downloads/Raw/Raw_CardDatabase_<hash>.mtga

它虽然扩展名是 `.mtga`，实际是标准 SQLite（文件头 `SQLite format 3`），
结构为：

    Cards(GrpId, TitleId, ...)
    Localizations_enUS(LocId, Formatted, Loc)   -- LocId = TitleId, Formatted=1 为卡名

因此英文卡名可以完全离线、零联网、零额外数据地补齐。中文名不在这份库里
（客户端只提供 enUS/ptBR/frFR/itIT/deDE/esES/jaJP/koKR），仍走可选的
社区快照导入或 Scryfall 同步——与 README「中文优先、缺译名回落英文」一致。

安全边界：只读打开（`mode=ro`），不写客户端目录、不联网、不解析对局数据。
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

CARD_DB_GLOB = "Raw_CardDatabase_*.mtga"
# 单次 IN 查询的 grpId 上限（SQLite 老版本变量上限 999，留余量）
_CHUNK = 500

# 客户端卡名是 Unity 富文本。实测出现的标记：
#   <nobr>…</nobr>            排版提示（不换行），无语义
#   <sprite=… name="arena_a"> 炼金重平衡的「A-」前缀图标
#   <i>…</i>                  斜体
_ALCHEMY_SPRITE = re.compile(r'<sprite="[^"]*"\s+name="arena_a"\s*/?>', re.IGNORECASE)
_RICH_TAG = re.compile(r"<[^>]*>")


def clean_client_name(raw: str | None) -> str:
    """清洗客户端库里的富文本标记，还原成与 Scryfall 一致的英文卡名。

    `<sprite … name="arena_a">` 必须还原成字面量 `A-`：否则同一张牌在客户端
    叫 `Acererak the Archlich`、在 Scryfall 叫 `A-Acererak the Archlich`，
    `CardNames.get` 会因「英文身份不一致」丢弃已有的中文译名目录条目。
    注意卡名本身可以含 `&`（如 `Minsc & Boo, Timeless Heroes`），不能当作实体转义。
    """
    if not raw:
        return ""
    name = _ALCHEMY_SPRITE.sub("A-", str(raw))
    name = _RICH_TAG.sub("", name)
    return " ".join(name.split()).strip()


def _ro_uri(path: Path) -> str:
    """SQLite 只读 URI。Windows 路径含空格/括号，必须走 as_uri 转义。"""
    return path.as_uri() + "?mode=ro"


def find_card_database(raw_dirs: list[Path]) -> Path | None:
    """在候选 Raw 目录里找客户端卡牌库；多份时取最大的（最新下载）。"""
    best: Path | None = None
    best_size = -1
    for d in raw_dirs:
        try:
            if not d.is_dir():
                continue
            candidates = sorted(d.glob(CARD_DB_GLOB))
        except OSError:
            continue
        for f in candidates:
            try:
                size = f.stat().st_size
            except OSError:
                continue
            if size > best_size:
                best, best_size = f, size
    return best


def read_names(db_path: Path, gids: list[str]) -> dict[str, str]:
    """grpId → 英文卡名。只读；任何失败都返回已拿到的部分（不抛异常）。"""
    out: dict[str, str] = {}
    if not gids:
        return out
    try:
        conn = sqlite3.connect(_ro_uri(db_path), uri=True, timeout=5)
    except sqlite3.Error:
        return out
    try:
        conn.execute("PRAGMA query_only=1")
        for start in range(0, len(gids), _CHUNK):
            chunk = gids[start:start + _CHUNK]
            placeholders = ",".join("?" * len(chunk))
            try:
                rows = conn.execute(
                    f"""SELECT cd.GrpId,
                               COALESCE(
                                 (SELECT l.Loc FROM Localizations_enUS l
                                   WHERE l.LocId = cd.TitleId AND l.Formatted = 1
                                   LIMIT 1),
                                 (SELECT l.Loc FROM Localizations_enUS l
                                   WHERE l.LocId = cd.TitleId
                                   ORDER BY l.Formatted LIMIT 1))
                          FROM Cards cd
                         WHERE cd.GrpId IN ({placeholders})""",
                    chunk,
                ).fetchall()
            except sqlite3.Error:
                return out
            for gid, name in rows:
                cleaned = clean_client_name(name)
                if cleaned:
                    out[str(gid)] = cleaned
    finally:
        try:
            conn.close()
        except sqlite3.Error:
            pass
    return out


def seed_cards_db(cards_conn: sqlite3.Connection, stats_conn: sqlite3.Connection,
                  raw_dirs: list[Path]) -> dict:
    """把客户端库里的英文卡名写进本机卡名缓存 `data/mtga_cards.db`。

    只补缺失的 grpId（stats 库里出现过、卡名库还没有的），已存在的行不改名，
    因此不会覆盖 Scryfall 或快照导入的结果。返回本次处理结果供 /api/status 展示。
    """
    from .cards_sync import pending_grpids

    result = {
        "client_db": None, "pending": 0, "seeded": 0,
        "unresolved": 0, "error": None,
    }
    try:
        gids = pending_grpids(stats_conn, cards_conn)
    except sqlite3.Error as exc:
        result["error"] = f"pending:{type(exc).__name__}"
        return result
    result["pending"] = len(gids)
    if not gids:
        return result

    db = find_card_database(raw_dirs)
    if db is None:
        result["unresolved"] = len(gids)
        return result
    result["client_db"] = str(db)

    names = read_names(db, gids)
    for gid, name in names.items():
        try:
            cards_conn.execute(
                """INSERT INTO cards(grp_id, name, source) VALUES(?,?,?)
                   ON CONFLICT(grp_id) DO UPDATE SET
                     name=COALESCE(cards.name, excluded.name),
                     source=COALESCE(cards.source, excluded.source)""",
                (gid, name, "client"),
            )
        except sqlite3.Error as exc:
            result["error"] = f"insert:{type(exc).__name__}"
            continue
    try:
        cards_conn.commit()
    except sqlite3.Error:
        pass
    result["seeded"] = len(names)
    result["unresolved"] = len(gids) - len(names)
    return result


def name_coverage(conn: sqlite3.Connection, root: Path, lang: str = "zh") -> dict:
    """当前展示口径下，对手主将的卡名覆盖情况（供页面提示用）。

    `named` 是能显示成真实卡名的 grpId 数；`missing` 会显示成 `grpId:xxxx`。
    """
    from .card_names import CardNames

    try:
        gids = [str(r[0]) for r in conn.execute(
            "SELECT DISTINCT grp_id FROM commanders WHERE grp_id IS NOT NULL")]
    except sqlite3.OperationalError:
        return {"total": 0, "named": 0, "missing": 0, "sample": []}
    names = CardNames(conn, lang, root)
    missing: list[str] = []
    for gid in gids:
        info = names.get(gid)
        if str(info.get("name") or "").startswith("grpId:"):
            missing.append(gid)
    return {
        "total": len(gids),
        "named": len(gids) - len(missing),
        "missing": len(missing),
        "sample": missing[:5],
    }
