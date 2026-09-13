# -*- coding: utf-8 -*-
"""首页「最近在打的套牌」入口（VISION V3 收尾）。

这个区块的职责是**当套牌旅程的选择器**：一行一个 deck 身份，点进去就是已有的
详情页。因此有三条口径必须守住，否则入口会退化成「点哪个都一样」：

1. 按 **deck_id** 聚合成行，不按名字——本机「轮抽套牌」一个名字压着 188 次 draft，
   按名字聚合只会得到一行 1288 场，挑不出任何一副；
2. 名字取「限制赛派生名优先，否则最近一次的 tag」——与详情页标题同一口径，
   点进去不会「换个名字」；
3. 两行最终同名时补「首次对局时间 起」——「现开赛」×5 摆在一起等于没法挑。

另守 `focus=True` 的赛制收窄（V3「信息密度随最近主赛制调整」落在入口区的那一半）。
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import stats, store


def _ts(y, mo, d, h=12, mi=0):
    return int(datetime(y, mo, d, h, mi).timestamp() * 1000)


def _ago(days, h=12, mi=0):
    """相对现在的时刻。

    `format_focus` 只看近 30 天，写死 2024 年的日期会掉出窗口、主赛制变成 unknown，
    赛制收窄那条测试就会空转通过。
    """
    base = datetime.now() - timedelta(days=days)
    return int(base.replace(hour=h, minute=mi, second=0, microsecond=0).timestamp() * 1000)


def _db(tmp_path):
    return store.connect(tmp_path / "t.db")


def _insert(db, mid, *, event, tag, deck_id, ts, mode="BO1", result="win",
            play_draw="play", seat=1):
    # 每个 deck_id 独立构筑版本：身份图会把共享任一可靠值的记录连成一个身份。
    db.execute(
        """INSERT INTO matches(match_id, source, event_id, start_time, my_seat,
               play_draw, my_result, my_deck_tag, my_deck_id, my_deck_version, match_mode)
           VALUES(?, 'log', ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (mid, event, ts, seat, play_draw, result, tag, deck_id,
         f"ver-{deck_id}" if deck_id else "", mode),
    )


# ---------- 1. 按 deck_id 成行 ----------

def test_one_row_per_deck_id_merging_renamed_tags(tmp_path):
    """同一副套牌改过名（一个 did 挂两个 tag）必须并成一行，不是两行同一目的地。

    本机有 20 个这样的 did（如「脂牙」+「脂牙 BO1」192 场）。按 (tag, did) 聚合会
    拆成两行，而两行点进去是同一个详情页——正是入口最不该有的样子。
    """
    db = _db(tmp_path)
    _insert(db, "a1", event="Ladder", tag="脂牙", deck_id="d1", ts=_ts(2024, 5, 1))
    _insert(db, "a2", event="Ladder", tag="脂牙", deck_id="d1", ts=_ts(2024, 5, 2))
    _insert(db, "a3", event="Ladder", tag="脂牙 BO1", deck_id="d1", ts=_ts(2024, 5, 9))
    db.commit()
    r = stats.recent_decks(db)
    assert r["total"] == 1
    item = r["items"][0]
    assert item["deck_id"] == "d1"
    assert item["n"] == 3, "改名前后都是同一副牌，场数要加在一起"
    assert item["label"] == "脂牙 BO1", "名字取最近一次对局用的那个（与详情页标题同规则）"
    db.close()


def test_name_only_rows_are_kept_separately(tmp_path):
    """只有名字、没有 deck_id 的记录仍要成行（按名字点进去），不能并成一坨。"""
    db = _db(tmp_path)
    _insert(db, "a1", event="Ladder", tag="W3", deck_id="", ts=_ts(2024, 5, 1))
    _insert(db, "a2", event="Ladder", tag="W4", deck_id="", ts=_ts(2024, 5, 2))
    db.commit()
    r = stats.recent_decks(db)
    assert sorted(i["label"] for i in r["items"]) == ["W3", "W4"]
    assert all(i["deck_id"] == "" for i in r["items"])
    db.close()


# ---------- 2. 限制赛每次 draft 各自成行 ----------

def test_limited_drafts_split_and_get_derived_names(tmp_path):
    """两次 draft 同名「轮抽套牌」但 did 不同 → 两行，且名字是可区分的派生名。"""
    db = _db(tmp_path)
    _insert(db, "a1", event="PremierDraft_DMU_20220901", tag="轮抽套牌", deck_id="L1",
            ts=_ts(2024, 10, 5, 21, 3))
    _insert(db, "a2", event="PremierDraft_DMU_20220901", tag="轮抽套牌", deck_id="L1",
            ts=_ts(2024, 10, 5, 21, 20))
    _insert(db, "b1", event="QuickDraft_DSK_20241004", tag="轮抽套牌", deck_id="L2",
            ts=_ts(2024, 11, 7, 9, 30))
    db.commit()
    r = stats.recent_decks(db)
    assert r["total"] == 2
    labels = {i["deck_id"]: i["label"] for i in r["items"]}
    assert labels["L1"] == "轮抓 · 2024-10-05 21:03"
    assert labels["L2"] == "轮抓 · 2024-11-07 09:30"
    assert len(set(labels.values())) == 2, "两个身份必须能被区分开"
    db.close()


# ---------- 3. 撞名补「首次对局时间 起」 ----------

def test_duplicate_labels_get_first_play_suffix(tmp_path):
    """名字重复且拿不到派生名时（本机「现开赛」×5）补时间，否则五行同名没法挑。

    用特别活动赛事构造：`Yargle_Day_*` 的 event_id 不含 Draft/Sealed，
    `limited_labels` 的 `_is_limited` 认不出来，于是回落原始名——正是本机实况。
    """
    db = _db(tmp_path)
    _insert(db, "a1", event="Yargle_Day_20260903", tag="现开赛", deck_id="y1",
            ts=_ts(2026, 9, 4, 19, 19))
    _insert(db, "b1", event="Yargle_Day_20260903", tag="现开赛", deck_id="y2",
            ts=_ts(2026, 9, 4, 22, 43))
    db.commit()
    r = stats.recent_decks(db)
    labels = {i["deck_id"]: i["label"] for i in r["items"]}
    assert labels["y1"] == "现开赛 · 2026-09-04 19:19 起"
    assert labels["y2"] == "现开赛 · 2026-09-04 22:43 起"
    db.close()


def test_unique_name_gets_no_suffix(tmp_path):
    """名字唯一就不加尾巴——用户自己的套牌名要保持原样，别塞解释性后缀。"""
    db = _db(tmp_path)
    _insert(db, "a1", event="Play_Brawl_Historic", tag="阿耶尼史迹争锋", deck_id="d1",
            ts=_ts(2024, 5, 1))
    db.commit()
    r = stats.recent_decks(db)
    assert r["items"][0]["label"] == "阿耶尼史迹争锋"
    db.close()


def test_same_minute_collision_falls_back_to_deck_id(tmp_path):
    """补完时间还撞（同一分钟开的两副）时用 deck_id 兜底，保证行行可分。"""
    db = _db(tmp_path)
    _insert(db, "a1", event="Yargle_Day_20260903", tag="现开赛", deck_id="aaaaaa11",
            ts=_ts(2026, 9, 4, 20, 0))
    _insert(db, "b1", event="Yargle_Day_20260903", tag="现开赛", deck_id="bbbbbb22",
            ts=_ts(2026, 9, 4, 20, 0))
    db.commit()
    labels = [i["label"] for i in stats.recent_decks(db)["items"]]
    assert len(set(labels)) == 2, labels
    assert any("aaaaaa" in lab for lab in labels)
    db.close()


# ---------- 4. 未记录套牌 ----------

def test_unlabeled_matches_are_counted_but_not_listed(tmp_path):
    """tag 与 id 都为空的对局点不进去，只计入 unlabeled 不占行。"""
    db = _db(tmp_path)
    _insert(db, "a1", event="Ladder", tag="W3", deck_id="d1", ts=_ts(2024, 5, 1))
    _insert(db, "u1", event="Ladder", tag="", deck_id="", ts=_ts(2024, 5, 2))
    _insert(db, "u2", event="Ladder", tag="", deck_id="", ts=_ts(2024, 5, 3))
    db.commit()
    r = stats.recent_decks(db)
    assert r["total"] == 1
    assert r["unlabeled"] == 2
    assert [i["label"] for i in r["items"]] == ["W3"]
    db.close()


# ---------- 5. 排序、场次、先后手 ----------

def test_ordered_by_last_match_and_limited_by_limit(tmp_path):
    db = _db(tmp_path)
    _insert(db, "a1", event="Ladder", tag="旧", deck_id="d1", ts=_ts(2024, 5, 1))
    _insert(db, "b1", event="Ladder", tag="新", deck_id="d2", ts=_ts(2024, 6, 1))
    _insert(db, "c1", event="Ladder", tag="中", deck_id="d3", ts=_ts(2024, 5, 15))
    db.commit()
    r = stats.recent_decks(db, limit=2)
    assert [i["label"] for i in r["items"]] == ["新", "中"]
    assert r["total"] == 3, "total 是收窄后的身份数，不受 limit 影响"
    assert r["limit"] == 2
    db.close()


def test_counts_and_play_draw(tmp_path):
    db = _db(tmp_path)
    _insert(db, "a1", event="Ladder", tag="W3", deck_id="d1", ts=_ts(2024, 5, 1),
            result="win", play_draw="play")
    _insert(db, "a2", event="Ladder", tag="W3", deck_id="d1", ts=_ts(2024, 5, 2),
            result="loss", play_draw="draw")
    _insert(db, "a3", event="Ladder", tag="W3", deck_id="d1", ts=_ts(2024, 5, 3),
            result="loss", play_draw="draw")
    db.commit()
    item = stats.recent_decks(db)["items"][0]
    assert item["n"] == 3 and item["wins"] == 1
    assert item["wr"] == 33.3
    assert (item["play"], item["draw"]) == (1, 2)
    assert item["last_time"] == _ts(2024, 5, 3)
    assert item["first_time"] == _ts(2024, 5, 1)
    db.close()


def test_abnormal_and_bot_respect_the_switches(tmp_path):
    db = _db(tmp_path)
    db.execute(
        """INSERT INTO matches(match_id, source, event_id, start_time, my_seat,
               play_draw, my_result, my_deck_tag, my_deck_id, is_abnormal)
           VALUES('a1','log','Ladder',?,1,'play','win','W3','d1',0)""", (_ts(2024, 5, 1),))
    db.execute(
        """INSERT INTO matches(match_id, source, event_id, start_time, my_seat,
               play_draw, my_result, my_deck_tag, my_deck_id, is_abnormal)
           VALUES('a2','log','Ladder',?,1,'play','win','异常牌','d2',1)""", (_ts(2024, 5, 2),))
    db.commit()
    assert stats.recent_decks(db)["total"] == 1
    assert stats.recent_decks(db, exclude_abnormal=False)["total"] == 2
    db.close()


# ---------- 6. 赛制收窄（focus） ----------

def test_focus_scopes_to_primary_format(tmp_path):
    """focus=True 且没显式筛选时，按近 30 天主赛制收窄。"""
    db = _db(tmp_path)
    # 近 30 天：4 场轮抽 + 1 场天梯 → 主赛制是轮抽
    for i in range(4):
        _insert(db, f"d{i}", event="QuickDraft_DSK_20241004", tag="轮抽套牌",
                deck_id=f"L{i}", ts=_ago(days=i + 1))
    _insert(db, "l1", event="Ladder", tag="红黑牺牲", deck_id="u1", ts=_ago(days=1, h=1))
    db.commit()
    r = stats.recent_decks(db, focus=True)
    assert r["focus"]["applied"] is True
    assert r["focus"]["primary"] == "轮抽"
    assert r["focus"]["window_days"] == 30
    assert r["total"] == 4, "天梯那副应被主赛制挡在外面"
    assert all(i["deck_id"].startswith("L") for i in r["items"])
    db.close()


def test_focus_off_lists_every_format(tmp_path):
    db = _db(tmp_path)
    _insert(db, "d1", event="QuickDraft_DSK_20241004", tag="轮抽套牌", deck_id="L1",
            ts=_ago(days=1))
    _insert(db, "l1", event="Ladder", tag="红黑牺牲", deck_id="u1", ts=_ago(days=2))
    db.commit()
    r = stats.recent_decks(db, focus=False)
    assert r["focus"]["applied"] is False
    assert r["total"] == 2
    db.close()


def test_focus_does_not_override_explicit_filters(tmp_path):
    """用户已经手选了赛制就以筛选为准，focus 不再插手。"""
    db = _db(tmp_path)
    _insert(db, "d1", event="QuickDraft_DSK_20241004", tag="轮抽套牌", deck_id="L1",
            ts=_ago(days=1))
    _insert(db, "l1", event="Ladder", tag="红黑牺牲", deck_id="u1", ts=_ago(days=2))
    db.commit()
    r = stats.recent_decks(db, focus=True, family="排位天梯")
    assert r["focus"]["applied"] is False
    assert [i["label"] for i in r["items"]] == ["红黑牺牲"]
    db.close()


def test_focus_unknown_when_window_is_empty(tmp_path):
    """近 30 天没数据时主赛制是 unknown，此时不能收窄（否则入口会空掉）。"""
    db = _db(tmp_path)
    _insert(db, "a1", event="Ladder", tag="红黑牺牲", deck_id="u1", ts=_ts(2024, 5, 1))
    db.commit()
    r = stats.recent_decks(db, focus=True)
    assert r["focus"]["applied"] is False
    assert r["focus"]["primary"] == "unknown"
    assert r["total"] == 1
    db.close()


# ---------- 7. 不受套牌筛选影响 ----------

def test_deck_filter_is_not_accepted(tmp_path):
    """这个区块是选择器：套牌筛选不该把入口压成一行。

    `recent_decks` 的签名里没有 `deck` / `deck_id`，API 层也不收——这条守住
    「以后有人顺手加上去」。
    """
    db = _db(tmp_path)
    _insert(db, "a1", event="Ladder", tag="W3", deck_id="d1", ts=_ts(2024, 5, 1))
    _insert(db, "b1", event="Ladder", tag="W4", deck_id="d2", ts=_ts(2024, 5, 2))
    db.commit()
    import inspect
    params = inspect.signature(stats.recent_decks).parameters
    assert "deck" not in params and "deck_id" not in params
    assert stats.recent_decks(db)["total"] == 2
    db.close()
