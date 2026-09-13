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


def _deck_rows(conn):
    """每个 deck_id 的：名字、总场数、限制赛场数、轮抓场数、首次对局时间。

    二级下拉（`identity_labels`）与明细显示名（`limited_labels`）共用这一份统计，
    保证「下拉里看到的名字」与「明细里看到的名字」永远一致。
    """
    return conn.execute(
        """SELECT my_deck_id id, my_deck_tag tag,
                  COUNT(*) n,
                  SUM(CASE WHEN event_id LIKE '%Draft%' OR event_id LIKE '%Sealed%'
                           THEN 1 ELSE 0 END) limited,
                  SUM(CASE WHEN event_id LIKE '%Draft%' THEN 1 ELSE 0 END) draft,
                  MIN(start_time) first_ts
             FROM matches
            WHERE COALESCE(my_deck_id, '') != ''
            GROUP BY my_deck_id"""
    ).fetchall()


def _limited_kind(row) -> str | None:
    """这个身份是不是限制赛；是的话返回「轮抓」或「现开」，否则 None。"""
    n = row["n"] or 0
    limited = row["limited"] or 0
    if not n or limited / n < LIMITED_SHARE:
        return None
    # 轮抓与现开各自计数，取多的那个作为赛制名。
    return "轮抓" if (row["draft"] or 0) * 2 >= limited else "现开"


def limited_labels(conn) -> dict[str, str]:
    """deck_id -> 派生显示名；只包含「限制赛且名字不唯一」的身份。"""
    ambiguous = ambiguous_tags(conn)
    if not ambiguous:
        return {}
    labels: dict[str, str] = {}
    for row in _deck_rows(conn):
        if row["tag"] not in ambiguous:
            continue
        kind = _limited_kind(row)
        if kind is None:
            continue
        labels[row["id"]] = f"{kind} · {_format_time(row['first_ts'])}"
    return labels


def identity_labels(conn) -> dict[str, str]:
    """deck_id -> 二级下拉里用于区分身份的名字。

    与 `limited_labels` 的区别：这里**覆盖所有重名身份**，因为下拉必须能区分
    「我指的是哪一副」，而明细只在限制赛那一类上改名（用户自起的重名保持原样）。

    - 限制赛沿用「轮抓／现开 · 首次对局时间」——与明细、详情标题一致；
    - 其余重名用「首次对局时间 起」。

    刻意**不带场数**：这里是全库口径，而两级下拉是求交（名字 + 身份），
    场数得按当前筛选算，由 `stats.deck_identities` 单独给出，否则同一个身份
    会出现「下拉里写 192 场、选完只有 47 场」的矛盾（改过名的套牌就会这样）。
    """
    ambiguous = ambiguous_tags(conn)
    if not ambiguous:
        return {}
    labels: dict[str, str] = {}
    for row in _deck_rows(conn):
        if row["tag"] not in ambiguous:
            continue
        kind = _limited_kind(row)
        if kind is not None:
            labels[row["id"]] = f"{kind} · {_format_time(row['first_ts'])}"
        else:
            labels[row["id"]] = f"{_format_time(row['first_ts'])} 起"
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
