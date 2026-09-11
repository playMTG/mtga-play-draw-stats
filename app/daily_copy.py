# -*- coding: utf-8 -*-
"""每日评语话术库：本地规则生成调侃句，少用纯感叹，论据不进主句。

同一天同一组证据固定选同一句（按 match_id 哈希），避免刷新换话。
要加句子：往对应 kind 的列表里追加模板即可；`{n}` `{name}` `{side}` 会被替换。
"""
from __future__ import annotations

import hashlib

# side: play=先手 draw=后手
TEMPLATES = {
    "hot_wr": [
        "今天胜率真亮眼",
        "状态在线，赢得很顺",
        "今天手气不错，基本没怎么输",
        "这胜率放平时都算好日子",
    ],
    "hot_wr_perfect": [
        "今天你太强了，几乎把把赢",
        "这战绩，今天没人拦得住",
    ],
    "pd_skew_play": [
        "今天把把先手，牌运站在你这边",
        "先手连轴转，对手压力很大",
        "今天轮不到对面先动",
    ],
    "pd_skew_draw": [
        "今天有点霉，几乎把把后手",
        "后手接得手软，体感偏背",
        "今天全是后手，属实有点惨",
    ],
    "streak_legendary_play": [
        "{n} 连先手，这牌运有点离谱",
        "{n} 连先手，系统是不是偏心了",
        "{n} 连先手，打得太舒服了",
    ],
    "streak_legendary_draw": [
        "{n} 连后手，霉得很有节奏",
        "{n} 连后手，这运气可以去买彩票",
        "{n} 连后手，今天牌桌不太站你这边",
    ],
    "streak_rare_play": [
        "{n} 连先手，有点东西",
        "{n} 连先手，值得记一笔",
    ],
    "streak_rare_draw": [
        "{n} 连后手，今天偏背",
        "{n} 连后手，体感有点崩",
    ],
    "streak_other_play": [
        "{n} 连先手，顺手",
    ],
    "streak_other_draw": [
        "{n} 连后手，不太顺",
    ],
    "repeat_commander": [
        "又和 {name} 碰上了，挺有缘分",
        "今天老朋友 {name} 又来了",
        "{name}：怎么又是你",
        "跟 {name} 的孽缘又续上了",
    ],
    "results": [
        "这一天已记录 {n} 场，{wins} 胜 {losses} 负",
    ],
    "volume_marathon": [
        "今天是真·耐力局，一口气 {n} 场",
        "肝了一整天，记录里整整 {n} 场",
        "今天完全泡在牌桌上，{n} 场打满",
    ],
    "volume_long": [
        "今天打了很久，足足 {n} 场",
        "场次拉满，{n} 场",
    ],
    "volume_marathon_hours": [
        "连肝约 {hours} 小时，{n} 场",
        "从头打到尾，约 {hours} 小时 / {n} 场",
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
