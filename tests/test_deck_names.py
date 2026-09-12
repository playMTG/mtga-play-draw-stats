# -*- coding: utf-8 -*-
"""限制赛临时牌组的可区分显示名（V1）。

判据是「限制赛 + 名字被多个 deck_id 共用」，**不是**硬编码「轮抽套牌」这些字符串
（客户端本地化会变）。最要紧的一条是**不误伤用户自己起的重名套牌**——本机实测
39 个「不具唯一性」的名字里绝大多数是用户自起的（"红黑牺牲"、"脂牙"、"大綠"）。
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import stats, store
from app.deck_detail import deck_detail
from app.deck_names import label_for, limited_labels


def _ts(y, mo, d, h=12, mi=0):
    return int(datetime(y, mo, d, h, mi).timestamp() * 1000)


def _db(tmp_path):
    return store.connect(tmp_path / "t.db")


def _insert(db, mid, *, event, tag, deck_id, ts, result="win", ver=None):
    # 默认给每个 deck_id 一个独立的构筑版本：R6 的身份图会把「共享任一可靠值」
    # 的记录连成一个身份，测试里若让两个 deck 共用指纹，它们就不再是两个身份了。
    db.execute(
        """INSERT INTO matches(match_id, source, event_id, start_time, my_seat,
               play_draw, my_result, my_deck_tag, my_deck_id, my_deck_version, match_mode)
           VALUES(?, 'log', ?, ?, 1, 'play', ?, ?, ?, ?, 'BO1')""",
        (mid, event, ts, result, tag, deck_id, ver or f"ver-{deck_id}"),
    )


def test_limited_placeholder_gets_distinguishable_label(tmp_path):
    """两次 draft 共用「轮抽套牌」→ 各自拿到「轮抓 · 首次对局时间」，且互不相同。"""
    db = _db(tmp_path)
    _insert(db, "a1", event="PremierDraft_DMU_20220901", tag="轮抽套牌", deck_id="d1",
            ts=_ts(2024, 10, 5, 21, 3))
    _insert(db, "a2", event="PremierDraft_DMU_20220901", tag="轮抽套牌", deck_id="d1",
            ts=_ts(2024, 10, 5, 22, 40))
    _insert(db, "b1", event="QuickDraft_DSK_20241004", tag="轮抽套牌", deck_id="d2",
            ts=_ts(2024, 11, 7, 9, 30))
    db.commit()
    labels = limited_labels(db)
    # 首战时间取该 deck 最早一场（a1），不是最后一场
    assert labels["d1"] == "轮抓 · 2024-10-05 21:03"
    assert labels["d2"] == "轮抓 · 2024-11-07 09:30"
    db.close()


def test_user_named_duplicate_keeps_its_name(tmp_path):
    """用户自己起的重名套牌（非限制赛）必须保持原名——这是本次最要紧的不误伤条件。"""
    db = _db(tmp_path)
    _insert(db, "x1", event="Ladder", tag="红黑牺牲", deck_id="u1", ts=_ts(2024, 5, 1))
    _insert(db, "x2", event="Ladder", tag="红黑牺牲", deck_id="u2", ts=_ts(2024, 5, 2))
    db.commit()
    labels = limited_labels(db)
    assert labels == {}
    assert label_for("红黑牺牲", "u1", labels) == "红黑牺牲"
    assert label_for("红黑牺牲", "u2", labels) == "红黑牺牲"
    db.close()


def test_limited_deck_with_unique_name_keeps_name(tmp_path):
    """限制赛但名字只对应一个 deck_id → 没有歧义，不改名。"""
    db = _db(tmp_path)
    _insert(db, "s1", event="Sealed_DMU_20220901", tag="我的现开", deck_id="solo",
            ts=_ts(2024, 3, 2, 10, 5))
    db.commit()
    labels = limited_labels(db)
    assert labels == {}
    assert label_for("我的现开", "solo", labels) == "我的现开"
    db.close()


def test_sealed_label_uses_sealed_kind(tmp_path):
    db = _db(tmp_path)
    _insert(db, "s1", event="Sealed_DMU_20220901", tag="现开赛", deck_id="s1",
            ts=_ts(2024, 3, 2, 10, 5))
    _insert(db, "s2", event="Sealed_SNC_20220428", tag="现开赛", deck_id="s2",
            ts=_ts(2024, 4, 2, 10, 5))
    db.commit()
    labels = limited_labels(db)
    assert labels["s1"] == "现开 · 2024-03-02 10:05"
    assert labels["s2"] == "现开 · 2024-04-02 10:05"
    db.close()


def test_mixed_tag_only_limited_deck_is_derived(tmp_path):
    """同一个 tag 既被限制赛又被构筑套牌用（本机 "?" 就是这样）：只改限制赛那个。"""
    db = _db(tmp_path)
    _insert(db, "m1", event="QuickDraft_DSK_20241004", tag="?", deck_id="lim",
            ts=_ts(2024, 6, 1))
    _insert(db, "m2", event="Ladder", tag="?", deck_id="con", ts=_ts(2024, 6, 2))
    db.commit()
    labels = limited_labels(db)
    assert "lim" in labels
    assert "con" not in labels
    db.close()


def test_deck_detail_uses_derived_title_and_drops_noise(tmp_path):
    """详情页：标题用派生名，且不再报「另有 N 场同名记录未合并」。

    那些记录本来就是别的 draft，不是「未合并的同名套牌」——实测本机这条提示
    会显示 1156 场，对限制赛纯属噪音。
    """
    db = _db(tmp_path)
    _insert(db, "a1", event="PremierDraft_DMU_20220901", tag="轮抽套牌", deck_id="d1",
            ts=_ts(2024, 10, 5, 21, 3))
    _insert(db, "b1", event="QuickDraft_DSK_20241004", tag="轮抽套牌", deck_id="d2",
            ts=_ts(2024, 11, 7, 9, 30))
    db.commit()
    detail = deck_detail(db, deck_id="d1", scope="all")
    assert detail["title"] == "轮抓 · 2024-10-05 21:03"
    assert detail["identity"]["same_name_unlinked"] == 0
    assert "轮抽套牌" in detail["identity"]["note"]  # 原名仍在说明里留痕
    assert detail["records"][0]["my_deck_label"] == "轮抓 · 2024-10-05 21:03"
    db.close()


def test_deck_detail_keeps_noise_for_user_named_duplicate(tmp_path):
    """对照：用户自起的重名套牌仍保留原名与「未合并」提示（行为不变）。"""
    db = _db(tmp_path)
    _insert(db, "x1", event="Ladder", tag="红黑牺牲", deck_id="u1", ts=_ts(2024, 5, 1))
    _insert(db, "x2", event="Ladder", tag="红黑牺牲", deck_id="u2", ts=_ts(2024, 5, 2))
    db.commit()
    detail = deck_detail(db, deck_id="u1", scope="all")
    assert detail["title"] == "红黑牺牲"
    assert detail["identity"]["same_name_unlinked"] == 1
    db.close()


def test_match_list_exposes_deck_label(tmp_path):
    db = _db(tmp_path)
    _insert(db, "a1", event="PremierDraft_DMU_20220901", tag="轮抽套牌", deck_id="d1",
            ts=_ts(2024, 10, 5, 21, 3))
    _insert(db, "b1", event="QuickDraft_DSK_20241004", tag="轮抽套牌", deck_id="d2",
            ts=_ts(2024, 11, 7, 9, 30))
    db.commit()
    res = stats.match_list(db, deck="轮抽套牌", limit=10)
    assert {r["my_deck_label"] for r in res["rows"]} == {
        "轮抓 · 2024-10-05 21:03", "轮抓 · 2024-11-07 09:30"}
    # 原始 tag 仍在，前端回退与既有契约不受影响
    assert {r["my_deck_tag"] for r in res["rows"]} == {"轮抽套牌"}
    db.close()
