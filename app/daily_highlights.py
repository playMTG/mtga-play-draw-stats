# -*- coding: utf-8 -*-
"""当天事实评语：小样本也要敢说亮点；主句只留调侃，论据进 evidence。

优先级：
1. 高场次（肝度）— n≥15 耐力局 / n≥10 打了很久
2. 高胜率（大样本要 ≥80% 才值得压过场次）
3. 罕见连续 / 明显先后手偏斜
4. 重复主将（≥3；大场次要更极端）
5. 战绩兜底

大场次（尤其 ≥15）时，普通三连、五五开胜率、中等偏斜都不当亮点。
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
    """大场次时丢掉「在 27 场里很平常」的弱信号。"""
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
            # 仅离谱级（legendary）才压得过耐力局；3 连在 27 场里很常见
            if c.get("level") != "legendary":
                continue
        elif kind == "pd_skew":
            # 11 先 / 11 后之类的偏斜在长局里无信息量
            continue
        elif kind == "repeat_commander":
            denom = max(c.get("denominator") or n, 1)
            if c.get("n", 0) < 8 and c.get("n", 0) / denom < 0.45:
                continue
        kept.append(c)
    return kept


def highlights(rows):
    if not rows:
        return []
    rows = sorted(rows, key=lambda r: (r["start_time"], r["match_id"]))
    n = len(rows)
    wins = sum(r["my_result"] == "win" for r in rows)
    losses = sum(r["my_result"] == "loss" for r in rows)
    unknown = n - wins - losses
    result = pick(
        "results",
        ["results", str(n), str(wins), str(losses)],
        n=n, wins=wins, losses=losses,
    ) + (f"，{unknown} 场结果待确认" if unknown else "")
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
        text = text or (result + f"，{pd}")
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
            add(
                "repeat_commander",
                pick("repeat_commander", [r["match_id"] for r in group] + [gid], name=name),
                group,
                len(identified) or n,
            )

    add("results", result, rows, n)

    def _rank(c):
        k = c["kind"]
        if k == "volume":
            return 0
        if k == "hot_wr":
            return 1
        if k == "play_draw_streak":
            return 2 if c.get("level") == "legendary" else 4
        if k == "pd_skew":
            return 3
        if k == "repeat_commander":
            return 5
        return 6

    non_results = [c for c in candidates if c["kind"] != "results"]
    non_results = _filter_for_volume(non_results, n, volume)
    non_results.sort(key=lambda c: (_rank(c), -c["n"]))
    results = next(c for c in candidates if c["kind"] == "results")
    top = non_results[:2]
    if not top:
        return [results]
    if len(top) == 1:
        top = top + [results]
    return top
