# -*- coding: utf-8 -*-
"""FastAPI 入口：静态面板 + JSON API + 启动回填 + 日志监听线程。

仅绑定 127.0.0.1（隐私原则：不监听外网）。
启动：python -m uvicorn app.main:app --host 127.0.0.1 --port 8765
或：  python -m app.main
"""
from __future__ import annotations

import threading
import sqlite3
import time
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, Response

from . import store, stats
from .config import Config, load_config
from .events import SessionBuilder
from .watcher import LogWatcher

cfg = load_config()
app = FastAPI(title="MTGA 先后手统计", docs_url=None, redoc_url=None)

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

_conn: store.sqlite3.Connection | None = None
_db_lock = threading.Lock()  # SQLite 连接跨线程共用，读写统一加锁
_watcher: LogWatcher | None = None
_watcher_thread: threading.Thread | None = None
_state = {"watching": False, "last_events": 0}


def get_conn():
    global _conn
    if _conn is None:
        _conn = store.connect(cfg.db_path, cfg.root / "data" / "mtga_cards.db")
    return _conn


def _watch_loop() -> None:
    """后台监听线程：增量解析 → 幂等入库。

    同时 tail Player.log 与 Player-prev.log：MTGA 重启时主日志滚动成
    prev，两个 watcher 各自持有独立 SessionBuilder（builder 是有状态的
    会话解析器，跨文件共用会串场），入库层 match_id 幂等保证不重不漏。
    """
    global _watcher
    watchers = [
        LogWatcher(cfg.player_log),
        LogWatcher(cfg.prev_log),
    ]
    _watcher = watchers[0]
    my_id = cfg.my_player_id or None
    builders = [SessionBuilder(source="log", my_player_id=my_id)
                for _ in watchers]
    conn = get_conn()
    pending_matches: list = []
    pending_ranks: list = []

    def flush() -> None:
        """take 走各 builder 缓冲，失败时保留 pending 下轮重试（不丢数据）。"""
        for sb in builders:
            r = sb.take()
            pending_matches.extend(r.matches)
            pending_ranks.extend(r.ranks)
        for m in pending_matches:
            store.upsert_match(conn, m, cfg)
        for snap in pending_ranks:
            store.insert_rank(conn, snap)
        conn.commit()
        pending_matches.clear()
        pending_ranks.clear()

    while True:
        got = 0
        for w, sb in zip(watchers, builders):
            try:
                for rec in w.poll():
                    sb.feed(rec.text, rec.ts_ms)
                    got += 1
            except OSError:
                continue  # 文件暂时不可读（滚动中），下轮重试
        if got:
            _state["last_events"] = _state.get("last_events", 0) + got
            try:
                with _db_lock:
                    flush()
            except Exception:
                pass  # 单轮失败（如 DB busy）不杀线程，pending 下轮重试
        time.sleep(2)


@app.on_event("startup")
def on_startup() -> None:
    # 启动回填（幂等）：三个日志来源；服务端随后单独持一条连接
    from .backfill import backfill, collect_sources
    from .archive import archive_session_logs

    try:
        archived = archive_session_logs(cfg)  # P0：先归档防丢（客户端会清旧日志）
        if archived:
            _state["archived"] = archived
    except Exception:
        pass  # 归档失败不阻塞面板启动
    try:
        backfill(cfg, collect_sources(cfg))
    except Exception:
        pass  # 回填失败不阻塞面板启动（库中已有数据仍可看）
    conn = get_conn()
    # Bot 套牌打标（按 config 套牌名模式，幂等）
    try:
        store.tag_bot_decks(conn, cfg.get("bot_deck_patterns") or [])
    except Exception:
        pass
    if cfg.get("watch_on_start", True):
        t = threading.Thread(target=_watch_loop, daemon=True)
        t.start()
        _state["watching"] = True


@app.on_event("shutdown")
def on_shutdown() -> None:
    if _conn is not None:
        _conn.close()


# ---------- API ----------

def q(fn, *args, **kwargs):
    """在全局锁内执行一次数据库查询（SQLite 连接跨线程共用）。"""
    with _db_lock:
        return fn(get_conn(), *args, **kwargs)


@app.get("/api/overview")
def api_overview(exclude_abnormal: bool = True, exclude_bot: bool = True,
                 event: str | None = None, deck: str | None = None,
                 family: str | None = None):
    return q(stats.overview, exclude_abnormal, event, deck, exclude_bot,
             family=family)


@app.get("/api/matches")
def api_matches(exclude_abnormal: bool = True, exclude_bot: bool = True,
                event: str | None = None,
                deck: str | None = None, limit: int = 200, offset: int = 0,
                family: str | None = None):
    return q(stats.match_list, exclude_abnormal, event, deck,
             min(limit, 1000), offset, cfg.get("card_name_lang", "zh"),
             exclude_bot, family=family)


@app.get("/api/mulligans")
def api_mulligans(exclude_abnormal: bool = True, exclude_bot: bool = True):
    return q(stats.mulligan_stats, exclude_abnormal, exclude_bot)


@app.get("/api/commanders")
def api_commanders(exclude_abnormal: bool = True, exclude_bot: bool = True,
                   event: str | None = None, deck: str | None = None,
                   family: str | None = None):
    kw = dict(exclude_abnormal=exclude_abnormal, event=event, deck=deck,
              family=family)
    rows = q(stats.matchups, root=cfg.root, lang=cfg.get("card_name_lang", "zh"),
             exclude_bot=exclude_bot, **kw)
    coverage = q(stats.commander_coverage, exclude_bot=exclude_bot, **kw)
    return {"rows": rows, "coverage": coverage}


@app.get("/api/rank_curve")
def api_rank_curve(track: str = "constructed"):
    """段位曲线（仅带时间戳快照；相邻重复段位已合并）。"""
    if track not in ("constructed", "limited"):
        track = "constructed"
    return q(stats.rank_curve, track)


@app.get("/api/export")
def api_export(type: str = "matches", exclude_abnormal: bool = True,
               exclude_bot: bool = False,
               event: str | None = None, deck: str | None = None,
               family: str | None = None):
    """CSV 导出（UTF-8 BOM，Excel 直接打开不乱码）。type: matches | ranks。"""
    import csv
    import io
    from datetime import datetime as _dt

    if type not in ("matches", "ranks"):
        type = "matches"
    headers, rows = q(stats.export_rows, type, exclude_abnormal, event, deck,
                      exclude_bot, family=family)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(headers)
    w.writerows(rows)
    content = "\ufeff" + buf.getvalue()  # BOM：Excel 识别 UTF-8
    fname = f"mtga_{type}_{_dt.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return Response(
        content=content.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={fname}"},
    )


@app.get("/api/filters")
def api_filters(exclude_abnormal: bool = True, exclude_bot: bool = True,
                event: str | None = None, family: str | None = None):
    return q(stats.filter_options, exclude_abnormal, exclude_bot, event,
             family)


@app.get("/api/targeting")
def api_targeting(window: str = "30", exclude_abnormal: bool = True,
                  exclude_bot: bool = True):
    """被针对指数（§3.5）。window: 7 | 30 | all。"""
    days = None if window == "all" else (
        7 if window == "7" else 30)
    def _calc(conn):
        return stats.targeting_index(conn, cfg, days, exclude_abnormal,
                                     exclude_bot, root=cfg.root)
    return q(_calc)


@app.get("/api/status")
def api_status():
    def _get(conn):
        return {"db": store.stats(conn), "watching": _state["watching"],
                "last_events": _state["last_events"], "port": cfg.port}
    return q(_get)


@app.post("/api/opp_tag_by_name")
def api_opp_tag_by_name(commander: str = Query(...), tag: str = Query("")):
    """按主将名打标（主将档案表入口）。tag 为空 = 清除，恢复先验/无标签。"""
    def _set(conn):
        if commander.startswith("grpId:"):
            # 未知卡名，按 grpId 回填
            gid = commander.removeprefix("grpId:")
            where_sql = "c.grp_id = ?"
            args: tuple = (gid,)
        else:
            where_sql = ("COALESCE((SELECT name FROM cards_db.cards WHERE grp_id = c.grp_id), "
                         "'grpId:' || c.grp_id) = ?")
            args = (commander,)
        if tag and tag not in stats.ARCH_KEYS:
            return {"ok": False, "error": f"非法类型：{tag}"}
        conn.execute(
            """INSERT INTO opponent_profiles(commander_name, archetype_user, updated_at)
               VALUES(?,?,strftime('%s','now'))
               ON CONFLICT(commander_name) DO UPDATE SET
                 archetype_user=excluded.archetype_user,
                 updated_at=excluded.updated_at""",
            (commander, tag or None),
        )
        try:
            conn.execute(
                f"""UPDATE matches SET opp_archetype_tag=?
                   WHERE match_id IN (
                     SELECT c.match_id FROM commanders c
                     WHERE c.seat != (SELECT my_seat FROM matches m WHERE m.match_id = c.match_id)
                       AND {where_sql})""",
                (tag or None, *args),
            )
        except sqlite3.OperationalError:
            pass  # 卡名库未挂载时跳过回填
        conn.commit()
        return {"ok": True, "commander": commander, "tag": tag or None}
    return q(_set)


@app.post("/api/deck_tag")
def api_deck_tag(match_id: str = Query(...), tag: str = Query("")):
    """手动打标自己套牌名。"""
    def _set(conn):
        conn.execute("UPDATE matches SET my_deck_tag=? WHERE match_id=?",
                     (tag, match_id))
        conn.commit()
        return {"ok": True}
    return q(_set)


@app.post("/api/opp_tag")
def api_opp_tag(match_id: str = Query(...), tag: str = Query("")):
    """手动打标对手卡组类型。

    沉淀规则：写入 opponent_profiles.archetype_user，并回填该主将名下
    全部历史对局（同主将共享一个档案）。tag 为空 = 清除打标。
    """
    def _set(conn):
        row = conn.execute(
            """SELECT COALESCE(cards.name, 'grpId:' || c.grp_id) name
               FROM commanders c
               LEFT JOIN cards_db.cards cards ON cards.grp_id = c.grp_id
               WHERE c.match_id = ? AND c.seat != (SELECT my_seat FROM matches WHERE match_id = ?)
               LIMIT 1""",
            (match_id, match_id),
        ).fetchone()
        if row is None:
            return {"ok": False, "error": "该对局无对手主将记录"}
        name = row["name"]
        valid = stats.ARCH_KEYS + [""]
        if tag not in valid:
            return {"ok": False, "error": f"非法类型：{tag}"}
        conn.execute(
            """INSERT INTO opponent_profiles(commander_name, archetype_user, updated_at)
               VALUES(?,?,strftime('%s','now'))
               ON CONFLICT(commander_name) DO UPDATE SET
                 archetype_user=excluded.archetype_user,
                 updated_at=excluded.updated_at""",
            (name, tag or None),
        )
        # 回填该主将全部历史对局的展示标签（解析结果查询时动态计算，此处仅缓存）
        try:
            conn.execute(
                """UPDATE matches SET opp_archetype_tag=?
                   WHERE match_id IN (
                     SELECT c.match_id FROM commanders c
                     WHERE c.seat != (SELECT my_seat FROM matches m WHERE m.match_id = c.match_id)
                       AND COALESCE((SELECT name FROM cards_db.cards WHERE grp_id = c.grp_id),
                                    'grpId:' || c.grp_id) = ?)""",
                (tag or None, name),
            )
        except sqlite3.OperationalError:
            pass  # 卡名库未挂载时跳过回填，仅沉淀档案
        conn.commit()
        return {"ok": True, "commander": name}
    return q(_set)


# ---------- 静态面板 ----------

@app.get("/")
def index():
    return FileResponse(WEB_DIR / "index.html")


@app.get("/app.js")
def app_js():
    return FileResponse(WEB_DIR / "app.js", media_type="text/javascript")


@app.get("/chart.umd.js")
def chart_js():
    return FileResponse(WEB_DIR / "chart.umd.js", media_type="text/javascript")


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=cfg.port, log_level="warning")


if __name__ == "__main__":
    main()
