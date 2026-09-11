# -*- coding: utf-8 -*-
"""R8 套牌小样本观察：从已记录事实中挑选可回查的亮点。"""
from __future__ import annotations

from collections import Counter
from math import prod


SIDE_LABELS = {"play": "先手", "draw": "后手"}


def _no_run_probability(length: int, streak: int) -> float:
    """公平独立二项序列中，指定一侧没有连续 ``streak`` 次的概率。"""
    if length < streak:
        return 1.0
    states = [0.0] * streak
    states[0] = 1.0
    for _ in range(length):
        next_states = [0.0] * streak
        next_states[0] = 0.5 * sum(states)
        for run in range(1, streak):
            next_states[run] = 0.5 * states[run - 1]
        states = next_states
    return sum(states)


def run_scan_probability(block_lengths: list[int], streak: int) -> float:
    """各可确认记录段中，至少一次出现指定侧连续 ``streak`` 次的概率。"""
    if streak < 1 or not block_lengths or max(block_lengths) < streak:
        return 0.0
    return 1.0 - prod(_no_run_probability(length, streak)
                      for length in block_lengths)


def _percent(probability: float) -> float:
    value = probability * 100
    if value < 0.1:
        return round(value, 3)
    if value < 1:
        return round(value, 2)
    return round(value, 1)


def _severity(probability: float) -> tuple[str, str]:
    if probability < 0.01:
        return "legendary", "离谱级连庄"
    if probability < 0.05:
        return "rare", "非常少见"
    if probability < 0.15:
        return "unusual", "明显连庄"
    return "notable", "值得记录"


def _ordered_streaks(rows: list[dict]) -> tuple[dict[str, dict | None], list[int], str | None]:
    """返回每一侧最长的可确认连续段，以及概率模型使用的记录段长度。"""
    if any(row["start_time"] is None for row in rows):
        return {"play": None, "draw": None}, [], "有日期未知的记录，无法确认完整顺序"

    ordered = sorted(rows, key=lambda row: (row["start_time"], row["match_id"]))
    time_counts = Counter(row["start_time"] for row in ordered)
    best: dict[str, dict | None] = {"play": None, "draw": None}
    block_lengths: list[int] = []
    block_length = 0
    current_side = None
    current_rows: list[dict] = []

    def close_block() -> None:
        nonlocal block_length
        if block_length:
            block_lengths.append(block_length)
            block_length = 0

    def close_streak() -> None:
        nonlocal current_side, current_rows
        if current_side and current_rows:
            candidate = {
                "side": current_side,
                "length": len(current_rows),
                "match_ids": [row["match_id"] for row in current_rows],
                "first_time": current_rows[0]["start_time"],
                "last_time": current_rows[-1]["start_time"],
            }
            previous = best[current_side]
            if (previous is None
                    or candidate["length"] > previous["length"]
                    or (candidate["length"] == previous["length"]
                        and candidate["last_time"] > previous["last_time"])):
                best[current_side] = candidate
        current_side = None
        current_rows = []

    for row in ordered:
        side = row["play_draw"]
        if time_counts[row["start_time"]] > 1 or side not in SIDE_LABELS:
            close_streak()
            close_block()
            continue
        block_length += 1
        if side != current_side:
            close_streak()
            current_side = side
        current_rows.append(row)
    close_streak()
    close_block()

    reason = None
    if any(n > 1 for n in time_counts.values()):
        reason = "同一时间的记录会打断可确认的连续段"
    elif any(row["play_draw"] not in SIDE_LABELS for row in ordered):
        reason = "未知先后手会打断可确认的连续段"
    return best, block_lengths, reason


def _streak_observation(side: str, run: dict, block_lengths: list[int],
                        reason: str | None) -> dict:
    length = run["length"]
    probability = run_scan_probability(block_lengths, length)
    level, verdict = _severity(probability)
    side_label = SIDE_LABELS[side]
    known = sum(block_lengths)
    blocks = len(block_lengths)
    scan_percent = _percent(probability)
    fixed_percent = _percent(0.5 ** length)
    block_text = f"范围内 {known} 场可确认顺序的记录"
    if blocks > 1:
        block_text += f"（分为 {blocks} 段）"
    explanation = (
        f"参考模型假设每场先后手相互独立且各为 50%。在当前{block_text}中，"
        f"至少出现一次连续 {length} 把{side_label}的概率约为 {scan_percent}%；"
        f"事先指定连续 {length} 场全为{side_label}的概率是 {fixed_percent}%。"
        "这里采用前一个“扫描整个范围”的口径。这个数值不是被针对概率，也不判断匹配机制。"
    )
    if reason:
        explanation += f" {reason}，概率只计算上述可确认记录段。"
    return {
        "key": f"streak-{side}",
        "kind": "play_draw_streak",
        "level": level,
        "headline": f"连续 {length} 把{side_label}：{verdict}",
        "text": f"当前范围内最长连续{side_label}为 {length} 场，参考概率约 {scan_percent}%。",
        "n": length,
        "match_ids": run["match_ids"],
        "probability": {
            "scan": probability,
            "scan_percent": scan_percent,
            "fixed_percent": fixed_percent,
            "known_matches": known,
            "blocks": blocks,
            "explanation": explanation,
        },
    }


def play_draw_streak_observations(rows: list[dict]) -> list[dict]:
    """返回从连续三场开始的先后手观察，按扫描概率由低到高排列。"""
    best, block_lengths, reason = _ordered_streaks(rows)
    items = [
        _streak_observation(side, run, block_lengths, reason)
        for side, run in best.items()
        if run and run["length"] >= 3
    ]
    items.sort(key=lambda item: (item["probability"]["scan"], -item["n"], item["key"]))
    return items


def _commander_observation(rows: list[dict], commanders: dict,
                           commanders_by_match: dict[str, set[str]]) -> dict | None:
    if not commanders["rows"]:
        return None
    top = commanders["rows"][0]
    if top["n"] < 2:
        return None
    gid = top["key"]
    matches = [row for row in rows if gid in commanders_by_match.get(row["match_id"], set())]
    decided = top["wins"] + top["losses"]
    if decided >= 3 and top["wins"] == decided:
        headline = f"对阵 {top['name']}，{decided} 战全胜"
        level = "strong"
    elif decided >= 3 and top["losses"] == decided:
        headline = f"对阵 {top['name']}，{decided} 战全负"
        level = "strong"
    else:
        headline = f"{top['n']} 次遇到 {top['name']}"
        level = "notable"
    result = f"交手 {top['wins']} 胜 {top['losses']} 负"
    if top["unknown_result"]:
        result += f"，{top['unknown_result']} 场结果待确认"
    text = (f"在主将已知的 {commanders['known']} 场争锋对局中占 {top['share_known']}%，"
            f"{result}；先手 {top['play']} 场、后手 {top['draw']} 场")
    if top["unknown_play_draw"]:
        text += f"、未知 {top['unknown_play_draw']} 场"
    return {
        "key": f"commander-{gid}",
        "kind": "commander_matchup",
        "level": level,
        "headline": headline,
        "text": text + "。",
        "n": len(matches),
        "match_ids": [row["match_id"] for row in matches],
        "commander_key": gid,
        "probability": None,
    }


def _fallback(rows: list[dict]) -> dict:
    wins = sum(row["my_result"] == "win" for row in rows)
    losses = sum(row["my_result"] == "loss" for row in rows)
    play = sum(row["play_draw"] == "play" for row in rows)
    draw = sum(row["play_draw"] == "draw" for row in rows)
    unknown_result = len(rows) - wins - losses
    unknown_side = len(rows) - play - draw
    text = f"先手 {play} 场、后手 {draw} 场"
    if unknown_side:
        text += f"、未知 {unknown_side} 场"
    text += f"；{wins} 胜 {losses} 负"
    if unknown_result:
        text += f"，{unknown_result} 场结果待确认"
    return {
        "key": "range-summary",
        "kind": "range_summary",
        "level": "neutral",
        "headline": f"当前范围记录了 {len(rows)} 场",
        "text": text + "。",
        "n": len(rows),
        "match_ids": [row["match_id"] for row in rows],
        "probability": None,
    }


def deck_observations(rows: list[dict], commanders: dict,
                      commanders_by_match: dict[str, set[str]]) -> dict:
    """生成最多三条观察；连续先后手按扫描概率由低到高排列。"""
    if not rows:
        return {
            "items": [],
            "note": "当前范围没有对局，暂时没有可评价的事实。",
        }

    items = play_draw_streak_observations(rows)
    commander = _commander_observation(rows, commanders, commanders_by_match)
    if commander:
        items.append(commander)
    if not items:
        items.append(_fallback(rows))
    return {
        "items": items[:3],
        "note": ("亮点只使用当前套牌、时间范围和构筑版本内的记录；从连续 3 场开始评价。"
                 "主将遭遇没有均匀理论基线，因此只报告实际占比和战绩。"),
    }
