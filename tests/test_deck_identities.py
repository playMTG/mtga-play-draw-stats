# -*- coding: utf-8 -*-
"""套牌筛选的二级联动（V1 续做）。

首页套牌下拉按「名字」分组，而本机 314 个名字里有 39 个被多个 deck_id 共用。
二级下拉让用户指定「哪一次 draft / 哪一副同名套牌」，再用 `deck_id` 收窄。

两条必须守住的口径：
1. 两级是**求交**（名字 + 身份），不是替换——否则「脂牙」下两副的场数加不回 84；
2. 身份名**不带场数**——它是全库口径，而场数按当前筛选算，混在一起会出现
   「下拉写 192 场、选完只有 47 场」的矛盾（改过名的套牌就是这样）。
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import stats, store
from app.deck_names import identity_labels, limited_labels
from app.insights import daily_report


def _ts(y, mo, d, h=12, mi=0):
    return int(datetime(y, mo, d, h, mi).timestamp() * 1000)


def _db(tmp_path):
    return store.connect(tmp_path / "t.db")


def _insert(db, mid, *, event, tag, deck_id, ts, mode="BO1", result="win"):
    # 每个 deck_id 独立构筑版本：R6 的身份图会把共享任一可靠值的记录连成一个身份。
    db.execute(
        """INSERT INTO matches(match_id, source, event_id, start_time, my_seat,
               play_draw, my_result, my_deck_tag, my_deck_id, my_deck_version, match_mode)
           VALUES(?, 'log', ?, ?, 1, 'play', ?, ?, ?, ?, ?)""",
        (mid, event, ts, result, tag, deck_id, f"ver-{deck_id}", mode),
    )


def _duplicate_tag(db):
    """同一个名字「脂牙」下两副套牌，其中一副改过名（历史名字「脂牙 BO1」）。"""
    _insert(db, "a1", event="Ladder", tag="脂牙", deck_id="d1", ts=_ts(2024, 5, 1))
    _insert(db, "a2", event="Ladder", tag="脂牙", deck_id="d1", ts=_ts(2024, 5, 2))
    _insert(db, "a3", event="Ladder", tag="脂牙", deck_id="d1", ts=_ts(2024, 5, 3))
    # d1 后来改名成「脂牙 BO1」，这两场不该算进「脂牙」这个名字
    _insert(db, "a4", event="Ladder", tag="脂牙 BO1", deck_id="d1", ts=_ts(2024, 5, 4))
    _insert(db, "a5", event="Ladder", tag="脂牙 BO1", deck_id="d1", ts=_ts(2024, 5, 5))
    _insert(db, "b1", event="Ladder", tag="脂牙", deck_id="d2", ts=_ts(2024, 6, 1))
    _insert(db, "b2", event="Ladder", tag="脂牙", deck_id="d2", ts=_ts(2024, 6, 2))
    db.commit()


def test_identity_labels_covers_limited_and_named_duplicates(tmp_path):
    """二级下拉必须能区分**所有**重名身份，而不只是限制赛那一类。"""
    db = _db(tmp_path)
    _insert(db, "a1", event="PremierDraft_DMU_20220901", tag="轮抽套牌", deck_id="L1",
            ts=_ts(2024, 10, 5, 21, 3))
    _insert(db, "b1", event="QuickDraft_DSK_20241004", tag="轮抽套牌", deck_id="L2",
            ts=_ts(2024, 11, 7, 9, 30))
    _insert(db, "c1", event="Ladder", tag="红黑牺牲", deck_id="U1", ts=_ts(2024, 5, 1))
    _insert(db, "c2", event="Ladder", tag="红黑牺牲", deck_id="U2", ts=_ts(2024, 5, 2))
    db.commit()
    labels = identity_labels(db)
    # 限制赛沿用与明细／详情标题一致的名字
    assert labels["L1"] == "轮抓 · 2024-10-05 21:03"
    assert labels["L2"] == "轮抓 · 2024-11-07 09:30"
    # 用户自起的重名：二级下拉也要能区分，但没有可复用的派生名，用「首次对局时间 起」
    assert labels["U1"] == "2024-05-01 12:00 起"
    assert labels["U2"] == "2024-05-02 12:00 起"
    # 明细那边仍然只改限制赛那一类（用户自起的名字保持原样）
    assert set(limited_labels(db)) == {"L1", "L2"}
    db.close()


def test_identity_labels_excludes_unique_names(tmp_path):
    """名字唯一就不需要第二级——不该出现在 identity_labels 里。"""
    db = _db(tmp_path)
    _insert(db, "a1", event="Ladder", tag="W3", deck_id="solo", ts=_ts(2024, 5, 1))
    db.commit()
    assert identity_labels(db) == {}
    db.close()


def test_identity_labels_has_no_match_count(tmp_path):
    """身份名里不能带场数：全库口径的 192 会与筛选后的 47 打架。"""
    db = _db(tmp_path)
    _duplicate_tag(db)
    labels = identity_labels(db)
    assert "场" not in labels["d1"], labels["d1"]
    assert labels["d1"].endswith("起")
    db.close()


def test_deck_identities_splits_and_sums(tmp_path):
    """二级下拉把名字拆成各身份，且各项场数加总等于该名字的场数。"""
    db = _db(tmp_path)
    _duplicate_tag(db)
    r = stats.deck_identities(db, "脂牙")
    assert r["deck"] == "脂牙"
    assert len(r["items"]) == 2
    assert r["total"] == 5  # 3 + 2，不含改名为「脂牙 BO1」的那两场
    assert sum(i["n"] for i in r["items"]) == r["total"]
    by_id = {i["value"]: i for i in r["items"]}
    assert by_id["d1"]["n"] == 3
    assert by_id["d2"]["n"] == 2
    assert by_id["d1"]["label"] == "2024-05-01 12:00 起"
    # 场数降序
    assert [i["value"] for i in r["items"]] == ["d1", "d2"]
    db.close()


def test_deck_identities_respects_upstream_narrowing(tmp_path):
    """上游筛选（这里是模式）要一并作用于身份列表。"""
    db = _db(tmp_path)
    _duplicate_tag(db)
    _insert(db, "c1", event="Ladder", tag="脂牙", deck_id="d2", ts=_ts(2024, 6, 3), mode="BO3")
    db.commit()
    assert stats.deck_identities(db, "脂牙")["total"] == 6
    bo3 = stats.deck_identities(db, "脂牙", mode="BO3")
    assert [i["value"] for i in bo3["items"]] == ["d2"]
    assert bo3["total"] == 1
    db.close()


def test_filter_options_decks_carry_identity_count(tmp_path):
    """前端靠 ids>1 判断要不要显示第二级，所以 filters 必须给出这个数。"""
    db = _db(tmp_path)
    _duplicate_tag(db)
    _insert(db, "s1", event="Ladder", tag="W3", deck_id="solo", ts=_ts(2024, 7, 1))
    db.commit()
    decks = {d["value"]: d for d in stats.filter_options(db)["decks"]}
    assert decks["脂牙"]["ids"] == 2
    assert decks["脂牙"]["n"] == 5
    assert decks["W3"]["ids"] == 1
    db.close()


def test_deck_id_narrows_within_the_name_not_replacing_it(tmp_path):
    """`deck` 与 `deck_id` 求交：选「脂牙 → d1」只该给 3 场，不是 d1 全部的 5 场。"""
    db = _db(tmp_path)
    _duplicate_tag(db)
    assert stats.match_list(db, deck="脂牙")["total"] == 5
    assert stats.match_list(db, deck="脂牙", deck_id="d1")["total"] == 3
    # 不给 deck 时 deck_id 单独生效（该身份的全部 5 场，含改名前的那两场）
    assert stats.match_list(db, deck_id="d1")["total"] == 5
    # 其他口径也走同一套筛选（总览／导出／日报都吃 deck_id）
    assert stats.overview(db, deck="脂牙", deck_id="d1")["total"]["n"] == 3
    assert len(stats.export_rows(db, "matches", deck="脂牙", deck_id="d1")[1]) == 3
    assert daily_report(db, "2024-05-01", deck="脂牙", deck_id="d1")["summary"]["n"] == 1
    db.close()
