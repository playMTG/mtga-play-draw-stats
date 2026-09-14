# -*- coding: utf-8 -*-
"""当天事实评语：小样本也要敢说亮点；主句只留调侃，论据进 evidence。

优先级（**场次不是第一位**，2026-09-14 调整）：
1. 高胜率（大样本要 ≥80% 才值得压过场次）
2. 离谱级连续（legendary）
3. 连续撞同一个主将
4. 明显先后手偏斜
5. 零散重复主将
6. 普通连续段
7. 高场次（肝度）— n≥15 耐力局 / n≥10 打了很久

以前场次排第一，于是**打得越多评语越单调**：一场 22 局的日子若没有离谱级连续，
其余信号都被 `_filter_for_volume` 丢掉，最后只剩一句「今天打了很久」（用户反馈：
「一旦打长了就必然只有一条说今天打了很久」）。现在场次降到末位，只当背景板；
它仍然会是**唯一**一条（如果确实没有别的可说的话），但不会再挤掉真亮点。

大场次（尤其 ≥15）时，普通三连、五五开胜率、中等偏斜仍不当亮点。
话术见 app/daily_copy.py。
"""
from collections import defaultdict

from .daily_copy import pick
from .deck_observations import play_draw_streak_observations

SIDE_ZH = {"play": "先手", "draw": "后手"}
VOLUME_MARATHON = 15
VOLUME_LONG = 10


def _volume_kind(n: int) -> str | None:
    if n >= VOLUME_MARATHON:
        return "marathon"
    if n >= VOLUME_LONG:
        return "long"
    return None


def _score_wr(n: int, wins: int) -> bool:
    if n < 3 or wins <= 0:
        return False
    if n == 3:
        return wins == 3
    return n >= 4 and wins / n >= 0.70


def _score_pd_skew(known: list[dict]) -> str | None:
    n = len(known)
    if n < 3:
        return None
    plays = sum(r["play_draw"] == "play" for r in known)
    draws = n - plays
    if plays / n >= 0.70:
        return "play"
    if draws / n >= 0.70:
        return "draw"
    return None


def _filter_for_volume(candidates: list[dict], n: int, volume: str | None) -> list[dict]:
    """大场次时丢掉「在 27 场里很平常」的弱信号。

    注意这里**只丢真的没信息量的**，不丢「一天里遇到同一个人 3 次」——
    那是绝对计数够醒目，与当天打了多少场无关。以前用占比（n/denominator ≥ 0.45）
    判，22 场里遇到 3 次（13.7%）就被丢掉，于是长时段的日子常常只剩一句场次
    （用户反馈）。现在重复主将按**绝对次数**保留。
    """
    if volume != "marathon":
        return candidates
    kept = []
    for c in candidates:
        kind = c.get("kind")
        if kind == "hot_wr":
            # 27 场里 52% 不算亮点；要真的高胜率才留
            if c.get("level") != "legendary":
                continue
        elif kind == "play_draw_streak":
            # 仅离谱级（legendary）才留；3 连在 27 场里很常见
            if c.get("level") != "legendary":
                continue
        elif kind == "pd_skew":
            # 11 先 / 11 后之类的偏斜在长局里无信息量
            continue
        kept.append(c)
    return kept


def _longest_commander_run(rows: list[dict], gid: str) -> list[dict]:
    """当天记录里连续遭遇同一主将的最长一段。

    以当天的完整对局顺序为准（rows 已按 start_time, match_id 排好）：只有该主将
    的对局算「撞上」，中间夹了别的对局就断。这与「一天里累计遇到 N 次」是两回事
    ——「连续三把」比零散遇到三次更值得说重一点（用户反馈）。
    """
    best: list[dict] = []
    current: list[dict] = []
    for r in rows:
        if gid in (r.get("commanders") or []):
            current.append(r)
            if len(current) > len(best):
                best = list(current)
        else:
            current = []
    return best


def highlights(rows):
    if not rows:
        return []
    rows = sorted(rows, key=lambda r: (r["start_time"], r["match_id"]))
    n = len(rows)
    wins = sum(r["my_result"] == "win" for r in rows)
    candidates = []

    def add(kind, text, evidence, denominator, **extra):
        candidates.append({
            "kind": kind,
            "text": text + ("。" if not text.endswith("。") else ""),
            "n": len(evidence),
            "denominator": denominator,
            "match_ids": [r["match_id"] for r in evidence],
            **extra,
        })

    known = [r for r in rows if r["play_draw"] in ("play", "draw")]

    if n == 1:
        r0 = rows[0]
        if r0["my_result"] == "win":
            key = "single_win"
        elif r0["my_result"] == "loss":
            key = "single_loss"
        else:
            key = "single_unknown"
        pd = SIDE_ZH.get(r0["play_draw"], "先后手未记录")
        text = pick(key, [r0["match_id"], key], side=pd)
        if r0["play_draw"] in ("play", "draw") and text and pd not in text:
            text = f"{text}（{pd}）"
        text = text or pd
        add("single", text, rows, n)
        return candidates

    volume = _volume_kind(n)
    if volume:
        dur = sum((r.get("duration_sec") or 0) for r in rows)
        hours = int(round(dur / 3600)) if dur else 0
        if volume == "marathon" and hours >= 3:
            key = "volume_marathon_hours"
            text = pick(key, ["volume", str(n), str(hours)], n=n, hours=hours)
        else:
            key = "volume_marathon" if volume == "marathon" else "volume_long"
            text = pick(key, ["volume", str(n)], n=n)
        add("volume", text, rows, n, level="legendary" if volume == "marathon" else "rare",
            volume=volume, hours=hours if dur else None)

    decided = [r for r in rows if r["my_result"] in ("win", "loss")]
    if _score_wr(len(decided), wins):
        wr_pct = wins / len(decided)
        perfect = wr_pct >= 0.95 or (len(decided) >= 4 and wins == len(decided))
        # 大场次要真正高胜率才叫「亮眼」
        strong = wr_pct >= 0.80 and len(decided) >= 10
        key = "hot_wr_perfect" if perfect else "hot_wr"
        add(
            "hot_wr",
            pick(key, [r["match_id"] for r in decided] + [key]),
            decided,
            n,
            level="legendary" if (perfect or strong) else "rare",
        )

    skew = _score_pd_skew(known)
    side_n = sum(r["play_draw"] == skew for r in known) if skew else None

    streak_items = play_draw_streak_observations(rows)
    streak_by_side = {}
    for item in streak_items:
        side = "play" if item["key"] == "streak-play" else "draw"
        evidence_ids = set(item["match_ids"])
        evidence = [row for row in rows if row["match_id"] in evidence_ids]
        level = item["level"]
        if level == "legendary":
            key = f"streak_legendary_{side}"
        elif level == "rare":
            key = f"streak_rare_{side}"
        else:
            key = f"streak_other_{side}"
        rec = {
            "kind": "play_draw_streak",
            "text": pick(key, [r["match_id"] for r in evidence] + [key], n=item["n"]) + "。",
            "n": len(evidence),
            "denominator": n,
            "match_ids": [r["match_id"] for r in evidence],
            "level": level,
            "probability": item["probability"],
            "side": side,
        }
        candidates.append(rec)
        streak_by_side[side] = rec

    if skew and side_n is not None:
        streak_rec = streak_by_side.get(skew)
        if not (streak_rec and streak_rec["n"] >= side_n):
            key = f"pd_skew_{skew}"
            add(
                "pd_skew",
                pick(key, [r["match_id"] for r in known if r["play_draw"] == skew] + [key]),
                [r for r in known if r["play_draw"] == skew],
                n,
                side=skew,
            )

    eligible = [r for r in rows if "Brawl" in (r["event_id"] or "")]
    identified = [r for r in eligible if r["commanders"]]
    opponents, names = defaultdict(list), {}
    for r in identified:
        for gid, name in zip(r["commanders"], r["commander_names"]):
            if not opponents[gid] or opponents[gid][-1]["match_id"] != r["match_id"]:
                opponents[gid].append(r)
            names[gid] = name
    if opponents:
        gid = min(opponents, key=lambda g: (-len(opponents[g]), str(g)))
        group = opponents[gid]
        if len(group) >= 3:
            name = names[gid]
            run = _longest_commander_run(rows, gid)
            if len(run) >= 3:
                # 连续三把都撞上同一个人：换更重的说法，证据也只挂这一段连着的。
                add(
                    "repeat_commander",
                    pick("repeat_commander_streak",
                         [r["match_id"] for r in run] + [gid], n=len(run), name=name),
                    run,
                    len(identified) or n,
                    level="legendary",
                    streak=len(run),
                )
            else:
                add(
                    "repeat_commander",
                    pick("repeat_commander", [r["match_id"] for r in group] + [gid], name=name),
                    group,
                    len(identified) or n,
                )

    def _rank(c):
        k = c["kind"]
        # 场次排最后：它是背景板，不该挤掉当天真正发生了什么
        if k == "hot_wr":
            return 0
        if k == "play_draw_streak":
            return 1 if c.get("level") == "legendary" else 5
        if k == "repeat_commander":
            return 2 if c.get("level") == "legendary" else 4
        if k == "pd_skew":
            return 3
        if k == "volume":
            return 6
        return 7

    # 只保留真正的亮点；不再补一句「这一天已记录 N 场，X 胜 Y 负」——
    # 那个数字在下方统计卡里已逐项列出，放进评语纯属复读（用户反馈）。
    # 没有亮点时返回空列表，由 insights.daily_report 决定 plain 的呈现。
    top = [c for c in candidates if c["kind"] != "results"]
    top = _filter_for_volume(top, n, volume)
    top.sort(key=lambda c: (_rank(c), -c["n"]))
    return top[:2]
