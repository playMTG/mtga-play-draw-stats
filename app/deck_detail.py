# -*- coding: utf-8 -*-
"""R6 套牌详情：可靠身份连接、时间范围与构筑版本拆分。"""
from __future__ import annotations

from collections import deque
from datetime import date, datetime, timedelta
import sqlite3

from .card_names import CardNames
from .deck_observations import deck_observations
from .event_names import friendly_event
from .stats import is_constructed_opponent_event, wr


SCOPES = {
    "today": "今天",
    "yesterday": "昨天",
    "last20": "近 20 场",
    "last7": "近 7 天",
    "all": "全部",
}
UNKNOWN_VERSION = "__unknown__"


def _clean(value) -> str | None:
    value = str(value).strip() if value is not None else ""
    return value or None


def _all_rows(conn: sqlite3.Connection) -> list[dict]:
    return [dict(row) for row in conn.execute(
        """SELECT id, match_id, source, event_id, start_time, my_seat, play_draw,
                  my_result, my_deck_tag, my_deck_id, my_deck_version,
                  match_mode, opp_archetype_tag, is_abnormal, is_bot
             FROM matches
            WHERE COALESCE(my_deck_tag, '') != ''
               OR COALESCE(my_deck_id, '') != ''
               OR COALESCE(my_deck_version, '') != ''"""
    )]


def _seed_rows(rows: list[dict], deck_id: str | None,
               deck_version: str | None, deck: str | None) -> tuple[list[int], bool]:
    """返回身份图的起始记录；bool 表示是否由名称自动选择了最近身份。"""
    if deck_id or deck_version:
        seeds = [
            i for i, row in enumerate(rows)
            if (not deck_id or _clean(row["my_deck_id"]) == deck_id)
            and (not deck_version or _clean(row["my_deck_version"]) == deck_version)
        ]
        if not seeds:
            raise ValueError("找不到对应的套牌身份")
        return seeds, False

    named = [i for i, row in enumerate(rows) if _clean(row["my_deck_tag"]) == deck]
    if not named:
        raise ValueError("找不到对应的套牌")
    reliable = [i for i in named if _clean(rows[i]["my_deck_id"])
                or _clean(rows[i]["my_deck_version"])]
    if reliable:
        latest = max(reliable, key=lambda i: (rows[i]["start_time"] is not None,
                                               rows[i]["start_time"] or -1,
                                               rows[i]["id"]))
        return [latest], True
    return named, False


def _identity(rows: list[dict], seeds: list[int]) -> tuple[set[int], set[str], set[str]]:
    """以 deck id / version 为二部图边，求可靠身份的连通分量。"""
    by_id: dict[str, list[int]] = {}
    by_version: dict[str, list[int]] = {}
    for i, row in enumerate(rows):
        deck_id = _clean(row["my_deck_id"])
        version = _clean(row["my_deck_version"])
        if deck_id:
            by_id.setdefault(deck_id, []).append(i)
        if version:
            by_version.setdefault(version, []).append(i)

    members: set[int] = set()
    ids: set[str] = set()
    versions: set[str] = set()
    queue: deque[tuple[str, str]] = deque()
    for i in seeds:
        deck_id = _clean(rows[i]["my_deck_id"])
        version = _clean(rows[i]["my_deck_version"])
        if deck_id:
            queue.append(("id", deck_id))
        if version:
            queue.append(("version", version))

    # 没有可靠字段时，调用方已经把全部同名行作为 seed。
    if not queue:
        return set(seeds), ids, versions

    seen_tokens: set[tuple[str, str]] = set()
    while queue:
        kind, value = queue.popleft()
        if (kind, value) in seen_tokens:
            continue
        seen_tokens.add((kind, value))
        if kind == "id":
            ids.add(value)
            linked = by_id.get(value, [])
        else:
            versions.add(value)
            linked = by_version.get(value, [])
        for i in linked:
            if i in members:
                continue
            members.add(i)
            deck_id = _clean(rows[i]["my_deck_id"])
            version = _clean(rows[i]["my_deck_version"])
            if deck_id:
                queue.append(("id", deck_id))
            if version:
                queue.append(("version", version))
    return members, ids, versions


def _visible(row: dict, exclude_abnormal: bool, exclude_bot: bool) -> bool:
    return not ((exclude_abnormal and row["is_abnormal"])
                or (exclude_bot and row["is_bot"]))


def _row_date(row: dict) -> date | None:
    ts = row["start_time"]
    return datetime.fromtimestamp(ts / 1000).date() if ts is not None else None


def _sorted(rows: list[dict]) -> list[dict]:
    return sorted(rows, key=lambda row: (row["start_time"] is not None,
                                          row["start_time"] or -1,
                                          row["id"]), reverse=True)


def _apply_scope(rows: list[dict], scope: str, today: date) -> list[dict]:
    if scope == "last20":
        return _sorted(rows)[:20]
    if scope == "all":
        return _sorted(rows)
    wanted = today if scope == "today" else today - timedelta(days=1)
    if scope == "last7":
        first = today - timedelta(days=6)
        return _sorted([row for row in rows
                        if _row_date(row) is not None and first <= _row_date(row) <= today])
    return _sorted([row for row in rows if _row_date(row) == wanted])


def _summary(rows: list[dict]) -> dict:
    decided = [row for row in rows if row["my_result"] in ("win", "loss")]
    play = [row for row in rows if row["play_draw"] == "play"]
    draw = [row for row in rows if row["play_draw"] == "draw"]
    known = len(play) + len(draw)
    return {
        "n": len(rows),
        "wins": sum(row["my_result"] == "win" for row in decided),
        "losses": sum(row["my_result"] == "loss" for row in decided),
        "unknown_result": len(rows) - len(decided),
        "win_rate": wr(sum(row["my_result"] == "win" for row in decided), len(decided)),
        "play": len(play),
        "draw": len(draw),
        "unknown_play_draw": len(rows) - known,
        "play_rate": round(100 * len(play) / known, 1) if known else None,
        "draw_rate": round(100 * len(draw) / known, 1) if known else None,
        "on_play": wr(sum(row["my_result"] == "win" for row in play),
                      sum(row["my_result"] in ("win", "loss") for row in play)),
        "on_draw": wr(sum(row["my_result"] == "win" for row in draw),
                      sum(row["my_result"] in ("win", "loss") for row in draw)),
    }


def _commander_data(conn: sqlite3.Connection, rows: list[dict], *, lang: str,
                    root=None) -> tuple[dict, dict[str, set[str]], dict[str, dict]]:
    """按对局聚合对手主将；同场同 grpId 去重，双主将分别进入两行。"""
    eligible = [row for row in rows if "Brawl" in (row["event_id"] or "")]
    eligible_by_id = {row["match_id"]: row for row in eligible}
    by_match: dict[str, set[str]] = {mid: set() for mid in eligible_by_id}
    for item in conn.execute("SELECT match_id, seat, grp_id FROM commanders"):
        match = eligible_by_id.get(item["match_id"])
        if (match is None or match["my_seat"] is None or item["seat"] is None
                or item["seat"] == match["my_seat"] or item["grp_id"] is None):
            continue
        by_match[item["match_id"]].add(str(item["grp_id"]))

    known = [row for row in eligible if by_match[row["match_id"]]]
    gids = sorted({gid for values in by_match.values() for gid in values})
    names = CardNames(conn, lang, root) if gids else None
    cards = {gid: names.get(gid) for gid in gids} if names else {}
    commander_rows = []
    for gid in gids:
        matches = [row for row in known if gid in by_match[row["match_id"]]]
        summary = _summary(matches)
        commander_rows.append({
            **cards[gid],
            **summary,
            "share_known": round(100 * len(matches) / len(known), 1) if known else None,
            "share_eligible": round(100 * len(matches) / len(eligible), 1) if eligible else None,
        })
    commander_rows.sort(key=lambda row: (-row["n"], row["key"]))
    return ({
        "eligible": len(eligible),
        "known": len(known),
        "missing": len(eligible) - len(known),
        "not_applicable": len(rows) - len(eligible),
        "distinct": len(commander_rows),
        "multi_commander_matches": sum(len(values) > 1 for values in by_match.values()),
        "rows": commander_rows,
    }, by_match, cards)


def deck_detail(conn: sqlite3.Connection, *, deck: str | None = None,
                deck_id: str | None = None, deck_version: str | None = None,
                scope: str = "last20", version: str | None = None,
                mode: str | None = None,
                exclude_abnormal: bool = True, exclude_bot: bool = True,
                today: date | None = None, lang: str = "zh", root=None,
                opponent_commander: str | None = None,
                observation: str | None = None) -> dict:
    """返回一个可靠套牌身份的独立复盘资料。

    同一 ID 或同一构筑指纹形成连接；名称只在缺可靠身份时回退使用。
    时间范围与版本均由后端应用，前端不重算统计。
    """
    deck, deck_id, deck_version, mode, opponent_commander, observation = map(
        _clean, (deck, deck_id, deck_version, mode, opponent_commander, observation))
    if not (deck or deck_id or deck_version):
        raise ValueError("请指定套牌")
    if scope not in SCOPES:
        raise ValueError("未知时间范围")
    if mode and mode not in ("BO1", "BO3", "未知"):
        raise ValueError("未知比赛模式")
    if opponent_commander and observation:
        raise ValueError("一次只能查看一种对局依据")

    rows = _all_rows(conn)
    seeds, picked_by_name = _seed_rows(rows, deck_id, deck_version, deck)
    members, ids, versions = _identity(rows, seeds)
    reliable = bool(ids or versions)
    identity_rows = [rows[i] for i in members]
    all_visible = _sorted([row for row in identity_rows
                           if _visible(row, exclude_abnormal, exclude_bot)])
    mode_counts = {key: sum((row["match_mode"] or "未知") == key for row in all_visible)
                   for key in ("BO1", "BO3", "未知")}
    visible = ([row for row in all_visible if (row["match_mode"] or "未知") == mode]
               if mode else all_visible)
    if not all_visible:
        # 身份存在但当前排除条件下没有记录，仍返回可解释的空详情。
        display_rows = identity_rows
    else:
        display_rows = visible

    aliases = sorted({_clean(row["my_deck_tag"]) for row in display_rows
                      if _clean(row["my_deck_tag"])})
    anchor_name = deck or (_clean(rows[seeds[0]]["my_deck_tag"]) if seeds else None)
    title = anchor_name or (aliases[-1] if aliases else "未命名套牌")
    if all_visible:
        recent_name = next((_clean(row["my_deck_tag"]) for row in all_visible
                            if _clean(row["my_deck_tag"])), None)
        title = recent_name or title

    same_name_unlinked = 0
    if reliable and anchor_name:
        same_name_unlinked = sum(
            _clean(row["my_deck_tag"]) == anchor_name and i not in members
            and _visible(row, exclude_abnormal, exclude_bot)
            for i, row in enumerate(rows)
        )

    version_rows: list[dict] = []
    version_values = sorted({_clean(row["my_deck_version"]) for row in visible
                             if _clean(row["my_deck_version"])},
                            key=lambda value: max((row["start_time"] or -1 for row in visible
                                                   if _clean(row["my_deck_version"]) == value)),
                            reverse=True)
    for number, value in enumerate(version_values, 1):
        selected = [row for row in visible if _clean(row["my_deck_version"]) == value]
        times = [row["start_time"] for row in selected if row["start_time"] is not None]
        version_rows.append({
            "value": value,
            "label": f"版本 {number}",
            "n": len(selected),
            "first_time": min(times) if times else None,
            "last_time": max(times) if times else None,
            "sources": sorted({_clean(row["source"]) for row in selected if _clean(row["source"])})
        })
    unknown_version = sum(not _clean(row["my_deck_version"]) for row in visible)
    if version is not None:
        version = _clean(version)
        valid = {item["value"] for item in version_rows} | ({UNKNOWN_VERSION} if unknown_version else set())
        if version not in valid:
            raise ValueError("找不到对应的构筑版本")
        if version == UNKNOWN_VERSION:
            scoped_base = [row for row in visible if not _clean(row["my_deck_version"])]
        else:
            scoped_base = [row for row in visible if _clean(row["my_deck_version"]) == version]
    else:
        scoped_base = visible

    now_day = today or datetime.now().date()
    scoped = _apply_scope(scoped_base, scope, now_day)
    scoped_known_versions = len({_clean(row["my_deck_version"]) for row in scoped
                                 if _clean(row["my_deck_version"])})
    commanders, commanders_by_match, commander_cards = _commander_data(
        conn, scoped, lang=lang, root=root)
    observations = deck_observations(scoped, commanders, commanders_by_match)
    observations_by_key = {item["key"]: item for item in observations["items"]}
    if opponent_commander and opponent_commander not in commander_cards:
        raise ValueError("当前范围没有这个对手主将的记录")
    if observation and observation not in observations_by_key:
        raise ValueError("当前范围没有这条观察")
    selected_observation = observations_by_key.get(observation)
    if opponent_commander:
        records_source = [row for row in scoped
                          if opponent_commander in commanders_by_match.get(row["match_id"], set())]
    elif selected_observation:
        evidence = set(selected_observation["match_ids"])
        records_source = [row for row in scoped if row["match_id"] in evidence]
    else:
        records_source = scoped[:200]
    games_by_match: dict[str, list[dict]] = {row["match_id"]: [] for row in records_source}
    record_ids = list(games_by_match)
    for start in range(0, len(record_ids), 500):
        batch = record_ids[start:start + 500]
        if not batch:
            continue
        for game in conn.execute(
            f"""SELECT match_id, game_no, result, reason, play_draw, duration_sec
                  FROM games WHERE match_id IN ({','.join('?' * len(batch))})
                 ORDER BY match_id, game_no""", batch):
            games_by_match[game["match_id"]].append({
                "game_no": game["game_no"], "result": game["result"],
                "reason": game["reason"], "play_draw": game["play_draw"],
                "duration_sec": game["duration_sec"],
            })
    records = [{
        "match_id": row["match_id"],
        "start_time": row["start_time"],
        "event_id": row["event_id"],
        "event_label": friendly_event(row["event_id"]),
        "play_draw": row["play_draw"],
        "my_result": row["my_result"],
        "my_deck_tag": row["my_deck_tag"],
        "my_deck_version": row["my_deck_version"],
        "source": row["source"],
        "match_mode": row["match_mode"] or "未知",
        "opponent_type_eligible": is_constructed_opponent_event(row["event_id"]),
        "opp_archetype_tag": row["opp_archetype_tag"],
        "games": games_by_match.get(row["match_id"], []),
        "opponent_commander_ids": sorted(commanders_by_match.get(row["match_id"], set())),
        "opponent_cards": [commander_cards[gid]
                           for gid in sorted(commanders_by_match.get(row["match_id"], set()))],
    } for row in records_source]

    if reliable:
        identity_note = (f"按套牌 ID 与相同构筑指纹连接记录；共 {len(ids)} 个套牌 ID、"
                         f"{len(versions)} 个已知构筑版本。")
    else:
        identity_note = "这些记录缺少套牌 ID 和构筑指纹，暂按套牌名称汇总，可能包含同名套牌。"
    if picked_by_name:
        identity_note += " 从这个名称最近使用的可靠身份进入。"
    if same_name_unlinked:
        identity_note += f" 另有 {same_name_unlinked} 场同名记录无法与此身份连接，未合并。"

    return {
        "title": title,
        "scope": scope,
        "scope_label": SCOPES[scope],
        "selected_mode": mode,
        "modes": [{"value": key, "label": key, "n": mode_counts[key]}
                  for key in ("BO1", "BO3", "未知") if mode_counts[key]],
        "selected_version": version,
        "identity": {
            "basis": "id_version" if reliable else "name_fallback",
            "note": identity_note,
            "aliases": aliases,
            "deck_ids": sorted(ids),
            "same_name_unlinked": same_name_unlinked,
        },
        "versions": version_rows,
        "unknown_version": unknown_version,
        "version_count_in_scope": scoped_known_versions,
        "summary": _summary(scoped),
        "observations": observations,
        "opponent_commanders": commanders,
        "selected_commander": commander_cards.get(opponent_commander),
        "selected_observation": selected_observation,
        "records": records,
        "records_total": (len(records_source)
                          if opponent_commander or selected_observation else len(scoped)),
        "records_truncated": not (opponent_commander or selected_observation)
                             and len(scoped) > len(records),
        "as_of": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
