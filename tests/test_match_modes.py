from datetime import datetime

from app import stats, store
from app.config import Config
from app.deck_detail import deck_detail
from app.events import GameRecord, MatchRecord
from app.insights import daily_report


def _cfg(tmp_path):
    return Config({"db_path": str(tmp_path / "modes.db")}, tmp_path)


def _match(match_id, event, games, *, result="win", play_draw="play"):
    return MatchRecord(
        match_id=match_id,
        event_id=event,
        start_ms=int(datetime.now().timestamp() * 1000),
        my_seat=1,
        my_result=result,
        play_draw=play_draw,
        my_deck_tag="模式测试套牌",
        my_deck_id="deck-mode",
        my_deck_version="version-mode",
        games=games,
    )


def test_match_mode_is_persisted_and_reclassified_when_later_games_arrive(tmp_path):
    cfg = _cfg(tmp_path)
    conn = store.connect(cfg.db_path)
    one = [GameRecord(1, play_draw="play", result="win")]
    two = one + [GameRecord(2, play_draw="draw", result="loss")]

    store.upsert_match(conn, _match("bo1", "Play_Brawl_Historic", one), cfg)
    store.upsert_match(conn, _match("traditional", "Traditional_Ladder", one), cfg)
    store.upsert_match(conn, _match("named-bo3", "Constructed_BestOf3", one), cfg)
    store.upsert_match(conn, _match("late", "Unrecognized_Event", one), cfg)
    conn.commit()
    by_id = {row["match_id"]: row["match_mode"] for row in conn.execute(
        "SELECT match_id,match_mode FROM matches")}
    assert by_id == {"bo1": "BO1", "traditional": "BO3",
                     "named-bo3": "BO3", "late": "未知"}

    store.upsert_match(conn, _match("late", "Unrecognized_Event", two), cfg)
    conn.commit()
    assert conn.execute("SELECT match_mode FROM matches WHERE match_id='late'").fetchone()[0] == "BO3"

    # 旧库或中断迁移留下的空值会在下次连接时回填。
    conn.execute("UPDATE matches SET match_mode=NULL WHERE match_id='bo1'")
    conn.commit()
    conn.close()
    conn = store.connect(cfg.db_path)
    assert conn.execute("SELECT match_mode FROM matches WHERE match_id='bo1'").fetchone()[0] == "BO1"
    assert conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] == "2"

    conn.execute("INSERT INTO matches(match_id,source,event_id) VALUES('duplicate-game','log','Mystery')")
    conn.executemany("INSERT INTO games(match_id,game_no) VALUES('duplicate-game',1)", [(), ()])
    conn.commit()
    conn.close()
    conn = store.connect(cfg.db_path)
    assert conn.execute("SELECT match_mode FROM matches WHERE match_id='duplicate-game'").fetchone()[0] == "未知"
    conn.close()


def test_mode_filter_is_shared_by_reports_lists_exports_and_deck_detail(tmp_path):
    cfg = _cfg(tmp_path)
    conn = store.connect(cfg.db_path)
    one = [GameRecord(1, play_draw="play", result="win")]
    two = [GameRecord(1, play_draw="draw", result="loss"),
           GameRecord(2, play_draw="play", result="win")]
    for item in (
        _match("bo1", "Play_Brawl_Historic", one),
        _match("bo3-event", "Traditional_Ladder", one, result="loss", play_draw="draw"),
        _match("bo3-games", "Unrecognized_Event", two),
        _match("unknown", "Unrecognized_Other", one, result="loss", play_draw="draw"),
    ):
        store.upsert_match(conn, item, cfg)
    conn.commit()

    assert stats.overview(conn, mode="BO3")["total"]["n"] == 2
    listed = stats.match_list(conn, mode="BO3")
    assert listed["total"] == 2
    assert {row["match_mode"] for row in listed["rows"]} == {"BO3"}
    assert [game["game_no"] for game in next(
        row for row in listed["rows"] if row["match_id"] == "bo3-games")["games"]] == [1, 2]

    filters = stats.filter_options(conn)
    assert {item["value"]: item["n"] for item in filters["modes"]} == {
        "BO1": 1, "BO3": 2, "未知": 1,
    }
    headers, exported = stats.export_rows(conn, mode="BO3")
    mode_index = headers.index("比赛模式")
    assert len(exported) == 2 and {row[mode_index] for row in exported} == {"BO3"}

    day = datetime.now().date().isoformat()
    report = daily_report(conn, day=day, mode="BO3")
    assert report["summary"]["n"] == 2
    assert report["scope"]["mode"] == "BO3"
    targeting = stats.targeting_index(conn, window_days=7, mode="BO3")
    assert targeting["summary"]["n"] == 2
    assert targeting["scope"]["mode"] == "BO3"

    deck = deck_detail(conn, deck_id="deck-mode", deck_version="version-mode",
                       scope="all", mode="BO3")
    assert deck["selected_mode"] == "BO3"
    assert deck["summary"]["n"] == 2
    assert {row["match_mode"] for row in deck["records"]} == {"BO3"}
    assert {item["value"]: item["n"] for item in deck["modes"]} == {
        "BO1": 1, "BO3": 2, "未知": 1,
    }
    assert len(next(row for row in deck["records"]
                    if row["match_id"] == "bo3-games")["games"]) == 2
    conn.close()
