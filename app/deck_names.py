# -*- coding: utf-8 -*-
"""限制赛临时牌组的可区分显示名。

MTGA 给轮抓／现开牌组的是通用占位名（"轮抽套牌" / "Draft Deck" / "现开赛"），
于是 250 次 draft 共用同一个名字：明细里点哪个都一样、筛选下拉把 188 次 draft
挤成一个条目、详情页还会提示「另有 1156 场同名记录无法与此身份连接」。

判据**不硬编码这些字符串**——客户端本地化会变（英文客户端就叫 Draft Deck），
而且硬编码会把用户自己起的名字也误伤。改用两条与语言无关的事实：

1. 该 deck 的对局里 ≥60% 属于限制赛（`event_id` 含 Draft / Sealed）；
2. 它的 `my_deck_tag` 在库中被**多个** `my_deck_id` 共用——名字已不足以标识身份。

两条同时满足才派生显示名「赛制 · 首次对局时间」。实测（本机 10957 场）：
命中 301 个 deck_id / 1996 场；被排除的 125 个 / 1435 场里**没有任何限制赛对局**，
其中包含用户自起的重名套牌（"红黑牺牲" 2 个 id、"脂牙" 2 个 id、"大綠" 2 个 id），
它们保持原名不动。
"""
from __future__ import annotations

from datetime import datetime

# 与 deck_detail._deck_kind 保持一致：占比达到这个阈值才算「这个身份是限制赛」。
LIMITED_SHARE = 0.6


def _is_limited(event_id: str | None) -> bool:
    event = event_id or ""
    return "Draft" in event or "Sealed" in event


def _is_draft(event_id: str | None) -> bool:
    return "Draft" in (event_id or "")


def ambiguous_tags(conn) -> set[str]:
    """被多个 deck_id 共用的 my_deck_tag —— 这些名字不再能标识身份。"""
    return {row[0] for row in conn.execute(
        "SELECT my_deck_tag FROM matches "
        "WHERE COALESCE(my_deck_tag, '') != '' AND COALESCE(my_deck_id, '') != '' "
        "GROUP BY my_deck_tag HAVING COUNT(DISTINCT my_deck_id) > 1")}


def _format_time(ts) -> str:
    if ts is None:
        return "时间未记录"
    return datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d %H:%M")


def limited_labels(conn) -> dict[str, str]:
    """deck_id -> 派生显示名；只包含「限制赛且名字不唯一」的身份。"""
    ambiguous = ambiguous_tags(conn)
    if not ambiguous:
        return {}
    labels: dict[str, str] = {}
    for row in conn.execute(
        """SELECT my_deck_id id, my_deck_tag tag,
                  COUNT(*) n,
                  SUM(CASE WHEN event_id LIKE '%Draft%' OR event_id LIKE '%Sealed%'
                           THEN 1 ELSE 0 END) limited,
                  SUM(CASE WHEN event_id LIKE '%Draft%' THEN 1 ELSE 0 END) draft,
                  MIN(start_time) first_ts
             FROM matches
            WHERE COALESCE(my_deck_id, '') != ''
            GROUP BY my_deck_id"""
    ):
        if row["tag"] not in ambiguous:
            continue
        n = row["n"] or 0
        limited = row["limited"] or 0
        if not n or limited / n < LIMITED_SHARE:
            continue
        # 轮抓与现开各自计数，取多的那个作为赛制名。
        kind = "轮抓" if (row["draft"] or 0) * 2 >= limited else "现开"
        labels[row["id"]] = f"{kind} · {_format_time(row['first_ts'])}"
    return labels


def derived_label(deck_ids, labels: dict[str, str]) -> str | None:
    """身份里任一 deck_id 命中的派生名（按 id 排序，保证稳定）。"""
    for value in sorted(v for v in deck_ids if v):
        if value in labels:
            return labels[value]
    return None


def label_for(tag: str | None, deck_id: str | None,
              labels: dict[str, str]) -> str | None:
    """明细与详情共用的显示名：派生名优先，否则回落原始套牌名。"""
    if deck_id and deck_id in labels:
        return labels[deck_id]
    return tag or None
