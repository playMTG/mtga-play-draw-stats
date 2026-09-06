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
             family: str | None = None) -> tuple[list[str], list]:
    conds, args = [], []
    c, a = _event_scope(event, family, conn)
    if c:
        conds.append(c)
        args.extend(a)
    if deck:
        conds.append("COALESCE(my_deck_tag, '') = ?")
        args.append(deck)
    return conds, args


def overview(conn: sqlite3.Connection, exclude_abnormal: bool = True,
             event: str | None = None, deck: str | None = None,
             exclude_bot: bool = True, family: str | None = None) -> dict:
    """总览：整体与先后手拆分 + 按赛事/套牌分组 + 趋势（按日）。"""
    conds, args = _filters(conn, event, deck, family)
    if exclude_abnormal:
        conds.append("is_abnormal = 0")
    if exclude_bot:
        conds.append("is_bot = 0")
    where = " AND ".join([_BASE_WHERE] + conds)

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

    return {
        "total": wr(total["w"] or 0, total["n"]),
        "on_play": wr(play["w"], play["n"]) if play else wr(0, 0),
        "on_draw": wr(draw["w"], draw["n"]) if draw else wr(0, 0),
        "by_event": [{"key": r["k"], **wr(r["w"] or 0, r["n"])} for r in by_event],
        "by_deck": [{"key": r["k"], **wr(r["w"] or 0, r["n"])} for r in by_deck],
        "trend_daily": [{"key": r["d"], **wr(r["w"] or 0, r["n"])} for r in trend],
        "trend_weekly": [{"key": r["wk"], **wr(r["w"] or 0, r["n"])} for r in trend_w],
    }


ARCH_KEYS = ["Aggro", "Control", "Combo", "Ramp", "Midrange", "Other"]
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
             family: str | None = None) -> list[dict]:
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
    return [
        {
            "key": r["k"],
            "name": r["name"],
            "archetype": arch.get(r["name"]),
            **wr(r["w"] or 0, r["n"]),
            "on_play": wr(r["pw"] or 0, r["pn"]),
            "on_draw": wr(r["dw"] or 0, r["dn"]),
        }
        for r in rows
    ]


def commander_coverage(conn: sqlite3.Connection, exclude_abnormal: bool = True,
                       event: str | None = None, deck: str | None = None,
                       exclude_bot: bool = True,
                       family: str | None = None) -> dict:
    """主将档案的样本覆盖率（口径与 matchups 相同的过滤条件）。

    背景：主将 grpId 只存在于本地日志的 GRE 事件里，Untapped 云史
    不含对手套牌信息——历史对局大量缺失主将记录，档案场次远小于
    总场次，必须在 UI 上明示，否则"对战 X 才 5 次"会被误读为解析丢数据。
    """
    conds, args = _filters(conn, event, deck, family)
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
    return {"total": row["total"] or 0, "with_cmdr": row["with_cmdr"] or 0}


def match_list(conn: sqlite3.Connection, exclude_abnormal: bool = True,
               event: str | None = None, deck: str | None = None,
               limit: int = 500, offset: int = 0, lang: str = "zh",
               exclude_bot: bool = True, family: str | None = None) -> dict:
    """对局明细（倒序），含调度次数与对手主将。"""
    conds, args = _filters(conn, event, deck, family)
    if exclude_abnormal:
        conds.append("is_abnormal = 0")
    if exclude_bot:
        conds.append("is_bot = 0")
    where = " AND ".join(["1=1"] + conds)

    # 卡名库可能未挂载：动态决定对手主将列的显示形式
    try:
        conn.execute("SELECT 1 FROM cards_db.cards LIMIT 1")
        name_base = ("COALESCE(cards.name_zh, cards.name)"
                     if lang == "zh" else "cards.name")
        cmdr_expr = f"GROUP_CONCAT(COALESCE({name_base}, 'grpId:' || c.grp_id))"
        join_sql = ("LEFT JOIN cards_db.cards cards ON cards.grp_id = c.grp_id")
    except sqlite3.OperationalError:
        cmdr_expr = "GROUP_CONCAT('grpId:' || c.grp_id)"
        join_sql = ""

    rows = conn.execute(
        f"""SELECT m.match_id, m.event_id, m.start_time, m.duration_sec,
                   m.opponent_name, m.play_draw, m.my_result, m.end_reason,
                   m.total_turns, m.is_abnormal, m.abnormal_reason, m.is_bot,
                   m.my_deck_tag, m.source,
                   (SELECT COALESCE(SUM(mu.kept_on),0) FROM mulligans mu
                     WHERE mu.match_id=m.match_id
                       AND (mu.seat IS NULL OR mu.seat=m.my_seat)) my_mulls,
                   (SELECT {cmdr_expr} FROM commanders c {join_sql}
                     WHERE c.match_id=m.match_id AND c.seat!=m.my_seat) opp_cmdrs
            FROM matches m WHERE {where}
            ORDER BY m.start_time DESC LIMIT ? OFFSET ?""",
        [*args, limit, offset],
    ).fetchall()
    total = conn.execute(
        f"SELECT COUNT(*) c FROM matches m WHERE {where}", args
    ).fetchone()["c"]
    return {
        "total": total,
        "rows": [
            {
                "match_id": r["match_id"],
                "event_id": r["event_id"],
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
                "source": r["source"],
                "my_mulls": r["my_mulls"],
                "opp_cmdrs": (r["opp_cmdrs"] or "").split(",") if r["opp_cmdrs"] else [],
            }
            for r in rows
        ],
    }


_SET_ZH = {
    "DMU": "多明纳里亚联合", "MOM": "机械降临", "MID": "午夜猎影",
    "VOW": "猩红婚誓", "NEO": "神河霓朝", "ELD": "艾卓王权",
    "DSK": "诡墟", "SNC": "新卡佩纳", "MH3": "摩登新篇3", "MH2": "摩登新篇2",
    "BLB": "边陲亡命", "OTJ": "旷野哨站", "FDN": "基础系列2025",
    "TDM": "鞑契风暴",
}

_EVENT_ZH = {
    "Ladder": "排位天梯",
    "Traditional_Ladder": "传统排位天梯（双备牌）",
    "Play": "自由对战（非排位）",
    "Play_Brawl_Historic": "史迹争锋（非排位）",
    "Explorer_Ladder": "探险排位天梯",
    "Traditional_Explorer_Ladder": "传统探险排位天梯",
    "Explorer_Play": "探险自由对战",
    "Explorer_Event_v2": "探险构组赛",
    "Historic_Ladder": "史迹排位天梯",
    "Timeless_Ladder": "无境排位天梯",
    "Traditional_Timeless_Ladder": "传统无境排位天梯",
    "Timeless_Play": "无境自由对战",
    "Constructed_Event_2022": "构组赛·2022",
    "Constructed_Event_2022_v2": "构组赛·2022 v2",
    "Traditional_Cons_Event_2022": "传统构组赛·2022",
}

_MWM_ZH = {
    "OmniscienceDraft": "全知轮抽", "Momir": "莫米", "BrawlBuilder": "争锋构筑",
}

_DRAFT_PREFIX = {
    "PremierDraft_": "高端轮抽", "QuickDraft_": "快速轮抽",
    "PickTwoDraft_": "二选一轮抽", "Sealed_": "现开赛",
}


def friendly_event(event_id: str) -> str:
    """把 MTGA 原始 event_id 转成可读的中文赛制名（未识别原样返回）。"""
    if event_id in _EVENT_ZH:
        return _EVENT_ZH[event_id]
    for prefix, label in _DRAFT_PREFIX.items():
        if event_id.startswith(prefix):
            code = event_id[len(prefix):].split("_")[0]
            return f"{label}·{_SET_ZH.get(code, code)}"
    if event_id.startswith("MWM_"):
        tail = event_id[4:]
        for k, v in _MWM_ZH.items():
            if tail.startswith(k):
                return f"每周魔法·{v}"
        return f"每周魔法·{tail}"
    if event_id.startswith("Brawl_Challenge"):
        return f"争锋挑战赛·{event_id.rsplit('_', 1)[-1]}"
    if event_id.startswith("Festival_"):
        return f"节日活动·{event_id.split('_')[1]}"
    if event_id.startswith("Jump_In"):
        return "跳入魔法"
    if event_id == "AIBotMatch":
        return "AI 机器人对局"
    if event_id.startswith("DirectGameTournament"):
        return "Direct Game 巡回赛"
    if event_id.startswith("CompCons"):
        return "竞技构组挑战赛"
    if event_id == "Constructed_BestOf3":
        return "传统构组赛（BO3）"
    if event_id.startswith("Yargle_Day"):
        return "亚格勒日"
    return event_id


def filter_options(conn: sqlite3.Connection, exclude_abnormal: bool = True,
                   exclude_bot: bool = True, event: str | None = None,
                   family: str | None = None) -> dict:
    """筛选器候选项（三级级联：赛制大类 → 赛事 → 套牌）。

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
    events = [r for r in all_events
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
    decks = conn.execute(
        f"SELECT my_deck_tag v, COUNT(*) n FROM matches "
        f"WHERE my_deck_tag IS NOT NULL AND my_deck_tag != ''{w}{dk_cond} "
        f"GROUP BY my_deck_tag ORDER BY n DESC, v",
        dk_args,
    ).fetchall()

    return {
        "families": families,
        "events": [
            {"value": r["v"], "label": friendly_event(r["v"]), "n": r["n"]}
            for r in events
        ],
        "decks": [{"value": r["v"], "label": r["v"], "n": r["n"]} for r in decks],
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


def export_rows(conn: sqlite3.Connection, kind: str = "matches",
                exclude_abnormal: bool = True,
                event: str | None = None, deck: str | None = None,
                exclude_bot: bool = False,
                family: str | None = None) -> tuple[list[str], list[list]]:
    """CSV 导出数据（kind: matches | ranks）。返回 (表头, 行)。

    exclude_abnormal / exclude_bot 仅作行过滤；导出列原样保留标记字段。
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
                r["constructed_class"] or "",
                r["constructed_level"] if r["constructed_level"] is not None else "",
                r["limited_class"] or "",
                r["limited_level"] if r["limited_level"] is not None else "",
            ])
        return headers, out

    # matches
    conds, args = _filters(conn, event, deck, family)
    if exclude_abnormal:
        conds.append("is_abnormal = 0")
    if exclude_bot:
        conds.append("is_bot = 0")
    where = " AND ".join(["1=1"] + conds)
    # 对手主将列：卡名库挂载时显示卡名（zh 优先），否则 grpId
    try:
        conn.execute("SELECT 1 FROM cards_db.cards LIMIT 1")
        name_base = "COALESCE(cards.name_zh, cards.name)"
        cmdr_sub = ("(SELECT GROUP_CONCAT(COALESCE(" + name_base +
                    ", 'grpId:' || c.grp_id)) FROM commanders c "
                    "LEFT JOIN cards_db.cards cards ON cards.grp_id = c.grp_id "
                    "WHERE c.match_id=m.match_id AND c.seat!=m.my_seat)")
    except sqlite3.OperationalError:
        cmdr_sub = ("(SELECT GROUP_CONCAT('grpId:' || c.grp_id) FROM commanders c "
                    "WHERE c.match_id=m.match_id AND c.seat!=m.my_seat)")
    rows = conn.execute(
        f"""SELECT m.*, (SELECT COALESCE(SUM(mu.kept_on),0) FROM mulligans mu
                 WHERE mu.match_id=m.match_id
                   AND (mu.seat IS NULL OR mu.seat=m.my_seat)) my_mulls,
                {cmdr_sub} opp_cmdrs
             FROM matches m WHERE {where} ORDER BY m.start_time""",
        args,
    ).fetchall()
    headers = ["match_id", "来源", "赛事", "时间", "时长(秒)", "对手名",
               "先后手", "结果", "结束原因", "总回合", "异常", "异常原因",
               "我方套牌", "对手类型", "我方调度", "对手主将", "Bot局"]
    out = []
    for r in rows:
        out.append([
            r["match_id"], r["source"], r["event_id"] or "",
            ts_to_local_str(r["start_time"]) or "",
            r["duration_sec"] if r["duration_sec"] is not None else "",
            r["opponent_name"] or "",
            r["play_draw"] or "",
            r["my_result"] or "",
            (r["end_reason"] or "").replace("ResultReason_", ""),
            r["total_turns"] if r["total_turns"] is not None else "",
            "是" if r["is_abnormal"] else "否",
            r["abnormal_reason"] or "",
            r["my_deck_tag"] or "",
            r["opp_archetype_tag"] or "",
            r["my_mulls"],
            r["opp_cmdrs"] or "",
            "是" if r["is_bot"] else "否",
        ])
    return headers, out


def mulligan_stats(conn: sqlite3.Connection, exclude_abnormal: bool = True,
                   exclude_bot: bool = True) -> dict:
    """调度统计：我的每局调度次数分布 + 调度与胜负关联。"""
    conds = []
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
            GROUP BY k ORDER BY k""",
    ).fetchall()
    # 调过度的局 vs 没调的局胜率（kept_on>=1 = 本局有调度）
    agg = conn.execute(
        f"""SELECT CASE WHEN EXISTS(
                 SELECT 1 FROM mulligans mu WHERE mu.match_id=m.match_id
                   AND (mu.seat IS NULL OR mu.seat=m.my_seat)
                   AND mu.kept_on >= 1) THEN 'mulligan' ELSE 'clean' END k,
               SUM(m.my_result='win') w, COUNT(*) n
            FROM matches m WHERE {where} GROUP BY k""",
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


def targeting_index(conn: sqlite3.Connection, cfg=None,
                    window_days: int | None = 30,
                    exclude_abnormal: bool = True,
                    exclude_bot: bool = True,
                    root=None) -> dict:
    """被针对指数（DESIGN §3.5）：四维度独立检验 + 合成 0-100。

    window_days: 7/30 = 近 N 天；None = 全部（维度 B 始终用滚动 30 天
    vs 此前基线，防止长期被针对被历史平均掉）。
    样本 < min_sample 的维度显示灰色态且不计入综合分。
    """
    ti = _ti_cfg(cfg)
    min_n = int(ti["min_sample"])
    p_normal = float(ti["p_normal"])

    now_ms = int(datetime.now().timestamp() * 1000)
    conds = ["my_result IS NOT NULL"]
    if exclude_abnormal:
        conds.append("is_abnormal = 0")
    if exclude_bot:
        conds.append("is_bot = 0")
    win_start = None
    if window_days:
        win_start = now_ms - window_days * 86_400_000
    wargs: list = [win_start] if win_start else []
    base_where = " AND ".join(conds)
    where = (f"{base_where} AND start_time >= ?") if win_start else base_where

    # ---- A. 先后手运：拿先手比例 vs 50%（单侧：先手偏少=被针对）----
    r = conn.execute(
        f"""SELECT SUM(play_draw='play') p, COUNT(*) n FROM matches
            WHERE {where} AND play_draw IS NOT NULL""", wargs).fetchone()
    a_plain = ""
    a_dim = _dim(
        "先后手运", r["n"], r["p"] or 0, (r["n"] or 0) / 2, 1.0, min_n,
        f"先手 {r['p'] or 0}/{r['n'] or 0} 场", "期望先手约一半",
    )
    if a_dim["n"]:
        pct = (r["p"] or 0) * 100.0 / r["n"]
        a_plain = (f"你 {r['n']} 场里有 {r['p'] or 0} 场先手（占 {pct:.1f}%）。"
                   f"MTGA 理论上先后手各占一半。")
        a_dim["p"] = round(binom_cdf(int(r["p"] or 0), r["n"], 0.5), 6)
        if a_dim["enough"]:
            a_dim["score"] = p_to_score(a_dim["p"], p_normal)
            a_plain += ("偏差在正常运气范围内。" if a_dim["score"] < 60
                        else "先手明显偏少，超出了运气波动范围。")
        a_dim["plain"] = a_plain

    # ---- C. 起手运：调度局占比 vs 基线调度率（单侧：调多了=被针对）----
    r = conn.execute(
        f"""SELECT SUM(CASE WHEN EXISTS(SELECT 1 FROM mulligans mu
                     WHERE mu.match_id=m.match_id
                       AND (mu.seat IS NULL OR mu.seat=m.my_seat)
                       AND mu.kept_on >= 1)
                 THEN 1 ELSE 0 END) mu, COUNT(*) n
            FROM matches m WHERE {where}""", wargs).fetchone()
    r0 = float(ti["mulligan_baseline"])
    c_dim = _dim(
        "起手运", r["n"], r["mu"] or 0, r0 * r["n"], 1.0, min_n,
        f"调度局 {r['mu'] or 0}/{r['n'] or 0}",
        f"基线调度率 {r0:.0%}",
    )
    if c_dim["n"]:
        pct_c = (r["mu"] or 0) * 100.0 / c_dim["n"]
        c_dim["plain"] = (f"{c_dim['n']} 场里有 {r['mu'] or 0} 场你调度过"
                          f"（占 {pct_c:.1f}%），一般玩家约 {r0:.0%}。")
        c_dim["p"] = round(binom_sf(int(r["mu"] or 0), c_dim["n"], r0), 6)
        if c_dim["enough"]:
            c_dim["score"] = p_to_score(c_dim["p"], p_normal)
            c_dim["plain"] += ("调度频率正常。" if c_dim["score"] < 60
                               else "调度明显偏多，起手质量异常。")

    # ---- D. 连败运：最大连败长度 vs 该胜率下的合理范围 ----
    rows = conn.execute(
        f"""SELECT my_result, start_time FROM matches WHERE {where}
            ORDER BY start_time""", wargs).fetchall()
    results = [x["my_result"] for x in rows]
    n_d = len(results)
    d_dim = _dim("连败运", n_d, 0, 0, 1.0, min_n, "", "")
    if n_d:
        wrate = results.count("win") / n_d
        streak = max_loss_streak(results)
        d_dim["observed"] = f"{streak} 连败"
        d_dim["p"] = round(streak_sf(streak, n_d, wrate), 6)
        d_dim["obs_desc"] = f"最大连败 {streak}"
        d_dim["exp_desc"] = f"整体胜率 {wrate:.0%}"
        d_dim["plain"] = (f"你最长一次连败 {streak} 场，整体胜率 {wrate:.0%}。")
        if d_dim["enough"]:
            d_dim["score"] = p_to_score(d_dim["p"], p_normal)
            d_dim["plain"] += ("这个连败长度在该胜率下完全正常。"
                               if d_dim["score"] < 60 else
                               f"以 {wrate:.0%} 的胜率连败 {streak} 场极其罕见，运气异常。")

    # ---- B. 对手运：遭遇类型分布 偏离 此前基线（卡方）+ 克星列表 ----
    b_window_days = window_days or 30
    b_start = now_ms - b_window_days * 86_400_000
    arch = archetype_map(conn, root) if root else {}

    try:
        conn.execute("SELECT 1 FROM cards_db.cards LIMIT 1")
        name_sql = "COALESCE(cards.name, 'grpId:' || c.grp_id)"
        join_b = "LEFT JOIN cards_db.cards cards ON cards.grp_id = c.grp_id"
    except sqlite3.OperationalError:
        name_sql = "'grpId:' || c.grp_id"
        join_b = ""

    def arch_mix(lo_ms: int | None, hi_ms: int | None) -> tuple[dict[str, int], int]:
        conds_b = list(conds)
        args_b: list = []
        if lo_ms is not None:
            conds_b.append("start_time >= ?")
            args_b.append(lo_ms)
        if hi_ms is not None:
            conds_b.append("start_time < ?")
            args_b.append(hi_ms)
        w_b = " AND ".join(conds_b)
        counts: dict[str, int] = {}
        total = 0
        for cr in conn.execute(
            f"""SELECT DISTINCT m.match_id, {name_sql} cname FROM matches m
                JOIN commanders c ON c.match_id=m.match_id AND c.seat!=m.my_seat
                {join_b} WHERE {w_b}""",
            args_b,
        ):
            k = arch.get(cr["cname"], "未知")
            counts[k] = counts.get(k, 0) + 1
            total += 1
        return counts, total

    win_counts, win_n = arch_mix(b_start, None)
    base_counts, base_n = arch_mix(None, b_start)
    b_dim = _dim(
        "对手运", win_n, win_counts, base_counts, 1.0, min_n,
        f"近 {b_window_days} 天 {win_n} 场遭遇", f"基线 {base_n} 场分布",
        plain=(f"最近 {b_window_days} 天遇到的 {win_n} 个对手，"
               f"和之前 {base_n} 场的对手类型分布对比。"),
    )
    if win_n and base_n and b_dim["enough"]:
        stat = 0.0
        buckets = 0
        small_obs = small_exp = 0.0
        for k in sorted(set(win_counts) | set(base_counts)):
            exp_k = base_counts.get(k, 0) * win_n / base_n
            obs_k = win_counts.get(k, 0)
            if exp_k < 1.0:  # 低频类合并，防新主将一己之力拉爆卡方
                small_obs += obs_k
                small_exp += exp_k
                continue
            stat += (obs_k - exp_k) ** 2 / exp_k
            buckets += 1
        if small_exp > 0:
            stat += (small_obs - small_exp) ** 2 / small_exp
            buckets += 1
        df = buckets - 1
        if df >= 1:
            b_dim["p"] = round(chi2_sf(stat, df), 6)
            b_dim["score"] = p_to_score(b_dim["p"], p_normal)
            b_dim["observed"] = round(stat, 2)
            b_dim["expected"] = f"卡方 {stat:.1f} (df={df})"
            b_dim["plain"] += ("对手类型构成正常。" if b_dim["score"] < 60
                               else "对手类型构成明显改变，像是被刻意匹配。")

    # 克星列表：窗口内遭遇 ≥3 次且我方胜率 <40% 的对手主将
    nemeses = []
    if win_n:
        conds_b = list(conds) + ["start_time >= ?"]
        args_b: list = [b_start]
        w_b = " AND ".join(conds_b)
        for cr in conn.execute(
            f"""SELECT {name_sql} cname, SUM(m.my_result='win') w, COUNT(*) n
                FROM matches m
                JOIN commanders c ON c.match_id=m.match_id AND c.seat!=m.my_seat
                {join_b} WHERE {w_b} GROUP BY cname HAVING n >= 3""",
            args_b,
        ):
            k = arch.get(cr["cname"], "未知")
            wr_k = (cr["w"] or 0) * 100.0 / cr["n"]
            if wr_k < 40:
                nemeses.append({"archetype": k, "name": cr["cname"],
                                "n": cr["n"], "wr": round(wr_k, 1)})
        nemeses.sort(key=lambda x: x["wr"])

    # ---- 合成：配置权重加权平均（仅计入样本足够的维度）----
    dims = {"play_draw": a_dim, "matchup": b_dim, "mulligan": c_dim, "streak": d_dim}
    weights = ti["weights"]
    num = den = 0.0
    for k, d in dims.items():
        if d["enough"] and d["score"] is not None:
            w_k = float(weights.get(k, 0))
            num += w_k * d["score"]
            den += w_k
    composite = round(num / den, 1) if den > 0 else None
    for d in dims.values():
        d["verdict"] = _verdict(d["score"] if d["enough"] else None)
    return {
        "window_days": window_days,
        "dimensions": dims,
        "composite": composite,
        "label": luck_label(composite) if composite is not None else None,
        "min_sample": min_n,
        "nemeses": nemeses[:5],
        "disclaimer": DISCLAIMER,
    }
