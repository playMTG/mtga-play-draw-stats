# -*- coding: utf-8 -*-
"""V2 主将环境观察：用 X 时环境里常遇到谁、先后手如何、对手基线对照。

只描述观察，不输出「被针对」。基线默认为库内全部争锋、主将已知的对局。
"""
from __future__ import annotations

from collections import Counter
from typing import Iterable

from .card_names import CardNames
from .stats import wr


def _seat_maps(conn, match_ids: Iterable[str], my_seats: dict[str, int | None]):
    """match_id -> set(opp grp_id)；以及 match_id -> set(my grp_id)。"""
    opp: dict[str, set[str]] = {mid: set() for mid in match_ids}
    mine: dict[str, set[str]] = {mid: set() for mid in match_ids}
    ids = list(match_ids)
    for start in range(0, len(ids), 400):
        batch = ids[start:start + 400]
        if not batch:
            continue
        ph = ",".join("?" * len(batch))
        for row in conn.execute(
            f"SELECT match_id, seat, grp_id FROM commanders WHERE match_id IN ({ph})",
            batch,
        ):
            gid = row["grp_id"]
            if gid is None:
                continue
            mid = row["match_id"]
            if mid not in opp:
                continue
            seat = row["seat"]
            my_seat = my_seats.get(mid)
            if seat is None or my_seat is None:
                continue
            if seat == my_seat:
                mine[mid].add(str(gid))
            else:
                opp[mid].add(str(gid))
    return opp, mine


def commander_environment(conn, *, deck_rows: list[dict],
                          baseline_rows: list[dict] | None = None,
                          lang: str = "zh", root=None) -> dict | None:
    """deck_rows：当前套牌身份的可见争锋对局。

    返回 None 表示当前套牌不适用（无争锋/无主将资料）。
    """
    brawl = [r for r in deck_rows if "Brawl" in (r.get("event_id") or "")]
    if not brawl:
        return None
    deck_ids = [r["match_id"] for r in brawl]
    my_seats = {r["match_id"]: r.get("my_seat") for r in brawl}
    opp_by, mine_by = _seat_maps(conn, deck_ids, my_seats)
    known = [r for r in brawl if opp_by.get(r["match_id"])]
    if not known:
        return {
            "applicable": True,
            "known": 0,
            "eligible": len(brawl),
            "note": "争锋对局里还没有可识别的对手主将，环境观察暂无法生成。",
            "rows": [],
            "play_draw": {"play": 0, "draw": 0, "unknown_pd": len(brawl)},
            "baseline": None,
        }

    # 我方主将（可多人/伙伴）
    my_cmd_counts: Counter[str] = Counter()
    for mid in deck_ids:
        my_cmd_counts.update(mine_by.get(mid) or ())
    names = CardNames(conn, lang, root)
    my_commanders = [
        {**names.get(gid), "n": n}
        for gid, n in my_cmd_counts.most_common(4)
    ]

    opp_counts: Counter[str] = Counter()
    opp_match_lists: dict[str, list[dict]] = {}
    for r in known:
        for gid in opp_by[r["match_id"]]:
            opp_counts[gid] += 1
            opp_match_lists.setdefault(gid, []).append(r)

    # 基线：库内全部争锋、主将已知（默认未传入时现算）
    if baseline_rows is None:
        baseline_rows = [
            dict(row)
            for row in conn.execute(
                """SELECT match_id, my_seat, play_draw, my_result, event_id
                     FROM matches
                    WHERE event_id LIKE '%Brawl%' AND my_seat IS NOT NULL"""
            )
        ]
    base_ids = [r["match_id"] for r in baseline_rows]
    base_seats = {r["match_id"]: r.get("my_seat") for r in baseline_rows}
    base_opp, _ = _seat_maps(conn, base_ids, base_seats)
    base_known = [r for r in baseline_rows if base_opp.get(r["match_id"])]
    base_counts: Counter[str] = Counter()
    for r in base_known:
        for gid in base_opp[r["match_id"]]:
            base_counts[gid] += 1
    base_n = len(base_known)

    rows = []
    for gid, n in opp_counts.most_common(12):
        matches = opp_match_lists[gid]
        s_play = [r for r in matches if r.get("play_draw") == "play"]
        s_draw = [r for r in matches if r.get("play_draw") == "draw"]
        decided = [r for r in matches if r.get("my_result") in ("win", "loss")]
        wins = sum(r["my_result"] == "win" for r in decided)
        base_share = round(100 * base_counts[gid] / base_n, 1) if base_n else None
        rows.append({
            **names.get(gid),
            "n": n,
            "share_known": round(100 * n / len(known), 1),
            "baseline_share": base_share,
            "delta_pp": (
                round(100 * n / len(known) - base_share, 1)
                if base_share is not None else None
            ),
            "win_rate": wr(wins, len(decided)),
            "on_play": wr(sum(r["my_result"] == "win" for r in s_play),
                          sum(r.get("my_result") in ("win", "loss") for r in s_play)),
            "on_draw": wr(sum(r["my_result"] == "win" for r in s_draw),
                          sum(r.get("my_result") in ("win", "loss") for r in s_draw)),
        })

    play = sum(r.get("play_draw") == "play" for r in brawl)
    draw = sum(r.get("play_draw") == "draw" for r in brawl)

    return {
        "applicable": True,
        "eligible": len(brawl),
        "known": len(known),
        "my_commanders": my_commanders,
        "play_draw": {
            "play": play,
            "draw": draw,
            "unknown_pd": len(brawl) - play - draw,
            "play_rate": round(100 * play / (play + draw), 1) if play + draw else None,
            "draw_rate": round(100 * draw / (play + draw), 1) if play + draw else None,
        },
        "baseline": {
            "known": base_n,
            "label": "库内全部争锋、主将已知对局",
        },
        "rows": rows,
        "note": (
            f"对手占比以本套牌主将已知的 {len(known)} 场为分母；"
            f"基线为{('库内全部争锋、主将已知的 ' + str(base_n) + ' 场') if base_n else '（暂无基线）'}。"
            "只描述遭遇与战绩，不代表匹配意图。"
        ),
    }
