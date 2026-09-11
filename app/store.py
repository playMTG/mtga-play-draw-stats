# -*- coding: utf-8 -*-
"""SQLite 持久化：WAL 模式、match_id 幂等 upsert、子表随主行重写。"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from .config import Config
from .events import MatchRecord
from .ingest_marks import MARKS_SCHEMA
from .cards_sync import CARDS_SCHEMA as _CARDS_SCHEMA_BODY

SCHEMA_VERSION = 2

# 卡名库的表结构以 cards_sync 为准（单一事实源），这里只加一个 cards_db. 前缀，
# 用于「ATTACH 完立即建表」——否则全新解压时 ATTACH 出来的空库里没有 cards 表，
# 所有查询都会撞 "no such table: cards_db.cards"（R12.5）。
_CARDS_TABLE_DDL = _CARDS_SCHEMA_BODY.replace(
    "CREATE TABLE IF NOT EXISTS cards",
    "CREATE TABLE IF NOT EXISTS cards_db.cards",
)

_SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS matches (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  match_id TEXT NOT NULL UNIQUE,
  source TEXT NOT NULL DEFAULT 'log',
  event_id TEXT, start_time INTEGER, end_time INTEGER, duration_sec REAL,
  my_seat INTEGER, opponent_name TEXT, opponent_platform TEXT,
  play_draw TEXT, my_result TEXT, end_reason TEXT, total_turns INTEGER,
  my_deck_tag TEXT, my_rank_class TEXT, my_rank_level INTEGER,
  format_class TEXT, match_mode TEXT,
  is_abnormal INTEGER NOT NULL DEFAULT 0, abnormal_reason TEXT,
  opp_archetype_tag TEXT, opp_commander_name TEXT,
  is_bot INTEGER NOT NULL DEFAULT 0);

CREATE TABLE IF NOT EXISTS games (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  match_id TEXT NOT NULL, game_no INTEGER NOT NULL,
  result TEXT, reason TEXT, duration_sec REAL, play_draw TEXT);

CREATE TABLE IF NOT EXISTS mulligans (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  match_id TEXT NOT NULL, game_no INTEGER, seat INTEGER, kept_on INTEGER);

CREATE TABLE IF NOT EXISTS commanders (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  match_id TEXT NOT NULL, seat INTEGER, grp_id TEXT,
  card_name TEXT, colors TEXT, partner_idx INTEGER DEFAULT 0);

CREATE TABLE IF NOT EXISTS rank_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER, constructed_class TEXT, constructed_level INTEGER,
  limited_class TEXT, limited_level INTEGER);

CREATE TABLE IF NOT EXISTS opponent_profiles (
  commander_name TEXT PRIMARY KEY,
  archetype_user TEXT,          -- 手动打标（最高优先）
  archetype_auto TEXT,          -- 先验映射快照（commander_archetypes.json）
  updated_at INTEGER);

CREATE UNIQUE INDEX IF NOT EXISTS uq_rank_snap
  ON rank_snapshots(IFNULL(ts,0), constructed_class, constructed_level,
                    limited_class, limited_level);

CREATE INDEX IF NOT EXISTS idx_games_match ON games(match_id);
CREATE INDEX IF NOT EXISTS idx_mull_match ON mulligans(match_id);
CREATE INDEX IF NOT EXISTS idx_cmdr_match ON commanders(match_id);
CREATE INDEX IF NOT EXISTS idx_matches_start ON matches(start_time);
""" + MARKS_SCHEMA


def connect(db_path: Path, cards_db_path: Path | None = None) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False：FastAPI 端点跑在线程池，连接跨线程共用（配合 main.py 的全局锁）
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # 回填/监听线程与 API 会并发写库，等锁时间放宽到 15 秒（默认 5 秒偏紧）
    conn.execute("PRAGMA busy_timeout=15000")
    conn.executescript(_SCHEMA)
    _migrate(conn)
    # 挂载卡名库（grpId→卡名），缺失时优雅降级为仅 grpId
    # 注意：**不管文件是否存在都要 ATTACH**（R12.1）。全新安装时 data/mtga_cards.db
    # 还不存在，而它是在启动后被 cards_db_connect 创建的；如果这里因为文件不存在
    # 就跳过挂载，主连接此后永远看不到 cards 表，补齐了卡名页面也读不出来。
    if cards_db_path:
        try:
            cards_db_path.parent.mkdir(parents=True, exist_ok=True)
            conn.execute("ATTACH DATABASE ? AS cards_db", (str(cards_db_path),))
            # 全新解压时 ATTACH 出来的是一张空库，cards 表要等 cards_db_connect 才建。
            # 两者之间（以及客户端库缺失时的整个启动期）任何查询都会撞
            # "no such table: cards_db.cards"。这里无条件把表补出来，
            # 让「已挂载」与「表可用」保持一致（R12.5）。
            try:
                conn.execute(_CARDS_TABLE_DDL)
                conn.commit()
            except sqlite3.OperationalError:
                pass  # 只读挂载等场景：降级为仅 grpId
            # 迁移：旧版卡名库缺 name_zh 列（中文卡名，M4），幂等补齐
            try:
                conn.execute("SELECT name_zh FROM cards_db.cards LIMIT 1")
            except sqlite3.OperationalError:
                try:
                    conn.execute("ALTER TABLE cards ADD COLUMN name_zh TEXT")
                except sqlite3.OperationalError:
                    pass  # 表还没建/只读挂载等场景：降级为仅英文名
        except sqlite3.OperationalError:
            pass
    conn.execute(
        "INSERT INTO meta(key, value) VALUES('schema_version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (str(SCHEMA_VERSION),),
    )
    conn.commit()
    return conn


def _refresh_match_modes(conn: sqlite3.Connection, match_ids: list[str] | None = None) -> None:
    """按明确赛事规则与已保存局数刷新比赛模式。"""
    from .comparisons import match_mode
    where, args = "", []
    if match_ids:
        where = f"WHERE m.match_id IN ({','.join('?' * len(match_ids))})"
        args = match_ids
    rows = conn.execute(
        f"""SELECT m.match_id, m.event_id, m.match_mode, COUNT(DISTINCT g.game_no) game_count
              FROM matches m LEFT JOIN games g ON g.match_id=m.match_id
              {where}
             GROUP BY m.match_id""", args).fetchall()
    updates = []
    for row in rows:
        value = match_mode(row["event_id"], row["game_count"])
        if row["match_mode"] != value:
            updates.append((value, row["match_id"]))
    if updates:
        conn.executemany("UPDATE matches SET match_mode=? WHERE match_id=?", updates)


def _migrate(conn: sqlite3.Connection) -> None:
    """旧库幂等迁移：模式、Bot 标记与调度 seat 回填。"""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(matches)")}
    for col in ("my_deck_id", "my_deck_version"):
        if col not in cols:
            conn.execute(f"ALTER TABLE matches ADD COLUMN {col} TEXT")
    if "match_mode" not in cols:
        conn.execute("ALTER TABLE matches ADD COLUMN match_mode TEXT")
    if "is_bot" not in cols:
        conn.execute("ALTER TABLE matches ADD COLUMN is_bot INTEGER NOT NULL DEFAULT 0")
        conn.commit()
    # 2026-09-07 口径变更：投降/秒退/速胜都是正常结果，历史异常标记（no_game、
    # short_duration 等旧规则产物）全部清除；异常判定已废弃，仅保留 is_bot
    conn.execute(
        "UPDATE matches SET is_abnormal = 0, abnormal_reason = NULL "
        "WHERE is_abnormal = 1 OR abnormal_reason IS NOT NULL"
    )
    _refresh_match_modes(conn)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_matches_mode ON matches(match_mode)")
    conn.commit()
    # 调度记录迁移：kept_on IS NULL 的行是 2026-09-06 前的旧解析产物
    # （decision 未解析、kept_on 全空、Keep/Mulligan 混杂不可区分），直接废弃，
    # 由回填按新 decision 语义重新生成
    conn.execute("DELETE FROM mulligans WHERE kept_on IS NULL")
    # seat 回填：MulliganResp 无 playerSeatId → 旧数据全 NULL（=我方）
    conn.execute(
        """UPDATE mulligans SET seat=(
             SELECT m.my_seat FROM matches m WHERE m.match_id=mulligans.match_id)
           WHERE seat IS NULL
             AND match_id IN (SELECT match_id FROM matches WHERE my_seat IS NOT NULL)"""
    )
    conn.commit()


def tag_bot_decks(conn: sqlite3.Connection, patterns: list[str]) -> int:
    """按套牌名模式打 Bot 标记（不区分大小写）。返回受影响行数。"""
    n = 0
    for pat in patterns:
        pat = (pat or "").strip().lower()
        if not pat:
            continue
        cur = conn.execute(
            "UPDATE matches SET is_bot=1 WHERE LOWER(COALESCE(my_deck_tag,'')) LIKE ?",
            (f"%{pat}%",),
        )
        n += cur.rowcount
    conn.commit()
    return n


def _abnormal_flags(duration, total_turns, cfg: Config) -> tuple[int, str | None]:
    """投降/秒退都是玩家主动做出的正常结果，一律照常计分（2026-09-07 定稿）。

    曾经的规则先后用过"时长/回合阈值"和"0 回合 = no_game"，都会把真实的
    秒退/投降对局（计入游戏内胜场进度）误判为异常并从默认视图隐藏。
    现已彻底废弃异常判定：is_abnormal 恒为 0，仅保留 is_bot 排除 Bot 刷分局。
    """
    return (0, None)


def upsert_match(conn: sqlite3.Connection, m: MatchRecord, cfg: Config) -> bool:
    """幂等写入：同 match_id 更新主行并重写子表。返回是否新建档。"""
    duration = None
    if m.start_ms and m.end_ms and m.end_ms >= m.start_ms:
        duration = (m.end_ms - m.start_ms) / 1000.0

    existing = conn.execute(
        "SELECT id FROM matches WHERE match_id = ?", (m.match_id,)
    ).fetchone()
    is_new = existing is None
    is_abnormal, abnormal_reason = _abnormal_flags(duration, m.total_turns or None, cfg)

    conn.execute(
        """
        INSERT INTO matches(match_id, source, event_id, start_time, end_time,
            duration_sec, my_seat, opponent_name, opponent_platform, play_draw,
            my_result, end_reason, total_turns, is_abnormal, abnormal_reason,
            my_deck_tag)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(match_id) DO UPDATE SET
            source=excluded.source, event_id=COALESCE(excluded.event_id, matches.event_id),
            start_time=COALESCE(excluded.start_time, matches.start_time),
            end_time=COALESCE(excluded.end_time, matches.end_time),
            duration_sec=COALESCE(excluded.duration_sec, matches.duration_sec),
            my_seat=COALESCE(excluded.my_seat, matches.my_seat),
            opponent_name=COALESCE(excluded.opponent_name, matches.opponent_name),
            opponent_platform=COALESCE(excluded.opponent_platform, matches.opponent_platform),
            play_draw=COALESCE(excluded.play_draw, matches.play_draw),
            my_result=COALESCE(excluded.my_result, matches.my_result),
            end_reason=COALESCE(excluded.end_reason, matches.end_reason),
            total_turns=MAX(COALESCE(excluded.total_turns,0), COALESCE(matches.total_turns,0)),
            is_abnormal=excluded.is_abnormal, abnormal_reason=excluded.abnormal_reason,
            my_deck_tag=COALESCE(NULLIF(matches.my_deck_tag,''), excluded.my_deck_tag)
        """,
        (
            m.match_id, m.source, m.event_id, m.start_ms, m.end_ms, duration,
            m.my_seat, m.opponent_name, m.opponent_platform, m.play_draw,
            m.my_result, m.end_reason, m.total_turns or None,
            is_abnormal, abnormal_reason,
            m.my_deck_tag if m.my_deck_tag not in ("", None) else None,
        ),
    )

    conn.execute("UPDATE matches SET my_deck_id=COALESCE(?,my_deck_id), "
                 "my_deck_version=COALESCE(?,my_deck_version) WHERE match_id=?",
                 (m.my_deck_id, m.my_deck_version, m.match_id))
    mid = m.match_id
    for g in m.games:
        old = conn.execute("SELECT id FROM games WHERE match_id=? AND game_no=?",
                           (mid, g.game_no)).fetchone()
        if old:
            conn.execute("UPDATE games SET result=COALESCE(?,result), reason=COALESCE(?,reason), "
                         "play_draw=COALESCE(?,play_draw) WHERE id=?",
                         (g.result, g.reason, g.play_draw, old["id"]))
            continue
        conn.execute(
            "INSERT INTO games(match_id, game_no, result, reason, play_draw) VALUES(?,?,?,?,?)",
            (mid, g.game_no, g.result, g.reason, g.play_draw),
        )
    for mu in m.mulligans:
        seat = mu["seat"] if mu["seat"] is not None else m.my_seat
        old = conn.execute("SELECT id FROM mulligans WHERE match_id=? AND game_no IS ? "
                           "AND seat IS ?", (mid, mu["game_no"], seat)).fetchone()
        if old:
            conn.execute("UPDATE mulligans SET kept_on=MAX(COALESCE(kept_on,0),?) WHERE id=?",
                         (mu["kept_on"], old["id"]))
            continue
        # seat 缺失（MulliganResp 无 playerSeatId）时填 my_seat：
        # 该事件是本地客户端日志，只会记录我方调度
        conn.execute(
            "INSERT INTO mulligans(match_id, game_no, seat, kept_on) VALUES(?,?,?,?)",
            (mid, mu["game_no"],
             mu["seat"] if mu["seat"] is not None else m.my_seat,
             mu["kept_on"]),
        )
    for c in m.commanders:
        if conn.execute("SELECT 1 FROM commanders WHERE match_id=? AND seat IS ? AND grp_id=?",
                        (mid, c["seat"], str(c["grp_id"]))).fetchone():
            continue
        conn.execute(
            "INSERT INTO commanders(match_id, seat, grp_id, partner_idx) VALUES(?,?,?,?)",
            (mid, c["seat"], c["grp_id"], c["partner_idx"]),
        )
    _refresh_match_modes(conn, [mid])
    return is_new


def insert_rank(conn: sqlite3.Connection, snap) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO rank_snapshots(ts, constructed_class, constructed_level, "
        "limited_class, limited_level) VALUES(?,?,?,?,?)",
        (snap.ts_ms, snap.constructed_class, snap.constructed_level,
         snap.limited_class, snap.limited_level),
    )


def stats(conn: sqlite3.Connection) -> dict:
    q = conn.execute
    return {
        "matches": q("SELECT COUNT(*) c FROM matches").fetchone()["c"],
        "with_result": q(
            "SELECT COUNT(*) c FROM matches WHERE my_result IS NOT NULL").fetchone()["c"],
        "with_commanders": q(
            "SELECT COUNT(DISTINCT match_id) c FROM commanders").fetchone()["c"],
        "abnormal": q("SELECT COUNT(*) c FROM matches WHERE is_abnormal=1").fetchone()["c"],
        "games": q("SELECT COUNT(*) c FROM games").fetchone()["c"],
        "mulligans": q("SELECT COUNT(*) c FROM mulligans").fetchone()["c"],
        "ranks": q("SELECT COUNT(*) c FROM rank_snapshots").fetchone()["c"],
    }
