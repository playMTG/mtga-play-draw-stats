from datetime import datetime

from fastapi.testclient import TestClient

from app import main, stats, store
from app.deck_detail import deck_detail
from app.insights import daily_report


def _add(conn, match_id, event, *, tag=None, result="win", pd="play",
         deck="构筑测试", mode="BO1"):
    ts = int(datetime.now().timestamp() * 1000)
    conn.execute(
        """INSERT INTO matches(match_id,source,event_id,start_time,my_seat,
                   my_deck_tag,my_deck_id,my_deck_version,play_draw,my_result,
                   match_mode,opp_archetype_tag)
           VALUES(?, 'log', ?, ?, 1, ?, 'deck-types', 'version-types', ?, ?, ?, ?)""",
        (match_id, event, ts, deck, pd, result, mode, tag),
    )


def test_only_clear_non_commander_constructed_events_enter_coverage(tmp_path):
    conn = store.connect(tmp_path / "types.db")
    assert stats.is_constructed_opponent_event("Ladder")
    assert stats.is_constructed_opponent_event("Traditional_Explorer_Ladder")
    assert stats.is_constructed_opponent_event("Constructed_BestOf3")
    assert stats.is_constructed_opponent_event("MWM_FINConstructed_20250617")
    for event in ("Play_Brawl_Historic", "PremierDraft_TEST", "Sealed_TEST",
                  "MWM_Momir_20260908", "Unknown_Event", None):
        assert not stats.is_constructed_opponent_event(event)

    _add(conn, "aggro", "Ladder", tag="Aggro", result="win", pd="play")
    _add(conn, "control", "Traditional_Ladder", tag="Control", result="loss",
         pd="draw", mode="BO3")
    _add(conn, "unknown", "Constructed_BestOf3", mode="BO3")
    _add(conn, "brawl", "Play_Brawl_Historic", tag=None)
    _add(conn, "draft", "PremierDraft_TEST", tag=None)
    conn.commit()

    report = stats.opponent_type_stats(conn)
    assert (report["eligible"], report["known"], report["unknown"]) == (3, 2, 1)
    by_tag = {row["tag"]: row for row in report["rows"]}
    assert by_tag["Aggro"]["n"] == 1 and by_tag["Aggro"]["win_rate"]["wr"] == 100
    assert by_tag["Control"]["losses"] == 1
    assert stats.opponent_type_stats(conn, mode="BO3")["eligible"] == 2

    matches = {row["match_id"]: row for row in stats.match_list(
        conn, exclude_abnormal=False, exclude_bot=False)["rows"]}
    assert matches["aggro"]["opponent_type_eligible"]
    assert matches["aggro"]["opp_archetype_tag"] == "Aggro"
    assert not matches["brawl"]["opponent_type_eligible"]
    assert not matches["draft"]["opponent_type_eligible"]

    daily = daily_report(conn, datetime.now().date().isoformat())
    assert daily["opponent_types"] == {
        "known": 2, "total": 3, "unknown": 1,
        "rows": {"Aggro": 1, "Control": 1},
    }
    detail = deck_detail(conn, deck_id="deck-types", deck_version="version-types",
                         scope="all")
    detail_rows = {row["match_id"]: row for row in detail["records"]}
    assert detail_rows["control"]["opponent_type_eligible"]
    assert detail_rows["control"]["opp_archetype_tag"] == "Control"
    conn.close()


def test_constructed_type_can_be_set_changed_and_cleared_per_match(tmp_path, monkeypatch):
    conn = store.connect(tmp_path / "types-api.db")
    _add(conn, "target", "Ladder")
    _add(conn, "other", "Ladder")
    _add(conn, "draft", "PremierDraft_TEST")
    conn.commit()
    monkeypatch.setattr(main, "_conn", conn)
    client = TestClient(main.app)

    response = client.post("/api/opp_tag", params={"match_id": "target", "tag": "Ramp"})
    assert response.json() == {
        "ok": True, "match_id": "target", "tag": "Ramp", "scope": "match",
    }
    assert conn.execute(
        "SELECT opp_archetype_tag FROM matches WHERE match_id='target'").fetchone()[0] == "Ramp"
    assert conn.execute(
        "SELECT opp_archetype_tag FROM matches WHERE match_id='other'").fetchone()[0] is None

    assert client.post("/api/opp_tag", params={
        "match_id": "target", "tag": "Midrange",
    }).json()["ok"]
    assert client.get("/api/opponent_types").json()["rows"][0]["tag"] == "Midrange"
    assert client.post("/api/opp_tag", params={
        "match_id": "target", "tag": "",
    }).json()["ok"]
    assert conn.execute(
        "SELECT opp_archetype_tag FROM matches WHERE match_id='target'").fetchone()[0] is None

    assert not client.post("/api/opp_tag", params={
        "match_id": "target", "tag": "Invalid",
    }).json()["ok"]
    assert not client.post("/api/opp_tag", params={
        "match_id": "draft", "tag": "Aggro",
    }).json()["ok"]
    assert not client.post("/api/opp_tag", params={
        "match_id": "missing", "tag": "Aggro",
    }).json()["ok"]
    client.close()
    conn.close()
