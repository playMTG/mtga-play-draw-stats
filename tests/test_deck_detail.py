from datetime import datetime, timedelta

import pytest

from app import main, store
from app.deck_detail import UNKNOWN_VERSION, deck_detail


def add(conn, match_id, day, *, name, deck_id=None, version=None,
        pd="play", result="win", source="log", is_bot=0):
    ts = int(datetime.combine(day, datetime.min.time()).timestamp() * 1000)
    conn.execute(
        """INSERT INTO matches(match_id,source,event_id,start_time,my_deck_tag,
                   my_deck_id,my_deck_version,play_draw,my_result,my_seat,is_bot)
           VALUES(?,?,'Play_Brawl_Historic',?,?,?,?,?,?,1,?)""",
        (match_id, source, ts, name, deck_id, version, pd, result, is_bot),
    )


@pytest.fixture
def db(tmp_path):
    conn = store.connect(tmp_path / "deck.db")
    yield conn
    conn.close()


def test_identity_connects_ids_and_versions_without_merging_same_name(db):
    today = datetime.now().date()
    add(db, "anchor", today, name="旧名称", deck_id="local-1", version="v1")
    add(db, "renamed", today - timedelta(days=1), name="新名称",
        deck_id="local-1", version="v2", pd="draw", result="loss")
    add(db, "bridge", today - timedelta(days=2), name="云端名称",
        deck_id="cloud-9", version="v1", source="untapped", result="loss")
    add(db, "cloud-new", today - timedelta(days=6), name="云端名称",
        deck_id="cloud-9", version="v3", source="untapped", pd="draw")
    add(db, "unknown-version", today, name="新名称", deck_id="local-1")
    add(db, "unrelated", today, name="旧名称", deck_id="other", version="vx")
    add(db, "name-only", today, name="旧名称")
    add(db, "bot", today, name="新名称", deck_id="local-1", version="v1", is_bot=1)
    db.commit()

    result = deck_detail(db, deck="旧名称", deck_id="local-1",
                         deck_version="v1", scope="all", today=today)
    assert result["summary"]["n"] == 5
    assert result["identity"]["deck_ids"] == ["cloud-9", "local-1"]
    assert result["identity"]["aliases"] == ["云端名称", "新名称", "旧名称"]
    assert result["identity"]["same_name_unlinked"] == 2
    assert len(result["versions"]) == 3
    assert result["unknown_version"] == 1
    assert {row["match_id"] for row in result["records"]} == {
        "anchor", "renamed", "bridge", "cloud-new", "unknown-version"
    }
    assert "同名记录" in result["identity"]["note"]

    v1 = deck_detail(db, deck_id="local-1", deck_version="v1",
                     scope="all", version="v1", today=today)
    assert v1["summary"]["n"] == 2
    assert v1["summary"]["win_rate"]["wr"] == 50
    assert v1["version_count_in_scope"] == 1

    unknown = deck_detail(db, deck_id="local-1", deck_version="v1",
                          scope="all", version=UNKNOWN_VERSION, today=today)
    assert [row["match_id"] for row in unknown["records"]] == ["unknown-version"]


def test_scopes_and_name_fallback(db):
    today = datetime.now().date()
    for i in range(25):
        add(db, f"m{i}", today - timedelta(days=i), name="范围套牌",
            deck_id="deck", version="one", pd="draw" if i % 2 else "play")
    add(db, "legacy-a", today, name="旧资料")
    add(db, "legacy-b", today - timedelta(days=1), name="旧资料", pd="draw")
    db.commit()

    anchor = dict(deck="范围套牌", deck_id="deck", deck_version="one", today=today)
    assert deck_detail(db, scope="today", **anchor)["summary"]["n"] == 1
    assert deck_detail(db, scope="yesterday", **anchor)["summary"]["n"] == 1
    assert deck_detail(db, scope="last7", **anchor)["summary"]["n"] == 7
    assert deck_detail(db, scope="last20", **anchor)["summary"]["n"] == 20
    assert deck_detail(db, scope="all", **anchor)["summary"]["n"] == 25

    fallback = deck_detail(db, deck="旧资料", scope="all", today=today)
    assert fallback["summary"]["n"] == 2
    assert fallback["identity"]["basis"] == "name_fallback"
    assert "暂按套牌名称汇总" in fallback["identity"]["note"]


def test_name_only_request_selects_latest_reliable_identity(db):
    today = datetime.now().date()
    add(db, "old", today - timedelta(days=2), name="同名", deck_id="old-id", version="old-v")
    add(db, "new", today, name="同名", deck_id="new-id", version="new-v")
    db.commit()
    result = deck_detail(db, deck="同名", scope="all", today=today)
    assert [row["match_id"] for row in result["records"]] == ["new"]
    assert result["identity"]["same_name_unlinked"] == 1
    assert "最近使用的可靠身份" in result["identity"]["note"]


def test_opponent_commanders_use_eligible_known_denominator_and_drilldown(db, tmp_path):
    today = datetime.now().date()
    db.execute("ATTACH DATABASE ':memory:' AS cards_db")
    db.execute("CREATE TABLE cards_db.cards(grp_id TEXT, name TEXT, name_zh TEXT)")
    db.executemany("INSERT INTO cards_db.cards VALUES(?,?,?)", [
        ("100", "First Commander", "第一主将"),
        ("200", "Partner Commander", "伙伴主将"),
        ("300", "Other Printing", "第一主将"),
    ])
    add(db, "m1", today, name="主将测试", deck_id="deck", version="v1",
        pd="play", result="win")
    add(db, "m2", today, name="主将测试", deck_id="deck", version="v1",
        pd="draw", result="loss")
    add(db, "m3", today, name="主将测试", deck_id="deck", version="v1",
        pd="play", result="win")
    add(db, "missing", today, name="主将测试", deck_id="deck", version="v1")
    add(db, "same-name", today, name="主将测试", deck_id="deck", version="v1")
    add(db, "draft", today, name="主将测试", deck_id="deck", version="v1")
    db.execute("UPDATE matches SET event_id='PremierDraft_TEST' WHERE match_id='draft'")
    db.executemany("INSERT INTO commanders(match_id,seat,grp_id) VALUES(?,?,?)", [
        ("m1", 2, "100"), ("m1", 2, "100"), ("m1", 2, "200"),
        ("m1", 1, "200"),  # 我方同名卡不计入对手
        ("m2", 2, "100"), ("m3", 2, "200"),
        ("same-name", 2, "300"),
        ("draft", 2, "100"),  # 非争锋的 command zone 资料不适用
    ])
    db.commit()

    result = deck_detail(db, deck_id="deck", deck_version="v1", scope="all",
                         today=today, root=tmp_path)
    commanders = result["opponent_commanders"]
    assert commanders == {**commanders, "eligible": 5, "known": 4, "missing": 1,
                          "not_applicable": 1, "distinct": 3,
                          "multi_commander_matches": 1}
    by_id = {row["key"]: row for row in commanders["rows"]}
    assert by_id["100"]["name"] == "第一主将"
    assert by_id["100"]["n"] == 2  # 同一场重复 grpId 只计一次
    assert by_id["100"]["share_known"] == 50
    assert by_id["100"]["wins"] == 1 and by_id["100"]["losses"] == 1
    assert by_id["100"]["play"] == 1 and by_id["100"]["draw"] == 1
    assert by_id["100"]["on_play"]["wr"] == 100
    assert by_id["100"]["on_draw"]["wr"] == 0
    assert by_id["300"]["name"] == by_id["100"]["name"]
    assert sum(row["n"] for row in commanders["rows"]) == 5 > commanders["known"]

    detail = deck_detail(db, deck_id="deck", deck_version="v1", scope="all",
                         today=today, root=tmp_path, opponent_commander="100")
    assert detail["selected_commander"]["name"] == "第一主将"
    assert detail["records_total"] == 2 and not detail["records_truncated"]
    assert {row["match_id"] for row in detail["records"]} == {"m1", "m2"}
    assert {card["key"] for card in next(row for row in detail["records"]
                                          if row["match_id"] == "m1")["opponent_cards"]} == {"100", "200"}
    with pytest.raises(ValueError, match="当前范围"):
        deck_detail(db, deck_id="deck", deck_version="v1", scope="all",
                    today=today, root=tmp_path, opponent_commander="999")


def test_deck_detail_api_validation(db, monkeypatch):
    from fastapi.testclient import TestClient

    today = datetime.now().date()
    add(db, "api", today, name="接口套牌", deck_id="api-id", version="api-v")
    db.commit()
    monkeypatch.setattr(main, "_conn", db)
    client = TestClient(main.app)
    response = client.get("/api/deck_detail", params={
        "deck": "接口套牌", "deck_id": "api-id", "deck_version": "api-v",
        "scope": "today",
    })
    assert response.status_code == 200
    assert response.json()["summary"]["n"] == 1
    assert client.get("/api/deck_detail").status_code == 422
    assert client.get("/api/deck_detail", params={
        "deck_id": "api-id", "mode": "不是模式",
    }).status_code == 422
    assert client.get("/api/overview", params={"mode": "不是模式"}).status_code == 422
    assert client.get("/api/deck_detail?deck=接口套牌&scope=bad").status_code == 422
    client.close()


def test_streak_observation_can_return_every_evidence_record(db):
    today = datetime.now().date()
    for i in range(8):
        add(db, f"draw-{i}", today, name="连庄套牌", deck_id="streak-id",
            version="streak-v", pd="draw", result="loss")
        db.execute("UPDATE matches SET start_time=start_time+? WHERE match_id=?",
                   (i * 60_000, f"draw-{i}"))
    db.commit()

    result = deck_detail(db, deck_id="streak-id", deck_version="streak-v",
                         scope="today", today=today)
    item = result["observations"]["items"][0]
    assert item["key"] == "streak-draw"
    assert item["headline"] == "连续 8 把后手：离谱级连庄"

    evidence = deck_detail(db, deck_id="streak-id", deck_version="streak-v",
                           scope="today", today=today, observation="streak-draw")
    assert evidence["selected_observation"]["n"] == 8
    assert evidence["records_total"] == 8
    assert not evidence["records_truncated"]
    assert [row["match_id"] for row in evidence["records"]] == [
        f"draw-{i}" for i in reversed(range(8))
    ]
    with pytest.raises(ValueError, match="当前范围没有这条观察"):
        deck_detail(db, deck_id="streak-id", deck_version="streak-v",
                    scope="today", today=today, observation="missing")
