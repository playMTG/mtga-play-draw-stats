# -*- coding: utf-8 -*-
"""每日评语话术库：本地规则生成调侃句，少用纯感叹，论据不进主句。

同一天同一组证据固定选同一句（按 match_id 哈希），避免刷新换话。
要加句子：往对应 kind 的列表里追加模板即可；`{n}` `{name}` `{side}` 会被替换。
"""
from __future__ import annotations

import hashlib

# side: play=先手 draw=后手
# 用户口径（2026-09-14）：「评语太平淡了，不够激情」。所以这里往「有情绪、有画面」
# 的方向写，但两条红线不能破：① 不能编事实（只描述记录里真有的东西）；
# ② 不用纯感叹词凑数（「卧槽」「哇」「太美」有测试守着）。
TEMPLATES = {
    "hot_wr": [
        "今天手是真的热，赢得干脆",
        "状态拉满，对手基本没还上手",
        "今天你说了算，一路平推",
        "这状态再打下去要被人举报了",
        "手感烫手，怎么打怎么有",
    ],
    "hot_wr_perfect": [
        "今天几乎全胜，牌桌上没人拦得住你",
        "这战绩已经不是运气了，是碾压",
        "全胜收官，今天你就是牌桌的主人",
    ],
    "pd_skew_play": [
        "今天把把先手，牌运直接站你这边",
        "先手连轴转，对面连地都没铺开",
        "今天轮到你先动，一动手就是压制",
    ],
    "pd_skew_draw": [
        "今天几乎全是后手，属实有点惨",
        "后手接到手软，节奏全在对面手里",
        "今天牌桌明摆着不站你这边",
    ],
    "streak_legendary_play": [
        "{n} 连先手，这牌运离谱得不像话",
        "{n} 连先手，系统今天是不是偏心了",
        "{n} 连先手，打得对面怀疑人生",
    ],
    "streak_legendary_draw": [
        "{n} 连后手，霉得都快成固定节目了",
        "{n} 连后手，这运气真该去买张彩票",
        "{n} 连后手，今天牌桌跟你杠上了",
    ],
    "streak_rare_play": [
        "{n} 连先手，手感正顺",
        "{n} 连先手，这波节奏在你手里",
    ],
    "streak_rare_draw": [
        "{n} 连后手，今天有点背",
        "{n} 连后手，节奏被压着走",
    ],
    "streak_other_play": [
        "{n} 连先手，顺手",
    ],
    "streak_other_draw": [
        "{n} 连后手，不太顺",
    ],
    "repeat_commander": [
        "又和 {name} 碰上了，这缘分不浅",
        "今天老朋友 {name} 又来了",
        "{name}：怎么又是你",
        "跟 {name} 的孽缘今天又续上了",
    ],
    # 连续 N 把（中间没夹别人）撞上同一个人：比零散遇到 N 次更值得说重一点。
    "repeat_commander_streak": [
        "{n} 连撞 {name}，这已经不是缘分，是锁定了",
        "连着 {n} 把都是 {name}，匹配系统是不是只会这一手",
        "{n} 连遇 {name}，今天的牌桌就这么大？",
        "{name} 堵了你 {n} 把，躲都躲不开",
    ],
    "volume_marathon": [
        "今天是真·耐力局，一口气 {n} 场",
        "肝了一整天，记录里整整 {n} 场",
        "今天完全泡在牌桌上，{n} 场打满",
        "{n} 场连轴转，牌桌都快坐穿了",
    ],
    "volume_long": [
        "今天打了很久，足足 {n} 场",
        "场次拉满，{n} 场",
        "{n} 场下来，今天没少花时间",
    ],
    "volume_marathon_hours": [
        "连肝约 {hours} 小时，{n} 场",
        "从头打到尾，约 {hours} 小时 / {n} 场",
        "约 {hours} 小时、{n} 场，今天是场持久战",
    ],
    # 同一天里撞上同一个**玩家** ≥3 次。与「重复主将」分开：主将重复常常只是
    # 环境里同一副牌多，玩家重复说明当天真的反复排到同一个人。
    "repeat_opponent": [
        "今天排到 {name} {n} 次，这匹配池是不是就这么大",
        "跟 {name} 一天碰了 {n} 回，你俩今晚有缘",
        "{n} 次遇上 {name}，躲都躲不开",
        "{name} 今天来了 {n} 趟，牌桌就这么几个人？",
    ],
    "single_win": [
        "开门红，这局拿下了",
        "首局赢了，节奏开了",
    ],
    "single_loss": [
        "首局惜败，后面再找手感",
        "开局不顺，先记一笔",
    ],
    "single_unknown": [
        "这局结果还没写进记录",
    ],
}


def pick(key: str, seed_parts: list[str], **fmt) -> str:
    """按证据稳定挑一句模板并格式化；无模板时回退空串。"""
    options = TEMPLATES.get(key) or []
    if not options:
        return ""
    blob = "|".join(seed_parts).encode("utf-8")
    idx = int(hashlib.sha1(blob).hexdigest()[:8], 16) % len(options)
    text = options[idx]
    try:
        return text.format(**fmt)
    except (KeyError, IndexError):
        return text
