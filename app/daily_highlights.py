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



# ---------- 选材引擎（今日评价 v2，2026-09-15） ----------
#
# 旧版用固定优先级表（`_rank`）挑前两条事实。优先级表的问题是**没有量纲**：它只知道
# 「A 类比 B 类重要」，不知道「今天这个 A 有多罕见」。于是本机 1.1 万场里大部分日子都
# 触发同样那 2–3 条规则、输出同一句调侃（用户反馈「这个体系不太行」）。
#
# 新版给每个候选算一个**戏剧分**，再按「三拍解说」装配。设计见
# docs/DESIGN.md「今日评价 v2 规划」。

# 主题：三拍必须分属不同主题，否则会像现在这样两句都在说同一件事。
# 分组要**细到「是不是同一个话题」**：胜率与先后手连击虽然都跟运气有关，但一个是
# 「赢了没有」、一个是「谁先动」，是两件事，不该互相挤掉（最初把两者都归进 luck，
# 结果 20 场全胜全后手只剩一条）。
_THEME = {
    "hot_wr": "result",
    "play_draw_streak": "side", "pd_skew": "side",
    "repeat_commander": "opponent", "repeat_opponent": "opponent",
    "rare_commander": "opponent",
    "revenge": "opponent", "nemesis": "opponent",
    "volume": "tempo", "blitz": "tempo", "arc": "tempo",
    "milestone": "history",
}

# 每个类别的「分量」基准。数值只用于横向比较，不必有绝对含义。
# **场次刻意给得很低**：它是背景板，不该压过「一天里遇到同一个人 3 次」这类真事实
# （2026-09-14 用户口径：「一旦打长了就必然只有一条说今天打了很久」）。
_WEIGHT = {
    "milestone": 1.1, "hot_wr": 1.0, "play_draw_streak": 1.0,
    "revenge": 0.95, "repeat_opponent": 0.9, "nemesis": 0.85,
    "repeat_commander": 0.85, "arc": 0.8, "rare_commander": 0.75,
    "pd_skew": 0.6, "blitz": 0.5, "volume": 0.25,
}

# 里程碑的整数关口。刻意稀疏——每一关都报就没人在意了。
MILESTONES = (100, 250, 500, 1000, 1500, 2000, 2500, 3000, 4000, 5000,
              6000, 7000, 8000, 9000, 10000, 12000, 15000, 20000)

# 「久违的主将」的门槛：见过、但距今这么多天没再遇到。
# 实测（全历史 882 天）180 天会触发 45 天 = 5%，是合适的稀有度。
RARE_COMMANDER_DAYS = 180


def _theme(kind: str) -> str:
    return _THEME.get(kind, "other")


def _drama(c: dict, n: int, recent_kinds: dict[str, int]) -> float:
    """戏剧分 = 稀有度 × 分量 × 证据量 × 新鲜度 × 级别加成。越大越该当开场。

    刻意**不用「证据占比」**：占比会让场次白拿满分（它的分母就是当天总场次），
    而重复对手这类事实的分母是当天全部对局，22 场里遇到 3 次只有 13.7%，按占比
    算会被场次压过去——正是用户反馈要修的那个毛病。改用**绝对证据量**的对数微调：
    3 次与 30 次的差别是真实的，但不该是线性的。

    - 稀有度：有理论概率的（先后手连击）用 `sqrt(1/p)` 量级（封顶 50）；
    - 新鲜度：最近 7 天说过同类事实就降权——治「天天同一句」的关键。但**必须封顶**：
      第一版用 `1/(1+次数)`，连续说 7 天就降成 1/8，结果 2026-09-14 那天「一天里遇到
      同一个人 3 次」被压到阈值以下，评语退化成只剩一句「22 场连轴转」——正好退回
      用户上次抱怨的状态。降权只能是**并列时的偏好**，不能变成「有也不说」。
      → 封顶 2.5 倍，且转折用相对阈值。
    """
    import math
    rarity = 1.0
    prob = (c.get("probability") or {}).get("p")
    if isinstance(prob, (int, float)) and 0 < prob < 1:
        rarity = min(1.0 / prob, 50.0) ** 0.5
    base = _WEIGHT.get(c["kind"], 0.5)
    evidence = 1.0 + 0.12 * math.log(1 + max(c.get("n") or 0, 0))
    seen = recent_kinds.get(c["kind"], 0)
    freshness = 1.0 / (1 + 0.6 * min(seen, 3))   # 最多降到 0.36 倍，不封死
    level_bonus = 1.4 if c.get("level") == "legendary" else 1.0
    return rarity * base * evidence * freshness * level_bonus


def _assemble(cands: list[dict], n: int, recent_kinds: dict[str, int]) -> list[dict]:
    """按「开场 → 转折 → 收尾」装配，每拍主题不重复。

    两条硬规则：

    1. **场次永远排最后**。它现在已经在顶部统计卡里写着（「今日 15 胜 9 负」），
       评语再花一格复述它是纯浪费；它只在「确实没别的可说」时当开场。
       这条不交给戏剧分——`level="legendary"` 会让它白拿 1.4 倍加成，实测会把
       「一天里遇到同一个人 3 次」压下去。
    2. 转折用**相对阈值**（相对开场一档）。用绝对值会让「今天确实发生了、但最近
       说过」的事实被整条丢掉，最后只剩背景板（2026-09-14 实测踩过）。
    """
    if not cands:
        return []
    def sort_key(c):
        return (c["kind"] == "volume", -_drama(c, n, recent_kinds), -c["n"])
    scored = sorted(cands, key=sort_key)
    lede = scored[0]
    lede_score = _drama(lede, n, recent_kinds)
    picks = [lede]
    used = {_theme(lede["kind"])}
    for c in scored[1:]:
        if len(picks) >= 2:
            break
        if _theme(c["kind"]) in used:
            continue
        # 转折要跟开场是同一量级，否则不如不说
        if _drama(c, n, recent_kinds) < 0.3 * lede_score:
            continue
        picks.append(c)
        used.add(_theme(c["kind"]))
    return picks


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


def highlights(rows, recent_kinds: dict[str, int] | None = None,
               context: dict | None = None):
    recent_kinds = recent_kinds or {}
    context = context or {}
    if not rows:
        return []
    rows = sorted(rows, key=lambda r: (r["start_time"], r["match_id"]))
    n = len(rows)
    wins = sum(r["my_result"] == "win" for r in rows)
    candidates = []

    def add(kind, text, evidence, denominator, **extra):
        # 只补句号：模板里已经有「？」「！」「…」时不能再补，否则出现「？。」
        if text and text[-1] not in "。？！…":
            text += "。"
        candidates.append({
            "kind": kind,
            "text": text,
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

    # 同一天里撞上同一个**玩家** ≥3 次（用户口径 2026-09-15）。
    # 与上面的「重复主将」是两回事：主将维度的重复常常只是环境里同一副牌多，
    # 玩家维度的重复说明当天真的反复排到同一个人。玩家名来自日志的 opponent_name。
    opponents = defaultdict(list)
    for r in rows:
        name = (r.get("opponent_name") or "").strip()
        if name and not r.get("is_bot"):
            opponents[name].append(r)
    if opponents:
        oname = min(opponents, key=lambda k: (-len(opponents[k]), k))
        ogroup = opponents[oname]
        if len(ogroup) >= 3:
            add(
                "repeat_opponent",
                pick("repeat_opponent", [r["match_id"] for r in ogroup] + [oname],
                     n=len(ogroup), name=oname),
                ogroup,
                n,
                level="legendary",
            )

    # ---- 当天走势（转折点）：先连输后连赢 = 回魂；先连赢后连输 = 崩盘 ----
    # 只看有胜负的对局；两段各 ≥3 场才算「走势」，否则只是普通波动。
    seq = [r for r in rows if r["my_result"] in ("win", "loss")]
    if len(seq) >= 6:
        head_res = seq[0]["my_result"]
        head_n = 1
        while head_n < len(seq) and seq[head_n]["my_result"] == head_res:
            head_n += 1
        tail_res = seq[-1]["my_result"]
        tail_n = 1
        while tail_n < len(seq) and seq[-1 - tail_n]["my_result"] == tail_res:
            tail_n += 1
        if (head_res != tail_res and head_n >= 3 and tail_n >= 3
                and head_n + tail_n <= len(seq)):
            key = "arc_comeback" if head_res == "loss" else "arc_collapse"
            add("arc", pick(key, [r["match_id"] for r in seq] + [key],
                            first=head_n, last=tail_n),
                seq, n, level="legendary" if head_res == "loss" else "rare",
                first=head_n, last=tail_n)

    # ---- 闪电局：一分钟内就结束的对局 ----
    blitz = [r for r in rows if (r.get("duration_sec") or 0) and r["duration_sec"] < 60]
    if len(blitz) >= 3:
        add("blitz", pick("blitz", [r["match_id"] for r in blitz], n=len(blitz)),
            blitz, n)

    # ---- 里程碑：当天的对局跨过整数关口 ----
    # 「第 N 场」是玩家真正会记住的东西，而且**天然稀有**（只在关口那天出现），
    # 所以它是这个体系里最该当开场的一类。
    total_before = context.get("total_before")
    if total_before is not None:
        for mark in MILESTONES:
            if total_before < mark <= total_before + n:
                add("milestone", pick("milestone", [str(mark)], total=mark), rows, n,
                    level="legendary")
                break

    # ---- 复仇 / 苦主：跟同一个人的交手历史 ----
    # 「个人相关度」最直接的体现——比「遇到同一个主将」强，因为对手名是同一个玩家。
    prior = context.get("opponents") or {}
    if prior:
        best_revenge = None
        best_nemesis = None
        for r in rows:
            name = (r.get("opponent_name") or "").strip()
            if not name or r.get("is_bot"):
                continue
            wins, losses = prior.get(name, (0, 0))
            if r["my_result"] == "win" and losses >= 2 and losses > wins:
                # 之前交手是明显劣势，今天拿下了
                if best_revenge is None or losses > best_revenge[1]:
                    best_revenge = (name, losses, wins, r)
            elif r["my_result"] == "loss" and losses >= 3 and wins == 0:
                # 从没赢过的对手，今天又输了
                if best_nemesis is None or losses > best_nemesis[1]:
                    best_nemesis = (name, losses, wins, r)
        if best_revenge:
            name, losses, wins, r = best_revenge
            add("revenge", pick("revenge", [r["match_id"], name],
                                name=name, losses=losses, wins=wins), [r], n)
        if best_nemesis:
            name, losses, wins, r = best_nemesis
            add("nemesis", pick("nemesis", [r["match_id"], name],
                                name=name, losses=losses, wins=wins), [r], n)

    # ---- 久违的主将：见过、但很久没再遇到 ----
    # 实测（全历史 882 天）≥180 天会触发 45 天 = 5%，稀有度合适；样例「命源御神体，642 天没见」
    # 这类话只有全库 last_seen 才说得出来。
    seen_before = context.get("commanders") or {}
    if seen_before:
        oldest = None
        for r in rows:
            day_ms = r.get("start_time")
            if not day_ms:
                continue
            for gid, name in zip(r.get("commanders") or [],
                                 r.get("commander_names") or []):
                last = seen_before.get(gid)
                if last is None:
                    continue          # 从没见过 = 首次相遇，不是「久违」
                gap_days = int((day_ms - last) / 86_400_000)
                if gap_days >= RARE_COMMANDER_DAYS and (oldest is None or gap_days > oldest[1]):
                    oldest = (name, gap_days, r)
        if oldest:
            name, gap, r = oldest
            add("rare_commander",
                pick("rare_commander", [r["match_id"], name], name=name, days=gap),
                [r], n, level="legendary" if gap >= 365 else "rare", days=gap)

    # 只保留真正的亮点；不再补一句「这一天已记录 N 场，X 胜 Y 负」——
    # 那个数字在下方统计卡里已逐项列出，放进评语纯属复读（用户反馈）。
    top = [c for c in candidates if c["kind"] != "results"]
    top = _filter_for_volume(top, n, volume)
    return _assemble(top, n, recent_kinds)
