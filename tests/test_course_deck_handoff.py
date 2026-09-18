# -*- coding: utf-8 -*-
"""启动回填与监听器是**两个独立 builder**，回填学到的状态必须能交棒（2026-09-18 真 BUG）。

**现象**：用户报 09-18 19:19 那场在页面上显示「套牌未记录」，而同一天后三场都正常。
**机制**：MTGA 在**开赛前**才发 `EventSetDeckV3` / `CourseDeckSummary` 来声明本场用哪副牌；
`_course_decks` 只活在 `SessionBuilder` 实例里，而启动回填与接手的监听器各用一个 builder
（还并发跑）。监听器一旦从那条选牌事件**之后**的水位线起步，就永远学不到这套映射。
后三场没事，是因为 MTGA 每场开赛前都会再发一次。
**复现**（用真实日志验证过）：从选牌事件之前回放 → `deck_tag=竞技哪失0915`；
从之后回放 → `deck_tag=None`。

所以这里钉住两件事：
1. 回填要把学到的映射**交出来**（`SessionBuilder.course_decks` → `backfill()` 的返回值）；
2. 监听器要能**接住**（`set_course_decks`），包括把已经建好、还没落库的那场对局补上。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tests.fixtures as fx
from app.events import SessionBuilder


def deck_event(event="Play_Brawl_Historic", name="Example", deck_id="sample-deck"):
    return json.dumps({
        "InternalEventName": event,
        "CourseDeckSummary": {"Name": name, "DeckId": deck_id},
        "CourseDeck": {"MainDeck": [{"cardId": 1, "quantity": 60}],
                       "CommandZone": [{"cardId": 99, "quantity": 1}]},
    })


def test_backfill_hands_the_deck_mapping_to_the_watcher():
    """监听器错过选牌事件 → 套牌名丢失；补挂映射后必须能拿到。"""
    # 回填的 builder 看过选牌事件，学到了映射
    filler = SessionBuilder(my_player_id=fx.ME)
    filler.feed(deck_event())
    learned = filler.course_decks
    assert learned and learned["Play_Brawl_Historic"][0] == "Example", "用例前提不成立"

    # 监听器是全新 builder、只看到对局——这就是 BUG 现场
    missed = SessionBuilder(my_player_id=fx.ME)
    for line in fx.bo1_match_lines():
        missed.feed(line)
    assert missed.close().matches[0].my_deck_tag is None

    # 补挂映射后，同一批日志必须能解析出套牌名
    watcher = SessionBuilder(my_player_id=fx.ME)
    watcher.set_course_decks(learned)
    for line in fx.bo1_match_lines():
        watcher.feed(line)
    m = watcher.close().matches[0]
    assert m.my_deck_tag == "Example" and m.my_deck_id == "sample-deck"
    assert m.my_deck_version


def test_handoff_also_patches_a_match_already_in_flight():
    """回填跑完时监听器可能**已经建好**那场对局——补挂映射要把它一起补上。

    这是真实时序：面板 19:19:16 重启，选牌在 19:19:08、开赛在 19:19:26，
    而回填要跑十几秒。所以补挂时 `_cur` 里往往已经有一场没有套牌名的对局。
    """
    filler = SessionBuilder(my_player_id=fx.ME)
    filler.feed(deck_event())
    learned = filler.course_decks

    watcher = SessionBuilder(my_player_id=fx.ME)
    for line in fx.bo1_match_lines():
        watcher.feed(line)                 # 对局已建好，但还没 close
    watcher.set_course_decks(learned)
    m = watcher.close().matches[0]
    assert m.my_deck_tag == "Example", "已经建好的对局没被补上套牌名"


def test_handoff_does_not_override_a_known_deck():
    """监听器自己已经知道套牌时，不许被回填的旧映射覆盖。"""
    filler = SessionBuilder(my_player_id=fx.ME)
    filler.feed(deck_event(name="回填学到的旧名字"))
    learned = filler.course_decks

    watcher = SessionBuilder(my_player_id=fx.ME)
    watcher.feed(deck_event(name="监听器自己的"))
    watcher.set_course_decks(learned)
    for line in fx.bo1_match_lines():
        watcher.feed(line)
    assert watcher.close().matches[0].my_deck_tag == "监听器自己的"


def test_handoff_is_a_noop_without_mapping():
    """回填没学到东西时（比如首次运行）不能崩，也不能乱改状态。"""
    watcher = SessionBuilder(my_player_id=fx.ME)
    watcher.set_course_decks({})
    watcher.set_course_decks(None)
    for line in fx.bo1_match_lines():
        watcher.feed(line)
    assert watcher.close().matches[0].my_deck_tag is None
