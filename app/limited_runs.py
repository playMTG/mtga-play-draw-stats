# -*- coding: utf-8 -*-
"""限制赛「单次 run」的切分与分档（评语用）。

一次 draft／现开 = 一个 run：**打满胜场上限或吃满负场即结束**。
本模块只做两件事：

1. `split_runs(rows)` —— 按时间顺序把限制赛对局切成一个个 run，**只返回已打完的**；
2. `band(spec, wins)` —— 把胜场折成档位（卷／差一把／回了／没回本／白给）。

话术在 `daily_copy.py`（`limited_*` 各库），选材与装配在 `daily_highlights.py`。

## 上限与「回本」线的来源（2026-09-20 核验）

| 赛事 | 前缀 | 入场 | 胜场上限 | 负场上限 | 回本线（奖励折算 ≈ 入场费） |
|---|---|---|---|---|---|
| 优选轮抽 BO1 | `PremierDraft_` | 1500 宝石 | 7 | 3 | 3 胜（1000 宝石 + 2 包） |
| 快速轮抽 BO1 | `QuickDraft_` | 750 宝石 | 7 | 3 | 5 胜（650 宝石 + 1 包） |
| 选两张轮抽 BO1 | `PickTwoDraft_` | 900 宝石 | 4 | 2 | 2 胜（800 宝石 + 1 包，官方社区口径「几乎回本」） |
| 传统轮抽 BO3 | `TradDraft_` | 1500 宝石 | 3 | 2 | 2 胜（1000 宝石 + 3 包） |
| 竞争者轮抽 BO1 | `ContenderDraft_` | 3000 宝石 | 7 | 3 | 4 胜（2800 宝石 + 6 包；0–2 胜零奖励） |
| 现开 BO1 | `Sealed_` | 2000 宝石 | 7 | 3 | 6 胜（宝石够再开一轮） |
| 传统现开 BO3 | `Trad_Sealed_` | 2000 宝石 | 4 | 2 | 4 胜 |

来源：优选轮抽逐级奖励与「7 胜／3 负结束」见 MagicArena Wiki（Premier Draft）；快速轮抽奖励表
见 Draftsim（「只有 6 胜才真的超过入场成本」）；选两张轮抽的 4 胜档与「两胜几乎回本」见
Draftsim（Pick-Two Draft，入场 900 宝石）；现开「6 胜可再开一轮」、传统现开「4 胜」见
Draftsim（Sealed）；竞争者轮抽的 0–2 胜零奖励与「4 胜回本」见 Draftsim（Contender Draft）。
**「回本」一律按宝石 + 补充包（1 包 ≈ 200 宝石）折算，不计开出来的收藏价值**——这个口径
正好复现用户给的两条线（优选 3 胜回了、选二 2 胜回了）。

数据侧核对：本机 2007 场限制赛按 `(event_id, my_deck_id)` 分组后，各赛事的「胜-负」组合与
上表一致（优选出现 0-3…7-0/7-1/7-2；选两张只出现 0-2…4-1，从不出现 5 胜或 3 负）。

## 为什么不评 MWM／十项全能／全知轮抽

这些活动赛**没有固定的 run 边界**：本机 `MWM_OmniscienceDraft_20251223` 单个 deck 组里
有 132 场、89 胜 43 负（能一直打），套上「7 胜 = 卷」会把活动赛误判成天天卷。
所以只认上面那张表的**标准队列前缀**，其余一律返回 None（不评）。
"""
from __future__ import annotations

from dataclasses import dataclass

from .event_names import friendly_event

# (前缀, kind, 胜场上限, 负场上限, 回本线)
# 前缀顺序无冲突（`Trad_Sealed_` 不以 `Sealed_` 开头），但保持「长前缀在前」的习惯。
RULES = (
    ("PickTwoDraft_", "picktwo", 4, 2, 2),
    ("PremierDraft_", "premier", 7, 3, 3),
    ("QuickDraft_", "quick", 7, 3, 5),
    ("TradDraft_", "trad", 3, 2, 2),
    ("TraditionalDraft_", "trad", 3, 2, 2),
    ("ContenderDraft_", "contender", 7, 3, 4),
    ("Trad_Sealed_", "trad_sealed", 4, 2, 4),
    ("TraditionalSealed_", "trad_sealed", 4, 2, 4),
    ("Sealed_", "sealed", 7, 3, 6),
)

# 档位 → 话术库后缀。顺序即优先级：打满 > 差一把 > 回本 > 没回本 > 白给。
# 「差一把」排在「回本」前面：现开 6 胜既是回本线又是差一把（上限 7），
# 按用户口径「差一把卷，可惜了」更值得说，所以它优先。
BANDS = ("cap", "near", "even", "low", "bust")


@dataclass(frozen=True)
class Spec:
    kind: str
    label: str        # 赛制中文名（取自 event_names，与页面同一口径）
    cap_wins: int
    cap_losses: int
    break_even: int


def short_label(event_id: str) -> str:
    """「选两张轮抽 · 霍比特人 · 2026-08-11」→「选两张轮抽」。

    刻意**从 `friendly_event` 派生**而不是在本模块另写一份译名表：
    页面显示名改了这里跟着改，不会两处不一致（`data/event_names.zh.json` 的本地覆盖同样生效）。
    """
    return friendly_event(event_id).split(" · ")[0]


def spec_for(event_id: str | None) -> Spec | None:
    """这个 event_id 属不属于「有固定 run 边界的标准限制赛」；不属于返回 None。"""
    if not event_id:
        return None
    for prefix, kind, cap_wins, cap_losses, break_even in RULES:
        if event_id.startswith(prefix):
            return Spec(kind, short_label(event_id), cap_wins, cap_losses, break_even)
    return None


def band(spec: Spec, wins: int) -> str:
    """胜场 → 档位。见 BANDS 的优先级说明。"""
    if wins >= spec.cap_wins:
        return "cap"
    if wins == spec.cap_wins - 1:
        return "near"
    if wins <= 0:
        return "bust"
    if wins >= spec.break_even:
        return "even"
    return "low"


def split_runs(rows) -> list[dict]:
    """把限制赛对局按时间切成 run，**只返回已打完的**。

    判据是「胜场吃满上限」或「负场吃满上限」，不看 `my_deck_id`：
    - 同一天同一赛事可能开两轮（两轮的临时牌组不同），所以按 `(event_id, my_deck_id)`
      分开计数；
    - 反过来，本机有些赛事会让多个 run 共用一个 `my_deck_id`（`MWM_*` 那类活动赛），
      所以**结束靠胜/负上限判断、不靠 deck_id 变化**——活动赛本来就不在 RULES 里。

    没打完的 run 不返回：宁可不说，也不能把 2-1 的中途成绩说成一轮的结果。
    """
    open_runs: dict[tuple, dict] = {}
    done: list[dict] = []
    for r in sorted(rows, key=lambda x: (x.get("start_time") or 0, x.get("match_id") or "")):
        spec = spec_for(r.get("event_id"))
        if spec is None:
            continue
        result = r.get("my_result")
        if result not in ("win", "loss"):
            continue      # 结果未知不进 run：不猜
        key = (r.get("event_id"), r.get("my_deck_id") or "")
        cur = open_runs.get(key)
        if cur is None:
            cur = open_runs[key] = {"spec": spec, "wins": 0, "losses": 0, "rows": []}
        cur["wins"] += result == "win"
        cur["losses"] += result == "loss"
        cur["rows"].append(r)
        if cur["wins"] >= spec.cap_wins or cur["losses"] >= spec.cap_losses:
            done.append(_finish(cur))
            del open_runs[key]
    return done


def _finish(cur: dict) -> dict:
    spec, wins, losses = cur["spec"], cur["wins"], cur["losses"]
    rows = cur["rows"]
    return {
        "event_id": rows[0].get("event_id"),
        "label": spec.label,
        "kind": spec.kind,
        "wins": wins,
        "losses": losses,
        "cap": spec.cap_wins,
        "break_even": spec.break_even,
        "band": band(spec, wins),
        "perfect": losses == 0,      # 一轮没输过
        "end_time": rows[-1].get("start_time"),
        "match_ids": [r["match_id"] for r in rows],
        "rows": rows,
    }


def rank(run: dict) -> tuple:
    """多轮同一天时挑哪一轮来评：先看档位，再看胜场，最后看结束得晚的。

    档位优先级用 `BANDS` 的顺序（越靠前越好），所以取**负的**下标交给 `max`——
    第一版直接返回 `BANDS.index`，`max` 于是挑中了「没回本」那一轮，
    实测表现为「当天有一轮 7-2 卷了，评语却写 3 胜没够本」。
    """
    return (-BANDS.index(run["band"]), run["wins"], run["end_time"] or 0)


def best_run(runs: list[dict]) -> dict | None:
    """当天最值得说的一轮（`rank` 最大者）。"""
    return max(runs, key=rank) if runs else None
