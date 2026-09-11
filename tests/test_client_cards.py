# -*- coding: utf-8 -*-
"""R12.1 卡名离线补齐：从本机 MTGA 客户端卡牌库读英文卡名。

客户端 `Raw_CardDatabase_*.mtga` 实为 SQLite（Cards + Localizations_enUS）。
这里用合成库覆盖：定位、读取、只补缺失、无库时优雅降级、来源文案、
以及「离线补齐不得饿死在线中文补全」这条回归。
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import cards_sync, client_cards, store

CARD_DB_NAME = "Raw_CardDatabase_deadbeef.mtga"


def _make_client_db(raw_dir: Path, rows: list[tuple[int, int, str]]) -> Path:
    """合成客户端卡牌库：rows = (GrpId, TitleId, enUS 名)。"""
    raw_dir.mkdir(parents=True, exist_ok=True)
    path = raw_dir / CARD_DB_NAME
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE Cards(GrpId INTEGER PRIMARY KEY, TitleId INTEGER)")
    conn.execute("CREATE TABLE Localizations_enUS(LocId INTEGER, Formatted INTEGER, Loc TEXT)")
    for grp_id, title_id, name in rows:
        conn.execute("INSERT INTO Cards VALUES(?,?)", (grp_id, title_id))
        conn.execute("INSERT INTO Localizations_enUS VALUES(?,1,?)", (title_id, name))
    conn.commit()
    conn.close()
    return path


def _stats_db(tmp_path: Path, grp_ids: list[str], existing_names: dict[str, str] | None = None):
    """stats 库（含 commanders）+ 卡名缓存，模拟面板的两个连接。"""
    stats_conn = store.connect(tmp_path / "stats.db")
    for i, gid in enumerate(grp_ids):
        mid = f"m{i}"
        stats_conn.execute(
            "INSERT INTO matches(match_id, source, event_id, my_seat, my_result) "
            "VALUES(?,?,?,1,'win')", (mid, "log", "Play_Brawl_Historic"))
        stats_conn.execute(
            "INSERT INTO commanders(match_id, seat, grp_id) VALUES(?,2,?)", (mid, gid))
    stats_conn.commit()
    cards_conn = cards_sync.cards_db_connect(tmp_path / "cards.db")
    for gid, name in (existing_names or {}).items():
        cards_conn.execute("INSERT INTO cards(grp_id, name) VALUES(?,?)", (gid, name))
    cards_conn.commit()
    return stats_conn, cards_conn


def test_find_and_read_client_database(tmp_path):
    raw = tmp_path / "Raw"
    _make_client_db(raw, [(14717, 100, "Captain Sisay"), (47485, 101, "Thalia")])
    found = client_cards.find_card_database([tmp_path / "nope", raw])
    assert found is not None and found.name == CARD_DB_NAME
    names = client_cards.read_names(found, ["14717", "47485", "99999"])
    assert names == {"14717": "Captain Sisay", "47485": "Thalia"}


def test_read_names_falls_back_when_formatted_missing(tmp_path):
    """Formatted=1 缺失时用同 TitleId 的其它行兜底，不返回空名。"""
    raw = tmp_path / "Raw"
    raw.mkdir()
    path = raw / CARD_DB_NAME
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE Cards(GrpId INTEGER PRIMARY KEY, TitleId INTEGER)")
    conn.execute("CREATE TABLE Localizations_enUS(LocId INTEGER, Formatted INTEGER, Loc TEXT)")
    conn.execute("INSERT INTO Cards VALUES(7, 70)")
    conn.execute("INSERT INTO Localizations_enUS VALUES(70, 2, 'Fallback Name')")
    conn.commit()
    conn.close()
    assert client_cards.read_names(path, ["7"]) == {"7": "Fallback Name"}


def test_connect_attaches_missing_cards_db(tmp_path):
    """回归：全新安装时卡名库还不存在，主连接也必须先挂载。

    否则启动后才被 cards_db_connect 创建的 cards 表，主连接永远看不到，
    补齐了卡名页面照样读不出来。
    """
    stats_db = tmp_path / "stats.db"
    cards_db = tmp_path / "cards.db"
    assert not cards_db.exists()
    conn = store.connect(stats_db, cards_db)
    assert cards_db.exists()                     # ATTACH 会建出文件
    writer = cards_sync.cards_db_connect(cards_db)
    writer.execute("INSERT INTO cards(grp_id, name) VALUES('1','Ajani')")
    writer.commit()
    # 已经打开的连接能看到后建的表与后写的数据
    assert conn.execute(
        "SELECT name FROM cards_db.cards WHERE grp_id='1'").fetchone()[0] == "Ajani"
    writer.close()
    conn.close()


def test_clean_client_name_strips_rich_text():
    """客户端卡名带 Unity 富文本：<nobr> 去掉，arena_a 图标还原成 A-。"""
    assert client_cards.clean_client_name("<nobr>Niv-Mizzet</nobr>, Parun") == "Niv-Mizzet, Parun"
    assert client_cards.clean_client_name(
        '<sprite="SpriteSheet_MiscIcons" name="arena_a">Acererak the Archlich'
    ) == "A-Acererak the Archlich"
    assert client_cards.clean_client_name("<i>Italic</i> Name") == "Italic Name"
    # 卡名本身的 & 不能被当成实体处理
    assert client_cards.clean_client_name("Minsc & Boo, Timeless Heroes") == \
        "Minsc & Boo, Timeless Heroes"
    assert client_cards.clean_client_name(None) == ""
    assert client_cards.clean_client_name("  Spaced   Name  ") == "Spaced Name"


def test_seed_fills_only_missing_and_keeps_existing(tmp_path):
    raw = tmp_path / "Raw"
    _make_client_db(raw, [(100, 1, "Client Name"), (200, 2, "Second Name")])
    stats_conn, cards_conn = _stats_db(
        tmp_path, ["100", "200"], existing_names={"100": "Scryfall Name"})
    r = client_cards.seed_cards_db(cards_conn, stats_conn, [raw])
    # 只有「卡名库还没有」的 grpId 会被处理：100 已有名称，不参与
    assert r["pending"] == 1 and r["seeded"] == 1 and r["unresolved"] == 0
    rows = {row["grp_id"]: row for row in cards_conn.execute(
        "SELECT grp_id, name, source FROM cards")}
    assert rows["100"]["name"] == "Scryfall Name"          # 已有名称不被覆盖
    assert rows["200"]["name"] == "Second Name"
    assert rows["200"]["source"] == "client"
    # 幂等：再跑一次没有新增
    assert client_cards.seed_cards_db(cards_conn, stats_conn, [raw])["seeded"] == 0


def test_seed_without_client_database_is_graceful(tmp_path):
    stats_conn, cards_conn = _stats_db(tmp_path, ["100"])
    r = client_cards.seed_cards_db(cards_conn, stats_conn, [tmp_path / "missing"])
    assert r["client_db"] is None and r["seeded"] == 0
    assert r["unresolved"] == 1 and r["pending"] == 1 and r["error"] is None


def test_name_coverage_and_source_label(tmp_path, monkeypatch):
    from app import card_names

    monkeypatch.setattr(card_names, "ROOT", tmp_path)
    raw = tmp_path / "Raw"
    _make_client_db(raw, [(100, 1, "Known Cmdr")])
    stats_conn, cards_conn = _stats_db(tmp_path, ["100", "555"])
    client_cards.seed_cards_db(cards_conn, stats_conn, [raw])
    # 卡名缓存挂到 stats 连接上（与面板一致）
    stats_conn.execute("ATTACH DATABASE ? AS cards_db",
                       (str(tmp_path / "cards.db"),))
    coverage = client_cards.name_coverage(stats_conn, tmp_path)
    assert coverage["total"] == 2 and coverage["named"] == 1
    assert coverage["missing"] == 1 and coverage["sample"] == ["555"]
    names = card_names.CardNames(stats_conn, "zh", tmp_path)
    assert names.get("100")["name"] == "Known Cmdr"
    # 完全没名字时不能再声称「英文回退」
    missing = names.get("555")
    assert missing["name"] == "grpId:555"
    assert "英文回退" not in missing["name_source"]
    assert "缺卡名" in missing["name_source"]


def test_source_label_distinguishes_unknown_origin(tmp_path, monkeypatch):
    """有英文名但没有中文译名时，来源文案要如实区分四档。

    历史遗留：早期导入的记录 source 为空（那时还没有 source 列）。这类行不能
    猜成 scryfall，也不能含糊地说「无中文译名」——直接标「来源未记录」。
    """
    from app import card_names

    monkeypatch.setattr(card_names, "ROOT", tmp_path)
    stats_conn, cards_conn = _stats_db(tmp_path, [])
    cards_conn.executemany(
        "INSERT INTO cards(grp_id, name, source) VALUES(?,?,?)",
        [
            ("1", "Client Card", "client"),
            ("2", "Scryfall Card", "scryfall"),
            ("3", "Legacy Card", None),
        ],
    )
    cards_conn.commit()
    stats_conn.execute("ATTACH DATABASE ? AS cards_db", (str(tmp_path / "cards.db"),))

    names = card_names.CardNames(stats_conn, "zh", tmp_path)
    assert "客户端卡名库" in names.get("1")["name_source"]
    assert "Scryfall" in names.get("2")["name_source"]
    assert "来源未记录" in names.get("3")["name_source"]
    # 三档都不该退回旧的含糊说法
    for gid in ("1", "2", "3"):
        assert "英文回退" not in names.get(gid)["name_source"]


def test_offline_seed_does_not_starve_online_zh(tmp_path, monkeypatch):
    """回归：英文名由离线补齐后，联网中文补全仍必须执行（旧逻辑会跳过）。"""
    raw = tmp_path / "Raw"
    _make_client_db(raw, [(100, 1, "Known Cmdr")])
    stats_conn, cards_conn = _stats_db(tmp_path, ["100"])
    client_cards.seed_cards_db(cards_conn, stats_conn, [raw])
    # 此时没有「缺英文名」的 grpId，pending 为空
    assert cards_sync.pending_grpids(stats_conn, cards_conn) == []

    calls: list[str] = []

    def fake_definitive(set_code, cn):
        calls.append(cn)
        return (True, "已知主将")

    monkeypatch.setattr(cards_sync, "_fetch_zh_definitive", fake_definitive)
    monkeypatch.setattr(cards_sync, "time", type("T", (), {"sleep": staticmethod(lambda *_: None)}))
    cards_conn.execute("UPDATE cards SET set_code='set', collector_number='1' WHERE grp_id='100'")
    cards_conn.commit()
    ok, total = cards_sync.sync_pending_cards(stats_conn, cards_conn, with_zh=True)
    assert (ok, total) == (0, 0)
    assert calls == ["1"]                                   # 中文仍然被查询
    assert cards_conn.execute(
        "SELECT name_zh FROM cards WHERE grp_id='100'").fetchone()[0] == "已知主将"


def test_backfill_zh_scope_and_no_retry(tmp_path, monkeypatch):
    stats_conn, cards_conn = _stats_db(tmp_path, ["100"])
    cards_conn.executemany(
        "INSERT INTO cards(grp_id, name, set_code, collector_number) VALUES(?,?,?,?)",
        [("100", "In Scope", "s", "1"), ("900", "Out Of Scope", "s", "9")])
    cards_conn.commit()
    seen: list[str] = []

    def fake_definitive(set_code, cn):
        seen.append(cn)
        return (True, None)      # 明确「无中文印刷」

    monkeypatch.setattr(cards_sync, "_fetch_zh_definitive", fake_definitive)
    monkeypatch.setattr(cards_sync, "time", type("T", (), {"sleep": staticmethod(lambda *_: None)}))
    assert cards_sync.backfill_zh(cards_conn, scope={"100"}) == 0
    assert seen == ["1"]                                     # 范围外的不查
    # 已查过（明确无译名）的卡不再重试
    assert cards_sync.backfill_zh(cards_conn, scope={"100"}) == 0
    assert seen == ["1"]


def test_backfill_zh_retries_when_network_fails(tmp_path, monkeypatch):
    stats_conn, cards_conn = _stats_db(tmp_path, ["100"])
    cards_conn.execute(
        "INSERT INTO cards(grp_id, name, set_code, collector_number) VALUES('100','X','s','1')")
    cards_conn.commit()

    def fake_definitive(set_code, cn):
        return (False, None)     # 网络失败：不是明确结论

    monkeypatch.setattr(cards_sync, "_fetch_zh_definitive", fake_definitive)
    monkeypatch.setattr(cards_sync, "time", type("T", (), {"sleep": staticmethod(lambda *_: None)}))
    assert cards_sync.backfill_zh(cards_conn, scope={"100"}) == 0
    assert cards_conn.execute(
        "SELECT zh_tried FROM cards WHERE grp_id='100'").fetchone()[0] == 0  # 保持可重试
