# -*- coding: utf-8 -*-
"""SQLite 持久化：WAL 模式、match_id 幂等 upsert、子表随主行重写。"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from .config import Config
from .events import MatchRecord

SCHEMA_VERSION = 1

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
  format_class TEXT,
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
"""


def connect(db_path: Path, cards_db_path: Path | None = None) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False：FastAPI 端点跑在线程池，连接跨线程共用（配合 main.py 的全局锁）
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    _migrate(conn)
    # 挂载卡名库（grpId→卡名），缺失时优雅降级为仅 grpId
    if cards_db_path and cards_db_path.exists():
        try:
            conn.execute("ATTACH DATABASE ? AS cards_db", (str(cards_db_path),))
            # 迁移：旧版卡名库缺 name_zh 列（中文卡名，M4），幂等补齐
            try:
                conn.execute("SELECT name_zh FROM cards_db.cards LIMIT 1")
            except sqlite3.OperationalError:
                try:
                    conn.execute("ALTER TABLE cards ADD COLUMN name_zh TEXT")
                except sqlite3.OperationalError:
                    pass  # 只读挂载等场景：降级为仅英文名
        except sqlite3.OperationalError:
            pass
    conn.execute(
        "INSERT INTO meta(key, value) VALUES('schema_version', ?) "
        "ON CONFLICT(key) DO NOTHING",
        (str(SCHEMA_VERSION),),
    )
    conn.commit()
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """旧库幂等迁移：is_bot 列（Bot 刷分局标记）、调度 seat 回填。"""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(matches)")}
    if "is_bot" not in cols:
        conn.execute("ALTER TABLE matches ADD COLUMN is_bot INTEGER NOT NULL DEFAULT 0")
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
    """异常局 = 没真正打起来的局：回合数据为 0/缺失（对手秒退，GRE 未到）。

    短时长但回合数 > 0 的对局是真实胜负（争锋里对手提前投降很常见，
    且计入游戏内胜场进度），照常计分 —— “打得快”≠“没打”。
    旧规则（时长/回合阈值）会把速胜误判成异常并从默认视图隐藏。
    """
    if total_turns is None or total_turns <= 0:
        return (1, "no_game")
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
            my_deck_tag=COALESCE(matches.my_deck_tag, excluded.my_deck_tag)
        """,
        (
            m.match_id, m.source, m.event_id, m.start_ms, m.end_ms, duration,
            m.my_seat, m.opponent_name, m.opponent_platform, m.play_draw,
            m.my_result, m.end_reason, m.total_turns or None,
            is_abnormal, abnormal_reason, m.my_deck_tag,
        ),
    )

    if not is_new:
        # 子表重写（幂等）
        for table in ("games", "mulligans", "commanders"):
            conn.execute(f"DELETE FROM {table} WHERE match_id=?", (m.match_id,))

    mid = m.match_id
    for g in m.games:
        conn.execute(
            "INSERT INTO games(match_id, game_no, result, reason, play_draw) VALUES(?,?,?,?,?)",
            (mid, g.game_no, g.result, g.reason, g.play_draw),
        )
    for mu in m.mulligans:
        # seat 缺失（MulliganResp 无 playerSeatId）时填 my_seat：
        # 该事件是本地客户端日志，只会记录我方调度
        conn.execute(
            "INSERT INTO mulligans(match_id, game_no, seat, kept_on) VALUES(?,?,?,?)",
            (mid, mu["game_no"],
             mu["seat"] if mu["seat"] is not None else m.my_seat,
             mu["kept_on"]),
        )
    for c in m.commanders:
        conn.execute(
            "INSERT INTO commanders(match_id, seat, grp_id, partner_idx) VALUES(?,?,?,?)",
            (mid, c["seat"], c["grp_id"], c["partner_idx"]),
        )
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
