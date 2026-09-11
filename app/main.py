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

from fastapi import FastAPI, Query, HTTPException
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
# 连接初始化单独用一把锁：q() 会在持有 _db_lock 的情况下调用 get_conn()，
# 若这里复用 _db_lock 就是自锁（R12.3）
_conn_lock = threading.Lock()
# 启动任务的「检查并在同一临界区置位」用锁（R12.3）
_boot_lock = threading.Lock()
_watcher: LogWatcher | None = None
_watcher_thread: threading.Thread | None = None
_stop_event = threading.Event()  # 通知后台线程退出（R11.3）
_state = {
    "watching": False,
    "last_events": 0,
    "boot_stage": None,
    "boot_error": None,
    "boot_done_at": None,
    "config_error": None,
}


def get_conn():
    """惰性建立全局连接（双检加锁）。

    首屏请求、启动回填线程和监听线程是并发起来的，此前无锁会让两个线程
    各自 connect 一次，后来者覆盖 _conn，先前那个连接连同它的 WAL 句柄
    被丢在一边继续被调用方使用（R12.3）。这里用独立的 _conn_lock 做双检：
    只有第一次真正需要建连接。
    """
    global _conn
    if _conn is not None:
        return _conn
    with _conn_lock:
        if _conn is None:
            _conn = store.connect(cfg.db_path, cfg.root / "data" / "mtga_cards.db")
        return _conn


def _safe_exists(path: Path) -> bool:
    """Path.exists 在 Windows 上可能因日志被独占抛 PermissionError。"""
    try:
        return path.exists()
    except OSError:
        return False


def _log_paths() -> list[Path]:
    return [p for p in (cfg.player_log, cfg.prev_log) if _safe_exists(p)]


def _detect_player_id() -> str | None:
    """config 优先；否则与 backfill 同源探测。探测失败返回 None，可重试。"""
    configured = (cfg.my_player_id or "").strip()
    if configured:
        return configured
    from .backfill import detect_player_id
    try:
        return detect_player_id(_log_paths())
    except OSError:
        return None


def _persist_player_id(player_id: str) -> None:
    """探测成功后写回 config.json，避免下次启动再丢身份。

    R11.3/H3：config.json 已存在且无法解析时**禁止**自动覆盖，
    否则会把损坏文件替换成只剩 my_player_id 的空配置。
    """
    import json
    from datetime import datetime

    cfg_file = cfg.root / "config.json"
    if cfg_file.exists():
        if getattr(cfg, "config_error", None):
            return  # 已损坏：保留原文件，等用户修复
        try:
            raw = cfg_file.read_text(encoding="utf-8")
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError("config.json 顶层必须是对象")
        except (json.JSONDecodeError, OSError, ValueError):
            # 读取/解析失败：备份损坏文件，绝不静默覆盖
            try:
                stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                bak = cfg_file.with_name(f"config.json.corrupt-{stamp}.bak")
                cfg_file.replace(bak)
                _state["config_error"] = f"配置损坏已备份为 {bak.name}，未自动改写"
            except OSError:
                _state["config_error"] = "配置损坏且无法备份，已放弃写回"
            return
    else:
        data = {}
    if data.get("my_player_id") == player_id:
        return
    data["my_player_id"] = player_id
    tmp = cfg_file.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(cfg_file)
    # 让当前进程后续探测/回填直接用上
    if isinstance(cfg._d, dict):
        cfg._d["my_player_id"] = player_id


def _watch_loop() -> None:
    """后台监听线程：增量解析 → 幂等入库。

    同时 tail Player.log 与 Player-prev.log：MTGA 重启时主日志滚动成
    prev，两个 watcher 各自持有独立 SessionBuilder（builder 是有状态的
    会话解析器，跨文件共用会串场），入库层 match_id 幂等保证不重不漏。
    """
    global _watcher
    try:
        _watch_loop_inner()
    except Exception as exc:
        _state["watching"] = False
        _state["last_error"] = f"watch_died:{type(exc).__name__}"
    finally:
        _state["watching"] = False


def _watch_loop_inner() -> None:
    global _watcher
    from .ingest_marks import IngestMarks

    conn = get_conn()
    marks = IngestMarks(conn)
    # 水位线：回填刚记录过这两个文件的消费位置，监听从这里接上，
    # 不再把整份 Player.log 从头重放一遍（R12.2）
    watchers = [
        LogWatcher(cfg.player_log, start_offset=marks.resume_offset(cfg.player_log)),
        LogWatcher(cfg.prev_log, start_offset=marks.resume_offset(cfg.prev_log)),
    ]
    _watcher = watchers[0]
    # 没有身份时座位/先后手/对手/胜负全都解析不出来。
    # 启动瞬间日志可能还没 reservedPlayers，或文件被 MTGA 独占，
    # 因此身份必须可重试，并在拿到后回填到进行中/最近闭合的对局。
    my_id = _detect_player_id()
    if my_id:
        _state["my_player_id"] = my_id
        _persist_player_id(my_id)
    builders = [SessionBuilder(source="log", my_player_id=my_id)
                for _ in watchers]
    pending_matches: list = []
    pending_ranks: list = []
    last_detect_attempt = 0.0
    _state["watching"] = True

    def save_marks() -> None:
        """只在没有未闭合对局时落水位线。

        中途落盘会让下次启动错过那一场的开头，后续事件就失去归属（R11.1 修
        的正是结果串场），所以宁可多重放一场也不在半场处记位置。
        """
        for w, sb in zip(watchers, builders):
            if sb.in_progress:
                continue
            marks.put(w.path, w.offset, w.last_ts)

    def ensure_identity() -> None:
        nonlocal my_id, last_detect_attempt
        if my_id:
            return
        now = time.time()
        # 日志轮换/客户端刚启动时 reservedPlayers 出现较晚，10s 重试足够
        if now - last_detect_attempt < 10:
            return
        last_detect_attempt = now
        found = _detect_player_id()
        if not found:
            return
        my_id = found
        _state["my_player_id"] = my_id
        _persist_player_id(my_id)
        for sb in builders:
            sb.set_player_id(my_id)

    def flush() -> None:
        """take 走各 builder 缓冲；每条 SAVEPOINT，失败只回滚该条（R11.3/H2）。"""
        for sb in builders:
            r = sb.take()
            pending_matches.extend(r.matches)
            pending_ranks.extend(r.ranks)
        for m in pending_matches:
            try:
                conn.execute("SAVEPOINT upsert_one")
                store.upsert_match(conn, m, cfg)
                conn.execute("RELEASE SAVEPOINT upsert_one")
            except Exception as exc:
                _state["dropped_matches"] = _state.get("dropped_matches", 0) + 1
                _state["last_drop"] = f"{type(exc).__name__}:{m.match_id}"
                try:
                    conn.execute("ROLLBACK TO SAVEPOINT upsert_one")
                    conn.execute("RELEASE SAVEPOINT upsert_one")
                except sqlite3.Error:
                    pass
        for snap in pending_ranks:
            try:
                conn.execute("SAVEPOINT insert_rank")
                store.insert_rank(conn, snap)
                conn.execute("RELEASE SAVEPOINT insert_rank")
            except Exception as exc:
                _state["dropped_ranks"] = _state.get("dropped_ranks", 0) + 1
                _state["last_drop"] = type(exc).__name__
                try:
                    conn.execute("ROLLBACK TO SAVEPOINT insert_rank")
                    conn.execute("RELEASE SAVEPOINT insert_rank")
                except sqlite3.Error:
                    pass
        conn.commit()
        pending_matches.clear()
        pending_ranks.clear()

    while not _stop_event.is_set():
        ensure_identity()
        got = 0
        for w, sb in zip(watchers, builders):
            try:
                for rec in w.poll():
                    sb.feed(rec.text, rec.ts_ms)
                    got += 1
            except OSError:
                continue  # 文件暂时不可读（滚动中），下轮重试
        if got or pending_matches or pending_ranks:
            _state["last_events"] = _state.get("last_events", 0) + got
            try:
                with _db_lock:
                    flush()
                    save_marks()
                _state["last_success_at"] = int(time.time()*1000)
                _state["last_error"] = None
            except Exception as exc:
                try:
                    conn.rollback()
                except sqlite3.Error:
                    pass
                _state["last_error"] = type(exc).__name__
        _stop_event.wait(2)


def _seed_client_cards(stats_conn, cards_conn) -> dict:
    """离线补齐卡名：只读本机 MTGA 客户端的卡牌库（R12.1）。

    客户端自带的 `Raw_CardDatabase_*.mtga` 是 SQLite，含全部英文卡名。
    这一步完全离线，是「开箱能看到卡名」的默认路径；中文译名仍走可选的
    联网同步或本地快照导入。
    """
    from .client_cards import seed_cards_db

    if not cfg.get("card_offline_seed", True):
        return {"client_db": None, "pending": 0, "seeded": 0,
                "unresolved": 0, "error": "disabled"}
    try:
        r = seed_cards_db(cards_conn, stats_conn, cfg.client_raw_dirs())
    except Exception as exc:  # 客户端目录异常不应影响面板
        return {"client_db": None, "pending": 0, "seeded": 0,
                "unresolved": 0, "error": f"{type(exc).__name__}"}
    if r.get("seeded"):
        _state["cards_seeded"] = _state.get("cards_seeded", 0) + r["seeded"]
    _state["cards_client_db"] = r.get("client_db")
    return r


def _cards_loop() -> None:
    """卡名维护线程：离线补齐（默认）→ 可选联网同步。

    离线部分每轮都跑：新遇到的对手主将从本机客户端库就地补英文名。
    联网部分只在 card_sync_enabled 打开时执行，且只补中文译名与元数据。
    """
    from .cards_sync import cards_db_connect, sync_pending_cards

    stats_conn = sqlite3.connect(cfg.db_path, check_same_thread=False)
    stats_conn.row_factory = sqlite3.Row
    cards_conn = cards_db_connect(cfg.root / "data" / "mtga_cards.db")
    online = bool(cfg.get("card_sync_enabled", False))
    while not _stop_event.is_set():
        try:
            _seed_client_cards(stats_conn, cards_conn)
        except Exception:
            pass  # 单轮失败不杀线程，下个周期重试
        if online:
            try:
                ok, total = sync_pending_cards(stats_conn, cards_conn)
                if total:
                    _state["cards_synced"] = _state.get("cards_synced", 0) + ok
            except Exception:
                pass  # 网络失败不杀线程，下个周期重试
        _stop_event.wait(300)
    try:
        stats_conn.close()
    except sqlite3.Error:
        pass


def _boot_tasks() -> None:
    """启动期的重活：归档会话日志 → 全量回填 → Bot 打标（全部幂等）。

    必须放在后台线程：历史日志累积到几百 MB 后全量解析要几十秒，阻塞在
    startup 里会让 uvicorn 迟迟不接受连接，外部健康探测（start.bat）会在
    服务其实正常的情况下误判为「启动失败」。

    R11.3/H1：各阶段错误写入 _state，经 /api/status 可见；失败可 POST
    /api/retry_boot 重试，不再静默 pass。
    """
    from .backfill import backfill, collect_sources
    from .archive import archive_session_logs

    _state["booting"] = True
    _state["boot_error"] = None
    _state["boot_stage"] = "archive"
    try:
        archived = archive_session_logs(cfg)  # P0：先归档防丢（客户端会清旧日志）
        _state["archived"] = archived or []
    except Exception as exc:
        _state["boot_error"] = f"archive:{type(exc).__name__}:{exc}"

    _state["boot_stage"] = "backfill"
    try:
        r = backfill(cfg, collect_sources(cfg))
        _state["boot_backfill"] = {
            "new": r.get("new"),
            "updated": r.get("updated"),
            "skipped": r.get("skipped"),
            "stats": r.get("stats"),
            "files": len(r.get("per_file") or []),
        }
    except Exception as exc:
        prev = _state.get("boot_error")
        msg = f"backfill:{type(exc).__name__}:{exc}"
        _state["boot_error"] = f"{prev}; {msg}" if prev else msg

    _state["boot_stage"] = "bot_tags"
    try:
        # 与 cards 阶段同样在锁内：这是写库操作，而首屏请求可能同时在建连接，
        # 锁外调用会与 API 的读写撞在一起（R12.3）
        with _db_lock:
            store.tag_bot_decks(get_conn(), cfg.get("bot_deck_patterns") or [])
    except Exception as exc:
        prev = _state.get("boot_error")
        msg = f"bot_tags:{type(exc).__name__}:{exc}"
        _state["boot_error"] = f"{prev}; {msg}" if prev else msg

    # 卡名离线补齐：回填入库后才知道有哪些 grpId，所以放在这里，
    # 保证第一次打开页面时对手主将已经是卡名而不是 grpId（R12.1）
    _state["boot_stage"] = "cards"
    try:
        from .cards_sync import cards_db_connect
        cards_conn = cards_db_connect(cfg.root / "data" / "mtga_cards.db")
        try:
            with _db_lock:
                _state["cards_boot"] = _seed_client_cards(get_conn(), cards_conn)
        finally:
            cards_conn.close()
    except Exception as exc:
        prev = _state.get("boot_error")
        msg = f"cards:{type(exc).__name__}:{exc}"
        _state["boot_error"] = f"{prev}; {msg}" if prev else msg

    _state["boot_stage"] = None
    _state["booting"] = False
    _state["boot_done_at"] = int(time.time() * 1000)
    # 回填完再挂监听，保持与旧版一致的先后顺序（避免与回填并发写库）
    if cfg.get("watch_on_start", True) and not _stop_event.is_set():
        global _watcher_thread
        if _watcher_thread is None or not _watcher_thread.is_alive():
            t = threading.Thread(target=_watch_loop, daemon=True)
            t.start()
            _watcher_thread = t


@app.on_event("startup")
def on_startup() -> None:
    if getattr(cfg, "config_error", None):
        _state["config_error"] = cfg.config_error
    # 先让 HTTP 服务立即可用，重活交给后台线程
    threading.Thread(target=_boot_tasks, daemon=True).start()
    # 卡名维护线程常驻：离线补齐默认开启，联网同步由 card_sync_enabled 决定
    threading.Thread(target=_cards_loop, daemon=True).start()


@app.on_event("shutdown")
def on_shutdown() -> None:
    _stop_event.set()
    t = _watcher_thread
    if t is not None and t.is_alive():
        t.join(timeout=5)
    with _db_lock:
        if _conn is not None:
            try:
                _conn.close()
            except sqlite3.Error:
                pass


# ---------- API ----------

def q(fn, *args, **kwargs):
    """在全局锁内执行一次数据库查询（SQLite 连接跨线程共用）。"""
    with _db_lock:
        return fn(get_conn(), *args, **kwargs)


def cards_joinable(conn) -> bool:
    """cards_db.cards 是否可查询。

    ATTACH 成功不代表表存在：全新解压时 data/mtga_cards.db 由本模块的
    _seed_client_cards 之后才建表，客户端卡牌库缺失的机器上也可能一直没有表。
    裸查会撞 "no such table: cards_db.cards"，所以拼 SQL 前先探一次（R12.5）。
    """
    try:
        conn.execute("SELECT 1 FROM cards_db.cards LIMIT 1")
        return True
    except sqlite3.OperationalError:
        return False


@app.get("/api/overview")
def api_overview(exclude_abnormal: bool = True, exclude_bot: bool = True,
                 event: str | None = None, deck: str | None = None,
                 family: str | None = None,
                 mode: str | None = Query(None, pattern="^(BO1|BO3|未知)$")):
    return q(stats.overview, exclude_abnormal, event, deck, exclude_bot,
             family=family, mode=mode)


@app.get("/api/matches")
def api_matches(exclude_abnormal: bool = True, exclude_bot: bool = True,
                event: str | None = None,
                deck: str | None = None, limit: int = Query(200, ge=1, le=1000), offset: int = Query(0, ge=0),
                family: str | None = None, day: str | None = None,
                mode: str | None = Query(None, pattern="^(BO1|BO3|未知)$")):
    try:
        return q(stats.match_list, exclude_abnormal, event, deck,
                 limit, offset, cfg.get("card_name_lang", "zh"),
                 exclude_bot, family=family, day=day, mode=mode)
    except ValueError:
        raise HTTPException(status_code=422, detail="日期格式应为 YYYY-MM-DD")


@app.get("/api/deck_detail")
def api_deck_detail(deck: str | None = None, deck_id: str | None = None,
                    deck_version: str | None = None,
                    scope: str = "last20", version: str | None = None,
                    mode: str | None = Query(None, pattern="^(BO1|BO3|未知)$"),
                    opponent_commander: str | None = None,
                    observation: str | None = None,
                    exclude_abnormal: bool = True, exclude_bot: bool = True):
    """套牌独立详情；身份不受首页赛事／赛制筛选影响。"""
    from .deck_detail import deck_detail
    try:
        return q(deck_detail, deck=deck, deck_id=deck_id,
                 deck_version=deck_version, scope=scope, version=version,
                 mode=mode,
                 opponent_commander=opponent_commander,
                 observation=observation,
                 exclude_abnormal=exclude_abnormal, exclude_bot=exclude_bot,
                 lang=cfg.get("card_name_lang", "zh"), root=cfg.root)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.get("/api/mulligans")
def api_mulligans(exclude_abnormal: bool = True, exclude_bot: bool = True,
                  event: str | None = None, deck: str | None = None, family: str | None = None,
                  mode: str | None = Query(None, pattern="^(BO1|BO3|未知)$")):
    return q(stats.mulligan_stats, exclude_abnormal, exclude_bot, event, deck, family, mode)


@app.get("/api/commanders")
def api_commanders(exclude_abnormal: bool = True, exclude_bot: bool = True,
                   event: str | None = None, deck: str | None = None,
                   family: str | None = None,
                   mode: str | None = Query(None, pattern="^(BO1|BO3|未知)$")):
    kw = dict(exclude_abnormal=exclude_abnormal, event=event, deck=deck,
              family=family, mode=mode)
    rows = q(stats.matchups, root=cfg.root, lang=cfg.get("card_name_lang", "zh"),
             exclude_bot=exclude_bot, **kw)
    coverage = q(stats.commander_coverage, exclude_bot=exclude_bot, **kw)
    return {"rows": rows, "coverage": coverage}


@app.get("/api/opponent_types")
def api_opponent_types(exclude_abnormal: bool = True, exclude_bot: bool = True,
                       event: str | None = None, deck: str | None = None,
                       family: str | None = None,
                       mode: str | None = Query(None, pattern="^(BO1|BO3|未知)$")):
    return q(stats.opponent_type_stats, exclude_abnormal, exclude_bot,
             event, deck, family, mode)


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
               family: str | None = None,
               mode: str | None = Query(None, pattern="^(BO1|BO3|未知)$")):
    """CSV 导出（UTF-8 BOM，Excel 直接打开不乱码）。type: matches | ranks。"""
    import csv
    import io
    from datetime import datetime as _dt

    if type not in ("matches", "ranks"):
        type = "matches"
    headers, rows = q(stats.export_rows, type, exclude_abnormal, event, deck,
                      exclude_bot, family=family, mode=mode)
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
                event: str | None = None, family: str | None = None,
                deck: str | None = None,
                mode: str | None = Query(None, pattern="^(BO1|BO3|未知)$")):
    return q(stats.filter_options, exclude_abnormal, exclude_bot, event,
             family, mode, deck)


@app.get("/api/targeting")
def api_targeting(window: str = "30", exclude_abnormal: bool = True,
                  exclude_bot: bool = True, event: str | None = None,
                  deck: str | None = None, family: str | None = None,
                  mode: str | None = Query(None, pattern="^(BO1|BO3|未知)$")):
    """被针对指数（§3.5）。window: 7 | 30 | all。"""
    days = None if window == "all" else (
        7 if window == "7" else 30)
    def _calc(conn):
        return stats.targeting_index(conn, cfg, days, exclude_abnormal,
                                     exclude_bot, root=cfg.root, event=event, deck=deck, family=family,
                                     mode=mode)
    return q(_calc)


@app.get("/api/daily")
def api_daily(day: str | None = None, exclude_abnormal: bool = True,
              exclude_bot: bool = True, event: str | None = None,
              deck: str | None = None, family: str | None = None,
              mode: str | None = Query(None, pattern="^(BO1|BO3|未知)$")):
    from .insights import daily_report
    try:
        return q(daily_report, day, exclude_abnormal, exclude_bot, event, deck, family, mode)
    except ValueError:
        raise HTTPException(status_code=422, detail="日期格式应为 YYYY-MM-DD")


@app.get("/api/status")
def api_status():
    from .client_cards import find_card_database, name_coverage

    def _get(conn):
        coverage = name_coverage(conn, cfg.root, cfg.get("card_name_lang", "zh"))
        # 启动早期还没跑过补齐时 _state 里没有记录，直接现场探测一次，
        # 避免页面短暂显示「未找到客户端库」
        client_db = _state.get("cards_client_db")
        if not client_db:
            found = find_card_database(cfg.client_raw_dirs())
            client_db = str(found) if found else None
        return {
            "db": store.stats(conn),
            "watching": _state["watching"],
            "booting": _state.get("booting", False),
            "boot_stage": _state.get("boot_stage"),
            "boot_error": _state.get("boot_error"),
            "boot_backfill": _state.get("boot_backfill"),
            "boot_done_at": _state.get("boot_done_at"),
            "config_error": _state.get("config_error") or getattr(cfg, "config_error", None),
            "last_events": _state["last_events"],
            "port": cfg.port,
            "last_success_at": _state.get("last_success_at"),
            "last_error": _state.get("last_error"),
            "my_player_id": _state.get("my_player_id") or cfg.my_player_id or None,
            "identity_ready": bool(_state.get("my_player_id") or cfg.my_player_id),
            "dropped_matches": _state.get("dropped_matches", 0),
            "last_drop": _state.get("last_drop"),
            "card_names": {
                **coverage,
                "client_db": client_db,
                "offline_seed": bool(cfg.get("card_offline_seed", True)),
                "online_sync": bool(cfg.get("card_sync_enabled", False)),
                "seeded": _state.get("cards_seeded", 0),
                "synced": _state.get("cards_synced", 0),
            },
        }
    return q(_get)


@app.post("/api/card_names_seed")
def api_card_names_seed():
    """手动触发一次卡名离线补齐（只读本机客户端卡牌库，不联网）。"""
    from .cards_sync import cards_db_connect

    try:
        cards_conn = cards_db_connect(cfg.root / "data" / "mtga_cards.db")
    except sqlite3.Error as exc:
        raise HTTPException(status_code=500, detail=f"卡名库不可用：{exc}")
    try:
        with _db_lock:
            r = _seed_client_cards(get_conn(), cards_conn)
    finally:
        cards_conn.close()
    return {"ok": True, **r}


@app.post("/api/retry_boot")
def api_retry_boot():
    """启动归档/回填失败后的手动重试入口（幂等，可重复调用）。

    「读 booting → 起线程」之间存在窗口：两次点按之间线程还没跑到置位，
    就会起两个回填线程并发写库（R12.3）。这里把检查与置位放进同一把锁，
    置位先生效，线程起来后再由 _boot_tasks 接管。
    """
    with _boot_lock:
        if _state.get("booting"):
            return {"ok": False, "error": "启动任务仍在进行中"}
        if not _state.get("boot_error"):
            return {"ok": True, "skipped": True, "message": "上次启动无错误"}
        _state["booting"] = True  # 先占位，避免窗口内重复起线程
    threading.Thread(target=_boot_tasks, daemon=True).start()
    return {"ok": True, "message": "已重新启动归档/回填"}


@app.post("/api/opp_tag_by_name")
def api_opp_tag_by_name(commander: str = Query(...), tag: str = Query("")):
    """按主将名打标（主将档案表入口）。tag 为空 = 清除，恢复先验/无标签。"""
    def _set(conn):
        if commander.startswith("grpId:"):
            # 未知卡名，按 grpId 回填
            gid = commander.removeprefix("grpId:")
            where_sql = "c.grp_id = ?"
            args: tuple = (gid,)
        elif cards_joinable(conn):
            where_sql = ("COALESCE((SELECT name FROM cards_db.cards WHERE grp_id = c.grp_id), "
                         "'grpId:' || c.grp_id) = ?")
            args = (commander,)
        else:
            # 卡名库无表：主将名只可能以 grpId:xxx 形态存在，别名匹配必然落空。
            # 不用裸查 cards_db，避免 "no such table"（R12.5）。
            where_sql = "0"
            args = ()
        if tag and tag not in stats.ARCH_KEYS:
            return {"ok": False, "error": f"非法类型：{tag}"}
        profile_key = commander
        if commander.startswith("grpId:"):
            try:
                row = conn.execute("SELECT name FROM cards_db.cards WHERE grp_id=?", (gid,)).fetchone()
                if row and row["name"]:
                    profile_key = row["name"]
            except sqlite3.OperationalError:
                pass
        conn.execute(
            """INSERT INTO opponent_profiles(commander_name, archetype_user, updated_at)
               VALUES(?,?,strftime('%s','now'))
               ON CONFLICT(commander_name) DO UPDATE SET
                 archetype_user=excluded.archetype_user,
                 updated_at=excluded.updated_at""",
            (profile_key, tag or None),
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

    明确的非主将构筑赛事只修改指定对局；争锋赛事继续写入主将档案，
    并回填同主将历史记录。tag 为空 = 清除打标。
    """
    def _set(conn):
        if tag not in stats.ARCH_KEYS + [""]:
            return {"ok": False, "error": f"非法类型：{tag}"}
        match = conn.execute(
            "SELECT match_id,event_id FROM matches WHERE match_id=?", (match_id,)
        ).fetchone()
        if match is None:
            return {"ok": False, "error": "找不到这场对局"}
        if stats.is_constructed_opponent_event(match["event_id"]):
            conn.execute("UPDATE matches SET opp_archetype_tag=? WHERE match_id=?",
                         (tag or None, match_id))
            conn.commit()
            return {"ok": True, "match_id": match_id, "tag": tag or None,
                    "scope": "match"}
        if "Brawl" not in (match["event_id"] or ""):
            return {"ok": False, "error": "该赛事不适用构筑对手类型标签"}
        if cards_joinable(conn):
            row = conn.execute(
                """SELECT COALESCE(cards.name, 'grpId:' || c.grp_id) name
                   FROM commanders c
                   LEFT JOIN cards_db.cards cards ON cards.grp_id = c.grp_id
                   WHERE c.match_id = ? AND c.seat != (SELECT my_seat FROM matches WHERE match_id = ?)
                   LIMIT 1""",
                (match_id, match_id),
            ).fetchone()
        else:
            # 卡名库无表：退化为纯 grpId 形态，不用裸 JOIN（R12.5）
            row = conn.execute(
                """SELECT 'grpId:' || c.grp_id name
                   FROM commanders c
                   WHERE c.match_id = ? AND c.seat != (SELECT my_seat FROM matches WHERE match_id = ?)
                     AND c.grp_id IS NOT NULL
                   LIMIT 1""",
                (match_id, match_id),
            ).fetchone()
        if row is None:
            return {"ok": False, "error": "该对局无对手主将记录"}
        name = row["name"]
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
    return FileResponse(WEB_DIR / "index.html", headers={"Cache-Control": "no-store"})


@app.get("/app.js")
def app_js():
    return FileResponse(WEB_DIR / "app.js", media_type="text/javascript",
                        headers={"Cache-Control": "no-store"})


@app.get("/chart.umd.js")
def chart_js():
    return FileResponse(WEB_DIR / "chart.umd.js", media_type="text/javascript")


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=cfg.port, log_level="warning")


if __name__ == "__main__":
    main()
