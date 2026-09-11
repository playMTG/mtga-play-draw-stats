# -*- coding: utf-8 -*-
"""统计层——全项目唯一的统计口径实现（DESIGN §3.6）。

口径约定（不得在前端或别处重算）：
- 分母为 match 层：一场 = 1 样本（BO3 不按局数拆分）；
- 异常局默认排除，include_abnormal=True 时才计入；
- 无胜负结果的行（my_result IS NULL）一律不计入胜率；
- 时间一律 epoch 毫秒存储，聚合时转本地日期。
"""
from __future__ import annotations

import math
import sqlite3
from datetime import datetime
from pathlib import Path

from .event_names import friendly_event
from .card_names import CardNames

from .targeting import (binom_cdf, binom_sf, chi2_sf, luck_label,
                        max_loss_streak, p_to_score, streak_sf)

Z95 = 1.959963984540054


def wilson(wins: int, n: int, z: float = Z95) -> tuple[float, float]:
    """Wilson 分数区间（小样本安全，不会越界 0-100）。返回 (low, high) 比例值。"""
    if n <= 0:
        return (0.0, 0.0)
    p = wins / n
    z2 = z * z
    denom = 1 + z2 / n
    center = (p + z2 / (2 * n)) / denom
    half = (z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n))) / denom
    lo = 0.0 if wins == 0 else max(0.0, center - half)  # 边界精确钳位（防浮点残差）
    hi = 1.0 if wins == n else min(1.0, center + half)
    return (lo, hi)


def wr(wins: int, n: int) -> dict:
    """胜率聚合对象：场次/胜场/胜率/Wilson 区间（百分比，保留 1 位）。"""
    lo, hi = wilson(wins, n)
    return {
        "n": n,
        "wins": wins,
        "wr": round(wins * 100.0 / n, 1) if n else None,
        "lo": round(lo * 100.0, 1),
        "hi": round(hi * 100.0, 1),
    }


_BASE_WHERE = "my_result IS NOT NULL"


def event_family(event_id: str) -> str:
    """把原始 event_id 归入赛制大类（学 Untapped 的 format 筛选粒度）。"""
    if event_id.startswith("MWM_"):
        return "每周魔法"
    if "Brawl" in event_id:
        return "争锋"
    if "Draft" in event_id:
        return "轮抽"
    if "Sealed" in event_id:
        return "现开"
    if event_id == "Ladder" or event_id.endswith("_Ladder"):
        return "排位天梯"
    if event_id == "Play" or event_id.endswith("_Play"):
        return "自由对战"
    if "Event" in event_id:
        return "构组赛"
    return "其他"


def _family_event_ids(conn: sqlite3.Connection, family: str) -> list[str]:
    ids = [r[0] for r in conn.execute(
        "SELECT DISTINCT event_id FROM matches WHERE event_id IS NOT NULL")]
    return [e for e in ids if event_family(e) == family]


def _event_scope(event: str | None, family: str | None,
                 conn: sqlite3.Connection | None = None,
                 col: str = "event_id") -> tuple[str | None, list]:
    """赛事级过滤条件（event 优先于 family）。family 展开为 IN 列表。"""
    if event:
        return f"{col} = ?", [event]
    if family:
        ids = _family_event_ids(conn, family) if conn is not None else []
        if not ids:
            return "1=0", []
        return f"{col} IN ({','.join('?' * len(ids))})", ids
    return None, []


def _filters(conn: sqlite3.Connection, event: str | None, deck: str | None,
             family: str | None = None, mode: str | None = None) -> tuple[list[str], list]:
    conds, args = [], []
    c, a = _event_scope(event, family, conn)
    if c:
        conds.append(c)
        args.extend(a)
    if deck:
        conds.append("COALESCE(my_deck_tag, '') = ?")
        args.append(deck)
    if mode:
        conds.append("match_mode = ?")
        args.append(mode)
    return conds, args


def overview(conn: sqlite3.Connection, exclude_abnormal: bool = True,
             event: str | None = None, deck: str | None = None,
             exclude_bot: bool = True, family: str | None = None,
             mode: str | None = None) -> dict:
    """总览：整体与先后手拆分 + 按赛事/套牌分组 + 趋势（按日）。"""
    conds, args = _filters(conn, event, deck, family, mode)
    stat_conds = list(conds)
    if exclude_abnormal:
        conds.append("is_abnormal = 0")
    if exclude_bot:
        conds.append("is_bot = 0")
    where = " AND ".join([_BASE_WHERE] + conds)

    # 被排除场次（异常/Bot）：仅统计因这两个开关而被隐藏的场次，用于前端提示
    hidden = 0
    if exclude_abnormal or exclude_bot:
        hwhere = " AND ".join(
            [_BASE_WHERE] + stat_conds + ["(is_abnormal = 1 OR is_bot = 1)"]
        )
        hidden = conn.execute(
            f"SELECT COUNT(*) FROM matches WHERE {hwhere}", args
        ).fetchone()[0]

    total = conn.execute(
        f"SELECT SUM(my_result='win') w, COUNT(*) n FROM matches WHERE {where}",
        args,
    ).fetchone()

    pd = conn.execute(
        f"SELECT play_draw, SUM(my_result='win') w, COUNT(*) n "
        f"FROM matches WHERE {where} AND play_draw IS NOT NULL "
        f"GROUP BY play_draw",
        args,
    ).fetchall()
    play = next((r for r in pd if r["play_draw"] == "play"), None)
    draw = next((r for r in pd if r["play_draw"] == "draw"), None)

    by_event = conn.execute(
        f"SELECT COALESCE(event_id, '(unknown)') k, "
        f"SUM(my_result='win') w, COUNT(*) n "
        f"FROM matches WHERE {where} GROUP BY k ORDER BY n DESC",
        args,
    ).fetchall()

    by_deck = conn.execute(
        f"SELECT COALESCE(NULLIF(my_deck_tag, ''), '(未标注)') k, "
        f"SUM(my_result='win') w, COUNT(*) n "
        f"FROM matches WHERE {where} GROUP BY k ORDER BY n DESC",
        args,
    ).fetchall()

    # 按日趋势（本地时区）
    trend = conn.execute(
        f"SELECT date(start_time/1000, 'unixepoch', 'localtime') d, "
        f"SUM(my_result='win') w, COUNT(*) n "
        f"FROM matches WHERE {where} AND start_time IS NOT NULL "
        f"GROUP BY d ORDER BY d",
        args,
    ).fetchall()

    # 按周趋势
    trend_w = conn.execute(
        f"SELECT date(start_time/1000, 'unixepoch', 'localtime', '-6 days', 'weekday 0') wk, "
        f"SUM(my_result='win') w, COUNT(*) n "
        f"FROM matches WHERE {where} AND start_time IS NOT NULL "
        f"GROUP BY wk ORDER BY wk",
        args,
    ).fetchall()

    pn, dn = (play['n'] if play else 0), (draw['n'] if draw else 0)
    return {
        "play_draw_rates": {'play': pn, 'draw': dn, 'unknown': total['n']-pn-dn,
                            'play_rate': round(100*pn/(pn+dn),1) if pn+dn else None,
                            'draw_rate': round(100*dn/(pn+dn),1) if pn+dn else None},
        "total": wr(total["w"] or 0, total["n"]),
        "hidden": hidden,
        "on_play": wr(play["w"], play["n"]) if play else wr(0, 0),
        "on_draw": wr(draw["w"], draw["n"]) if draw else wr(0, 0),
        "by_event": [{"key": r["k"], "label": friendly_event(r["k"]), **wr(r["w"] or 0, r["n"])} for r in by_event],
        "by_deck": [{"key": r["k"], **wr(r["w"] or 0, r["n"])} for r in by_deck],
        "trend_daily": [{"key": r["d"], **wr(r["w"] or 0, r["n"])} for r in trend],
        "trend_weekly": [{"key": r["wk"], **wr(r["w"] or 0, r["n"])} for r in trend_w],
    }


ARCH_KEYS = ["Aggro", "Control", "Combo", "Ramp", "Midrange", "Other"]


def is_constructed_opponent_event(event_id: str | None) -> bool:
    """是否适合用非主将构筑的“对手类型”标签。

    只纳入规则明确的排位、自由对战、构组赛及名称明确含 Constructed 的赛事；
    争锋、轮抽、现开、Momir 等无法确认规则的活动不进入缺失分母。
    R11.4/M1：补全 MWM AllAccess / Artisan / Pauper 与 Decathlon 构筑项目。
    """
    event_id = event_id or ""
    if not event_id or any(key in event_id for key in ("Brawl", "Draft", "Sealed")):
        return False
    if any(key in event_id for key in ("Momir", "Jump_In", "JumpIn", "Cube")):
        return False
    if event_family(event_id) in {"排位天梯", "自由对战"}:
        return True
    # Decathlon 构筑项目（名称含 Decathlon 且已排除轮抽/现开）
    if "Decathlon" in event_id:
        return True
    # 周中魔法：排除特殊模式后，名称含明确构筑赛制则适用
    if event_id.startswith("MWM_"):
        mid = event_id[4:]
        if any(x in mid for x in ("Momir", "Brawl", "Draft", "Sealed", "Cube",
                                  "Chaos", "Omniscience")):
            return False
        return any(x in mid for x in (
            "AllAccess", "Artisan", "Pauper", "Standard", "Historic",
            "Explorer", "Timeless", "Alchemy", "Pioneer", "Shakeup",
            "Singleton", "Constructed",
        ))
    constructed_markers = (
        "Constructed", "Cons_Event", "Explorer_Event",
        "Metagame_Challenge", "Standard_Challenge", "Explorer_Challenge",
        "AllAccess", "HistoricArtisan", "Pauper", "Artisan",
    )
    return any(marker in event_id for marker in constructed_markers)


def opponent_type_stats(conn: sqlite3.Connection, exclude_abnormal: bool = True,
                        exclude_bot: bool = True, event: str | None = None,
                        deck: str | None = None, family: str | None = None,
                        mode: str | None = None) -> dict:
    """非主将构筑对局的人工类型覆盖和战绩；未标注不作自动推断。"""
    conds, args = _filters(conn, event, deck, family, mode)
    if exclude_abnormal:
        conds.append("is_abnormal = 0")
    if exclude_bot:
        conds.append("is_bot = 0")
    where = " AND ".join(["1=1"] + conds)
    candidates = [dict(row) for row in conn.execute(
        f"""SELECT match_id,event_id,opp_archetype_tag,my_result,play_draw
              FROM matches WHERE {where}""", args)]
    eligible = [row for row in candidates if is_constructed_opponent_event(row["event_id"])]
    tagged = [row for row in eligible if row["opp_archetype_tag"]]
    rows = []
    order = {key: i for i, key in enumerate(ARCH_KEYS)}
    for tag in sorted({row["opp_archetype_tag"] for row in tagged},
                      key=lambda value: (order.get(value, len(order)), value)):
        group = [row for row in tagged if row["opp_archetype_tag"] == tag]
        decided = [row for row in group if row["my_result"] in ("win", "loss")]
        wins = sum(row["my_result"] == "win" for row in decided)
        rows.append({
            "tag": tag, "n": len(group), "wins": wins,
            "losses": sum(row["my_result"] == "loss" for row in decided),
            "unknown_result": len(group) - len(decided),
            "play": sum(row["play_draw"] == "play" for row in group),
            "draw": sum(row["play_draw"] == "draw" for row in group),
            "win_rate": wr(wins, len(decided)),
        })
    return {
        "eligible": len(eligible), "known": len(tagged),
        "unknown": len(eligible) - len(tagged), "rows": rows,
        "labels": {"Aggro": "快攻", "Control": "控制", "Combo": "组合技",
                   "Ramp": "Ramp", "Midrange": "中速", "Other": "其他"},
        "note": "只统计明确的非主将构筑赛事；轮抽、现开、争锋及规则未知赛事不进入分母。类型全部来自逐场人工标注。",
    }
ARCH_ZH = {
    "Aggro": "快攻", "Control": "控制", "Combo": "组合技",
    "Ramp": "Ramp", "Midrange": "中速", "Other": "其他",
}


def load_priors(root) -> dict[str, str]:
    """主将→类型先验（commander_archetypes.json，可编辑）。"""
    import json
    p = Path(root) / "commander_archetypes.json"
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return {k: v for k, v in data.items() if not k.startswith("_") and v in ARCH_KEYS}
    except (json.JSONDecodeError, OSError):
        return {}


def archetype_map(conn: sqlite3.Connection, root) -> dict[str, str]:
    """合并类型解析：手动打标（opponent_profiles）> 先验映射。键为主将卡名。"""
    out = dict(load_priors(root))
    # 手动打标沉淀（user 优先，其次 auto 快照）
    try:
        for r in conn.execute(
            "SELECT commander_name, COALESCE(archetype_user, archetype_auto) a "
            "FROM opponent_profiles WHERE a IS NOT NULL"
        ):
            if r["a"]:
                out[r["commander_name"]] = r["a"]
    except sqlite3.OperationalError:
        pass  # 表尚未创建（旧库）时静默降级
    return out


def matchups(conn: sqlite3.Connection, exclude_abnormal: bool = True,
             event: str | None = None, deck: str | None = None,
             root=None, lang: str = "zh", exclude_bot: bool = True,
             family: str | None = None, mode: str | None = None) -> list[dict]:
    """对手主将档案：总/先手/后手胜率 + 卡名 + 类型标签。

    依赖 store.connect 已 ATTACH 卡名库为 cards_db（缺失时卡名降级为 grpId）。
    lang="zh" 时优先使用中文卡名（name_zh，缺失回落英文）。
    """
    conds = ["m.my_result IS NOT NULL"]
    args: list = []
    if exclude_abnormal:
        conds.append("m.is_abnormal = 0")
    if exclude_bot:
        conds.append("m.is_bot = 0")
    if event:
        conds.append("m.event_id = ?")
        args.append(event)
    elif family:
        c, a = _event_scope(None, family, conn, col="m.event_id")
        conds.append(c)
        args.extend(a)
    if deck:
        conds.append("COALESCE(m.my_deck_tag, '') = ?")
        args.append(deck)
    if mode:
        conds.append("m.match_mode = ?")
        args.append(mode)
    where = " AND ".join(conds)
    # 卡名库可能未挂载（测试库/未运行 update_cards）：动态决定是否 join
    try:
        conn.execute("SELECT 1 FROM cards_db.cards LIMIT 1")
        has_cards = True
    except sqlite3.OperationalError:
        has_cards = False
    name_base = "cards.name"
    if has_cards and lang == "zh":
        name_base = "COALESCE(cards.name_zh, cards.name)"
    name_expr = (f"COALESCE({name_base}, '未知 (grpId ' || c.grp_id || ')')"
                 if has_cards else "'grpId:' || c.grp_id")
    join_sql = ("LEFT JOIN cards_db.cards cards ON cards.grp_id = c.grp_id"
                if has_cards else "")
    rows = conn.execute(
        f"""SELECT c.grp_id k,
               {('cards.name' if has_cards else 'NULL')} canonical_name,
               {name_expr} name,
               SUM(m.my_result='win') w, COUNT(DISTINCT m.match_id) n,
               SUM(CASE WHEN m.play_draw='play' THEN 1 ELSE 0 END) pn,
               SUM(CASE WHEN m.play_draw='play' AND m.my_result='win' THEN 1 ELSE 0 END) pw,
               SUM(CASE WHEN m.play_draw='draw' THEN 1 ELSE 0 END) dn,
               SUM(CASE WHEN m.play_draw='draw' AND m.my_result='win' THEN 1 ELSE 0 END) dw
            FROM matches m
            JOIN commanders c ON c.match_id = m.match_id AND c.seat != m.my_seat
            {join_sql}
            WHERE {where}
            GROUP BY c.grp_id ORDER BY n DESC""",
        args,
    ).fetchall()
    arch = archetype_map(conn, root) if root else {}
    names = CardNames(conn, lang, root)
    return [
        {
            "key": r["k"],
            **names.get(r["k"]),
            "archetype": arch.get(r["canonical_name"]) or arch.get('grpId:' + str(r['k'])) or arch.get(r["name"]),
            **wr(r["w"] or 0, r["n"]),
            "on_play": wr(r["pw"] or 0, r["pn"]),
            "on_draw": wr(r["dw"] or 0, r["dn"]),
        }
        for r in rows
    ]


def commander_coverage(conn: sqlite3.Connection, exclude_abnormal: bool = True,
                       event: str | None = None, deck: str | None = None,
                       exclude_bot: bool = True,
                       family: str | None = None, mode: str | None = None) -> dict:
    """主将档案的样本覆盖率（口径与 matchups 相同的过滤条件）。

    背景：主将 grpId 只存在于本地日志的 GRE 事件里，Untapped 云史
    不含对手套牌信息——历史对局大量缺失主将记录，档案场次远小于
    总场次，必须在 UI 上明示，否则"对战 X 才 5 次"会被误读为解析丢数据。
    """
    conds, args = _filters(conn, event, deck, family, mode)
    if exclude_abnormal:
        conds.append("is_abnormal = 0")
    if exclude_bot:
        conds.append("is_bot = 0")
    where = " AND ".join([_BASE_WHERE] + conds)
    row = conn.execute(
        f"""SELECT COUNT(*) total,
               SUM(EXISTS(SELECT 1 FROM commanders c WHERE c.match_id=m.match_id))
                 with_cmdr
            FROM matches m WHERE {where}""",
        args,
    ).fetchone()
    from .insights import records
    eligible = [r for r in records(conn, exclude_abnormal, exclude_bot, event, deck, family, mode)
                if 'Brawl' in (r['event_id'] or '') and r['my_result'] is not None]
    known = [r for r in eligible if r['commanders']]
    dates = [ts_to_local_str(r['start_time']) for r in known if r['start_time']]
    return {"total": len(eligible), "with_cmdr": len(known),
            "all_total": row['total'] or 0, "first": dates[0] if dates else None,
            "last": dates[-1] if dates else None}


def match_list(conn: sqlite3.Connection, exclude_abnormal: bool = True,
               event: str | None = None, deck: str | None = None,
               limit: int = 500, offset: int = 0, lang: str = "zh",
               exclude_bot: bool = True, family: str | None = None, day=None,
               mode: str | None = None) -> dict:
    """对局明细（倒序），含明确记录的我方／对手主将与诊断字段。"""
    base_conds, base_args = _filters(conn, event, deck, family, mode)
    if day:
        datetime.strptime(day, '%Y-%m-%d')
        base_conds.append("date(start_time/1000,'unixepoch','localtime')=?")
        base_args.append(day)
    conds = list(base_conds)
    if exclude_abnormal:
        conds.append("is_abnormal = 0")
    if exclude_bot:
        conds.append("is_bot = 0")
    where = " AND ".join(["1=1"] + conds)

    names = CardNames(conn, lang)
    cmdr_expr = "GROUP_CONCAT(DISTINCT c.grp_id)"
    join_sql = ""

    rows = conn.execute(
        f"""SELECT m.match_id, m.event_id, m.start_time, m.duration_sec,
                   m.opponent_name, m.play_draw, m.my_result, m.end_reason,
                   m.total_turns, m.is_abnormal, m.abnormal_reason, m.is_bot,
                   m.my_deck_tag, m.my_deck_id, m.my_deck_version, m.source,
                   m.match_mode, m.opp_archetype_tag,
                   (SELECT SUM(mu.kept_on) FROM mulligans mu
                     WHERE mu.match_id=m.match_id
                       AND (mu.seat IS NULL OR mu.seat=m.my_seat)) my_mulls,
                   (SELECT {cmdr_expr} FROM commanders c {join_sql}
                     WHERE c.match_id=m.match_id AND c.seat!=m.my_seat) opp_cmdrs
                  ,(SELECT {cmdr_expr} FROM commanders c {join_sql}
                     WHERE c.match_id=m.match_id AND c.seat=m.my_seat) my_cmdrs
            FROM matches m WHERE {where}
            ORDER BY m.start_time DESC LIMIT ? OFFSET ?""",
        [*base_args, limit, offset],
    ).fetchall()
    games_by_match: dict[str, list[dict]] = {r["match_id"]: [] for r in rows}
    match_ids = list(games_by_match)
    for start in range(0, len(match_ids), 500):
        batch = match_ids[start:start + 500]
        if not batch:
            continue
        game_rows = conn.execute(
            f"""SELECT match_id, game_no, result, reason, play_draw, duration_sec
                  FROM games WHERE match_id IN ({','.join('?' * len(batch))})
                 ORDER BY match_id, game_no""", batch).fetchall()
        for game in game_rows:
            games_by_match[game["match_id"]].append({
                "game_no": game["game_no"], "result": game["result"],
                "reason": game["reason"], "play_draw": game["play_draw"],
                "duration_sec": game["duration_sec"],
            })
    total = conn.execute(
        f"SELECT COUNT(*) c FROM matches m WHERE {where}", base_args
    ).fetchone()["c"]
    # 被排除开关隐藏的场次（同赛制/套牌口径，但含异常/bot 局）——
    # 让“我的胜利去哪了”类困惑在界面上自解释
    hidden = 0
    if exclude_abnormal or exclude_bot:
        hide_conds = list(base_conds) + ["(is_abnormal = 1 OR is_bot = 1)"]
        hide_where = " AND ".join(["1=1"] + hide_conds)
        hidden = conn.execute(
            f"SELECT COUNT(*) c FROM matches m WHERE {hide_where}", base_args
        ).fetchone()["c"]
    return {
        "total": total,
        "hidden_by_filter": hidden,
        "rows": [
            {
                "match_id": r["match_id"],
                "event_id": r["event_id"],
                "event_label": friendly_event(r["event_id"]),
                "start_time": r["start_time"],
                "duration_sec": r["duration_sec"],
                "opponent_name": r["opponent_name"],
                "play_draw": r["play_draw"],
                "my_result": r["my_result"],
                "end_reason": r["end_reason"],
                "total_turns": r["total_turns"],
                "is_abnormal": bool(r["is_abnormal"]),
                "abnormal_reason": r["abnormal_reason"],
                "is_bot": bool(r["is_bot"]),
                "my_deck_tag": r["my_deck_tag"],
                "my_deck_id": r["my_deck_id"],
                "my_deck_version": r["my_deck_version"],
                "source": r["source"],
                "match_mode": r["match_mode"] or "未知",
                "opponent_type_eligible": is_constructed_opponent_event(r["event_id"]),
                "opp_archetype_tag": r["opp_archetype_tag"],
                "games": games_by_match.get(r["match_id"], []),
                "my_mulls": r["my_mulls"],
                "my_cards": ([names.get(g) for g in (r["my_cmdrs"] or "").split(",") if g]
                             if "Brawl" in (r["event_id"] or "") else []),
                "my_cmdrs": ([names.get(g)["name"] for g in (r["my_cmdrs"] or "").split(",") if g]
                             if "Brawl" in (r["event_id"] or "") else []),
                "opp_cards": ([names.get(g) for g in (r["opp_cmdrs"] or "").split(",") if g]
                              if "Brawl" in (r["event_id"] or "") else []),
                "opp_cmdrs": ([names.get(g)["name"] for g in (r["opp_cmdrs"] or "").split(",") if g]
                              if "Brawl" in (r["event_id"] or "") else []),
            }
            for r in rows
        ],
    }


def filter_options(conn: sqlite3.Connection, exclude_abnormal: bool = True,
                   exclude_bot: bool = True, event: str | None = None,
                   family: str | None = None, mode: str | None = None,
                   deck: str | None = None) -> dict:
    """筛选器候选项（赛制大类 → 赛事 → 比赛模式 → 套牌）。

    返回 families / events / decks，每项含 {value, label, n}，按场数降序。
    - families 始终全量（学 Untapped 的 format 粒度）
    - 传 family 时 events 只含该大类下的赛事，decks 按大类收窄
    - 传 event 时 decks 只含该赛事下的套牌
    场数口径与面板默认一致（排除异常局/Bot 局）。
    """
    base = []
    if exclude_abnormal:
        base.append("is_abnormal = 0")
    if exclude_bot:
        base.append("is_bot = 0")
    w = " AND ".join(base)
    w = f" AND {w}" if w else ""

    all_events = conn.execute(
        f"SELECT event_id v, COUNT(*) n FROM matches "
        f"WHERE event_id IS NOT NULL{w} GROUP BY event_id",
    ).fetchall()

    # 赛制大类聚合（始终全量）
    fam_n: dict[str, int] = {}
    for r in all_events:
        f = event_family(r["v"])
        fam_n[f] = fam_n.get(f, 0) + r["n"]
    families = [
        {"value": k, "label": k, "n": n}
        for k, n in sorted(fam_n.items(), key=lambda kv: (-kv[1], kv[0]))
    ]

    # 赛事列表：family 收窄
    event_mode_where = f"{w} AND match_mode = ?" if mode else w
    event_mode_args = [mode] if mode else []
    event_rows = conn.execute(
        f"SELECT event_id v, COUNT(*) n FROM matches "
        f"WHERE event_id IS NOT NULL{event_mode_where} GROUP BY event_id",
        event_mode_args,
    ).fetchall()
    events = [r for r in event_rows
              if family is None or event_family(r["v"]) == family]
    events.sort(key=lambda r: (-r["n"], r["v"]))

    # 套牌列表：event / family 收窄
    dk_args: list = []
    dk_cond = ""
    if event:
        dk_cond = " AND event_id = ?"
        dk_args.append(event)
    elif family:
        ids = _family_event_ids(conn, family)
        if ids:
            dk_cond = f" AND event_id IN ({','.join('?' * len(ids))})"
            dk_args.extend(ids)
        else:
            dk_cond = " AND 1=0"
    if mode:
        dk_cond += " AND match_mode = ?"
        dk_args.append(mode)
    decks = conn.execute(
        f"SELECT my_deck_tag v, COUNT(*) n FROM matches "
        f"WHERE my_deck_tag IS NOT NULL AND my_deck_tag != ''{w}{dk_cond} "
        f"GROUP BY my_deck_tag ORDER BY n DESC, v",
        dk_args,
    ).fetchall()

    # 模式在套牌之前：计数只受上游赛事范围影响，避免下游套牌因模式
    # 不匹配被重置后，模式选项仍残留旧套牌的数量。
    mode_conds, mode_args = _filters(conn, event, None, family)
    if exclude_abnormal:
        mode_conds.append("is_abnormal = 0")
    if exclude_bot:
        mode_conds.append("is_bot = 0")
    mode_where = " AND ".join(["1=1"] + mode_conds)
    mode_counts = {row["k"]: row["n"] for row in conn.execute(
        f"SELECT COALESCE(match_mode,'未知') k, COUNT(*) n FROM matches "
        f"WHERE {mode_where} GROUP BY k", mode_args)}
    return {
        "families": families,
        "events": [
            {"value": r["v"], "label": friendly_event(r["v"]), "n": r["n"]}
            for r in events
        ],
        "decks": [{"value": r["v"], "label": r["v"], "n": r["n"]} for r in decks],
        "modes": [{"value": key, "label": key, "n": mode_counts.get(key, 0)}
                  for key in ("BO1", "BO3", "未知")],
    }


RANK_CLASSES = ["Bronze", "Silver", "Gold", "Platinum", "Diamond", "Mythic"]
RANK_ZH = {"Bronze": "青铜", "Silver": "白银", "Gold": "黄金",
           "Platinum": "铂金", "Diamond": "钻石", "Mythic": "秘稀"}


def rank_score(cls: str | None, level: int | None) -> int | None:
    """段位 → 单调数值刻度：Bronze4=1 … Bronze1=4, Silver4=5 … Diamond1=20,
    Mythic=21（百分比不记录，秘稀统一一档）。未知段位返回 None。"""
    if cls not in RANK_CLASSES:
        return None
    idx = RANK_CLASSES.index(cls)
    if cls == "Mythic":
        return idx * 4 + 1  # 21
    if not isinstance(level, int) or not 1 <= level <= 4:
        return None
    return idx * 4 + (5 - level)


def score_label(score: int) -> str:
    """数值刻度 → 段位显示名（供图表坐标轴）。"""
    if score >= 21:
        return "秘稀"
    idx, rem = divmod(score - 1, 4)
    cls = RANK_CLASSES[idx] if 0 <= idx < len(RANK_CLASSES) else "?"
    return f"{RANK_ZH.get(cls, cls)}{4 - rem}"


def rank_curve(conn: sqlite3.Connection, track: str = "constructed") -> dict:
    """段位曲线：仅使用带时间戳的快照，相邻重复段位只保留首个点。

    track: constructed | limited。早期裸 JSON 行（ts=NULL）无时间上下文，
    无法定位，不参与曲线。
    """
    col = ("constructed_class" if track == "constructed" else "limited_class")
    lvl = ("constructed_level" if track == "constructed" else "limited_level")
    rows = conn.execute(
        f"SELECT ts, {col} cc, {lvl} cl FROM rank_snapshots "
        f"WHERE ts IS NOT NULL AND {col} IS NOT NULL "
        f"ORDER BY ts, id",
    ).fetchall()
    points = []
    last_score = None
    for r in rows:
        score = rank_score(r["cc"], r["cl"])
        if score is None:
            continue
        if score == last_score:
            continue  # 相邻重复：合并为一段
        points.append({
            "ts": r["ts"],
            "class": r["cc"],
            "level": r["cl"],
            "score": score,
            "label": f"{RANK_ZH.get(r['cc'], r['cc'])}{r['cl']}" if r["cc"] != "Mythic" else "秘稀",
        })
        last_score = score
    return {"track": track, "points": points}


def _csv_safe(value):
    """Excel/Sheets 公式注入防护（R11.5/M2）。

    对手名等外部文本可能以 = + - @ 开头；危险前缀加前置单引号。
    数字/空值原样返回；去掉控制字符与前后空白后再判断。
    """
    if value is None or isinstance(value, (int, float)):
        return value if value is not None else ""
    s = str(value)
    if not s:
        return ""
    # 去掉可能绕过前缀检测的控制字符/零宽字符
    cleaned = "".join(ch for ch in s if ch >= " " or ch in "\t\n\r")
    cleaned = cleaned.replace("﻿", "").replace("​", "").strip()
    if cleaned[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + cleaned
    return cleaned


def export_rows(conn: sqlite3.Connection, kind: str = "matches",
                exclude_abnormal: bool = True,
                event: str | None = None, deck: str | None = None,
                exclude_bot: bool = False,
                family: str | None = None, mode: str | None = None) -> tuple[list[str], list[list]]:
    """CSV 导出数据（kind: matches | ranks）。返回 (表头, 行)。

    exclude_abnormal / exclude_bot 仅作行过滤；导出列原样保留标记字段。
    文本单元格经 _csv_safe，防止 Excel 公式注入。
    """
    if kind == "ranks":
        rows = conn.execute(
            "SELECT ts, constructed_class, constructed_level, "
            "limited_class, limited_level FROM rank_snapshots ORDER BY ts, id"
        ).fetchall()
        headers = ["时间", "构组段位", "构组等级", "轮抽段位", "轮抽等级"]
        out = []
        for r in rows:
            out.append([
                ts_to_local_str(r["ts"]) or "",
                _csv_safe(r["constructed_class"] or ""),
                r["constructed_level"] if r["constructed_level"] is not None else "",
                _csv_safe(r["limited_class"] or ""),
                r["limited_level"] if r["limited_level"] is not None else "",
            ])
        return headers, out

    # matches
    conds, args = _filters(conn, event, deck, family, mode)
    if exclude_abnormal:
        conds.append("is_abnormal = 0")
    if exclude_bot:
        conds.append("is_bot = 0")
    where = " AND ".join(["1=1"] + conds)
    names = CardNames(conn)
    my_cmdr_sub = ("(SELECT GROUP_CONCAT(DISTINCT c.grp_id) FROM commanders c "
                   "WHERE c.match_id=m.match_id AND c.seat=m.my_seat)")
    cmdr_sub = ("(SELECT GROUP_CONCAT(DISTINCT c.grp_id) FROM commanders c "
                "WHERE c.match_id=m.match_id AND c.seat!=m.my_seat)")
    rows = conn.execute(
        f"""SELECT m.*, (SELECT SUM(mu.kept_on) FROM mulligans mu
                 WHERE mu.match_id=m.match_id
                   AND (mu.seat IS NULL OR mu.seat=m.my_seat)) my_mulls,
                {my_cmdr_sub} my_cmdrs, {cmdr_sub} opp_cmdrs
             FROM matches m WHERE {where} ORDER BY m.start_time""",
        args,
    ).fetchall()
    headers = ["match_id", "来源", "赛事", "比赛模式", "时间", "时长(秒)", "对手名",
               "先后手", "结果", "结束原因", "总回合", "异常", "异常原因",
               "我方套牌", "我方主将", "对手类型", "我方调度", "对手主将", "Bot局"]
    out = []
    for r in rows:
        is_brawl = "Brawl" in (r["event_id"] or "")
        out.append([
            _csv_safe(r["match_id"]), _csv_safe(r["source"]),
            _csv_safe(r["event_id"] or ""), _csv_safe(r["match_mode"] or "未知"),
            ts_to_local_str(r["start_time"]) or "",
            r["duration_sec"] if r["duration_sec"] is not None else "",
            _csv_safe(r["opponent_name"] or ""),
            _csv_safe(r["play_draw"] or ""),
            _csv_safe(r["my_result"] or ""),
            _csv_safe((r["end_reason"] or "").replace("ResultReason_", "")),
            r["total_turns"] if r["total_turns"] is not None else "",
            "是" if r["is_abnormal"] else "否",
            _csv_safe(r["abnormal_reason"] or ""),
            _csv_safe(r["my_deck_tag"] or ""),
            _csv_safe(" // ".join(names.get(g)["name"] for g in (r["my_cmdrs"] or "").split(",") if g)
                      if is_brawl else ""),
            _csv_safe(r["opp_archetype_tag"] or ""),
            r["my_mulls"],
            _csv_safe(" // ".join(names.get(g)["name"] for g in (r["opp_cmdrs"] or "").split(",") if g)
                      if is_brawl else ""),
            "是" if r["is_bot"] else "否",
        ])
    return headers, out


def mulligan_stats(conn: sqlite3.Connection, exclude_abnormal: bool = True,
                   exclude_bot: bool = True, event=None, deck=None, family=None,
                   mode=None) -> dict:
    """调度统计：我的每局调度次数分布 + 调度与胜负关联。"""
    conds, args = _filters(conn, event, deck, family, mode)
    if exclude_abnormal:
        conds.append("is_abnormal = 0")
    if exclude_bot:
        conds.append("is_bot = 0")
    where = " AND ".join(["my_result IS NOT NULL"] + conds)
    # seat IS NULL 视为我方：MulliganResp 是本地事件，只记录我方调度，
    # 旧数据（2026-09-06 前）seat 列全为 NULL；新数据由 upsert 自动填 my_seat
    dist = conn.execute(
        f"""SELECT mu.kept_on k, COUNT(*) n FROM mulligans mu
            JOIN matches m ON m.match_id=mu.match_id
            WHERE (mu.seat IS NULL OR mu.seat=m.my_seat) AND {where}
            GROUP BY k ORDER BY k""", args,
    ).fetchall()
    # 调过度的局 vs 没调的局胜率（kept_on>=1 = 本局有调度）
    agg = conn.execute(
        f"""SELECT CASE WHEN EXISTS(
                 SELECT 1 FROM mulligans mu WHERE mu.match_id=m.match_id
                   AND (mu.seat IS NULL OR mu.seat=m.my_seat)
                   AND mu.kept_on >= 1) THEN 'mulligan'
                 WHEN EXISTS(SELECT 1 FROM mulligans mu WHERE mu.match_id=m.match_id
                   AND (mu.seat IS NULL OR mu.seat=m.my_seat) AND mu.kept_on IS NOT NULL)
                 THEN 'clean' ELSE 'unknown' END k,
               SUM(m.my_result='win') w, COUNT(*) n
            FROM matches m WHERE {where} GROUP BY k""", args,
    ).fetchall()
    return {
        "kept_on_dist": [{"kept_on": r["k"], "count": r["n"]} for r in dist],
        "by_mulligan": [
            {"key": r["k"], **wr(r["w"] or 0, r["n"])} for r in agg
        ],
    }


def ts_to_local_str(ms: int | None) -> str | None:
    if not ms:
        return None
    return datetime.fromtimestamp(ms / 1000).strftime("%m-%d %H:%M")


# ================= §3.5 「你被针对了吗」被针对指数 =================

DISCLAIMER = ("MTGA 无公开的匹配操纵证据；本功能是统计自检+娱乐，"
              "小样本极易误报，样本量永远显示在结论旁边。")


def _ti_cfg(cfg) -> dict:
    d = {"weights": {"play_draw": 0.25, "matchup": 0.35, "mulligan": 0.2,
                     "streak": 0.2},
         "min_sample": 20, "p_normal": 0.10, "mulligan_baseline": 0.10}
    if cfg is not None:
        user = cfg.get("targeting_index") or {}
        if isinstance(user.get("weights"), dict):
            d["weights"].update(user["weights"])
        for k in ("min_sample", "p_normal", "mulligan_baseline"):
            if user.get(k) is not None:
                d[k] = user[k]
    return d


def _dim(label: str, n: int, observed, expected, p: float, min_sample: int,
         obs_desc: str, exp_desc: str, plain: str = "") -> dict:
    enough = n >= min_sample
    return {
        "label": label, "n": n, "min_sample": min_sample,
        "observed": observed, "expected": expected,
        "obs_desc": obs_desc, "exp_desc": exp_desc,
        "plain": plain,
        "p": round(p, 6) if p == p else 1.0,
        "score": p_to_score(p) if enough else None,
        "enough": enough,
    }


def _verdict(score: float | None) -> str | None:
    """维度分数 → 一眼能懂的结论词（50=正常基线，越高越邪门）。"""
    if score is None:
        return None
    if score < 60:
        return "正常"
    if score < 70:
        return "有点怪"
    if score < 85:
        return "偏邪门"
    return "高度可疑"


def targeting_index(conn, cfg=None, window_days=30, exclude_abnormal=True,
                    exclude_bot=True, root=None, event=None, deck=None, family=None,
                    mode=None):
    from .insights import targeting
    return targeting(conn, cfg, window_days, exclude_abnormal, exclude_bot,
                     root, event, deck, family, mode)
