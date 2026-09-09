# -*- coding: utf-8 -*-
"""M4 单测：段位曲线刻度与合并、CSV 导出、中文卡名降级。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import fixtures as fx
from app.events import SessionBuilder
from app.store import connect, upsert_match
from app import stats


def _cfg(tmp_path):
    from app.config import Config
    return Config({"db_path": str(tmp_path / "t.db"),
                   "abnormal_match": {"max_duration_sec": 150, "max_turns": 2}}, tmp_path)


def _store(tmp_path):
    cfg = _cfg(tmp_path)
    conn = connect(cfg.db_path)
    sb = SessionBuilder(my_player_id=fx.ME)
    for t in fx.bo1_match_lines():
        sb.feed(t)
    for m in sb.close().matches:
        upsert_match(conn, m, cfg)
    conn.commit()
    return conn, cfg


def _rank(conn, ts, cc=None, cl=None, lc=None, ll=None):
    conn.execute(
        "INSERT INTO rank_snapshots(ts, constructed_class, constructed_level, "
        "limited_class, limited_level) VALUES(?,?,?,?,?)",
        (ts, cc, cl, lc, ll),
    )


# ---------- rank_score 刻度 ----------

def test_rank_score_monotonic():
    assert stats.rank_score("Bronze", 4) == 1
    assert stats.rank_score("Bronze", 1) == 4
    assert stats.rank_score("Silver", 4) == 5
    assert stats.rank_score("Gold", 4) == 9
    assert stats.rank_score("Gold", 2) == 11
    assert stats.rank_score("Platinum", 1) == 16
    assert stats.rank_score("Diamond", 1) == 20
    assert stats.rank_score("Mythic", 1) == 21
    # 单调性：非秘稀段位严格递增，秘稀高于钻石1
    seq = [stats.rank_score(c, l) for c in stats.RANK_CLASSES[:-1] for l in (4, 3, 2, 1)]
    assert all(b > a for a, b in zip(seq, seq[1:]))
    assert stats.rank_score("Mythic", 1) > seq[-1]


def test_rank_score_unknown():
    assert stats.rank_score("Unranked", 3) is None
    assert stats.rank_score("Gold", None) is None
    assert stats.rank_score("Gold", 9) is None


def test_score_label():
    assert stats.score_label(1) == "青铜4"
    assert stats.score_label(4) == "青铜1"
    assert stats.score_label(9) == "黄金4"
    assert stats.score_label(20) == "钻石1"
    assert stats.score_label(21) == "秘稀"


# ---------- rank_curve ----------

def test_rank_curve_merges_and_skips_null_ts(tmp_path):
    conn, _ = _store(tmp_path)
    _rank(conn, None, "Gold", 4)          # 无时间戳：不参与
    _rank(conn, 1000, "Gold", 4)
    _rank(conn, 2000, "Gold", 4)          # 相邻重复：合并
    _rank(conn, 3000, "Gold", 2)          # 变化：保留
    _rank(conn, 4000, "Mythic", 1)
    _rank(conn, 5000, "Gold", 4)          # 回落：保留（非相邻重复）
    conn.commit()
    r = stats.rank_curve(conn, "constructed")
    pts = r["points"]
    assert [p["score"] for p in pts] == [9, 11, 21, 9]
    assert pts[0]["label"] == "黄金4"
    # limited 轨道为空不崩溃
    assert stats.rank_curve(conn, "limited")["points"] == []


def test_rank_curve_tracks_independent(tmp_path):
    conn, _ = _store(tmp_path)
    _rank(conn, 1000, "Gold", 4, "Silver", 1)
    conn.commit()
    c = stats.rank_curve(conn, "constructed")["points"]
    l = stats.rank_curve(conn, "limited")["points"]
    assert [p["score"] for p in c] == [9]
    assert [p["score"] for p in l] == [8]  # Silver1 = 5+3


# ---------- export_rows ----------

def test_export_ranks(tmp_path):
    conn, _ = _store(tmp_path)
    _rank(conn, 1788607429278, "Gold", 4, "Silver", 1)
    conn.commit()
    headers, rows = stats.export_rows(conn, "ranks")
    assert headers == ["时间", "构组段位", "构组等级", "轮抽段位", "轮抽等级"]
    assert rows[0][1] == "Gold" and rows[0][3] == "Silver"


def test_export_matches(tmp_path):
    conn, _ = _store(tmp_path)
    headers, rows = stats.export_rows(conn, "matches", exclude_abnormal=False)
    assert len(headers) == 18
    assert len(rows) == 1
    r = dict(zip(headers, rows[0]))
    assert r["赛事"] == "Play_Brawl_Historic"
    assert r["结果"] == "win"
    assert r["先后手"] == "play"
    assert "我方主将" in r
    assert "对手主将" in r and r["对手主将"]  # grpId 降级形式


def test_export_matches_abnormal_filter(tmp_path):
    conn, cfg = _store(tmp_path)
    # fixtures 对局 2 回合 → 判定异常；排除后应导出 0 行
    n_abn = conn.execute("SELECT COUNT(*) c FROM matches WHERE is_abnormal=1").fetchone()["c"]
    _, rows = stats.export_rows(conn, "matches", exclude_abnormal=True)
    if n_abn:
        assert rows == []
    _, rows = stats.export_rows(conn, "matches", exclude_abnormal=False)
    assert len(rows) == 1


# ---------- 中文卡名降级 ----------

def test_matchups_without_cards_db_uses_grp_id(tmp_path):
    conn, _ = _store(tmp_path)  # 未 ATTACH 卡名库
    rows = stats.matchups(conn, exclude_abnormal=False, lang="zh")
    assert rows and all(r["name"].startswith("grpId:") for r in rows)


def test_matchups_lang_en_matches_default_shape(tmp_path):
    conn, _ = _store(tmp_path)
    for lang in ("zh", "en"):
        rows = stats.matchups(conn, exclude_abnormal=False, lang=lang)
        assert rows and all("name" in r for r in rows)


# ---------- my_deck_tag 导入与手动打标共存（M4.5 导入口径） ----------

def test_deck_tag_import_and_manual_priority(tmp_path):
    from app.events import MatchRecord
    conn, cfg = _store(tmp_path)
    # 导入源自带套牌名
    m = MatchRecord(match_id="ut_1", source="untapped", my_deck_tag="W3")
    assert upsert_match(conn, m, cfg) is True
    assert conn.execute("SELECT my_deck_tag FROM matches WHERE match_id='ut_1'"
                        ).fetchone()["my_deck_tag"] == "W3"
    # 手动改标后重放导入（解析行 tag=None）：手动值优先，不被清空
    conn.execute("UPDATE matches SET my_deck_tag='手动名' WHERE match_id='ut_1'")
    upsert_match(conn, m, cfg)
    assert conn.execute("SELECT my_deck_tag FROM matches WHERE match_id='ut_1'"
                        ).fetchone()["my_deck_tag"] == "手动名"


# ---------- Bot 局排除（M4.5） ----------

def test_bot_tag_and_stats_exclusion(tmp_path):
    from app.events import MatchRecord
    from app.store import tag_bot_decks
    conn, cfg = _store(tmp_path)
    conn.execute("UPDATE matches SET my_deck_tag='Bot BO1'")
    conn.commit()
    assert tag_bot_decks(conn, ["bot"]) == 1
    # 统计默认排除 Bot 局（fixtures 对局本身异常，需同时关闭异常排除）
    assert stats.overview(conn, exclude_abnormal=False)["total"]["n"] == 0
    assert stats.overview(conn, exclude_abnormal=False, exclude_bot=False)["total"]["n"] == 1
    assert stats.match_list(conn, exclude_abnormal=False)["rows"] == []
    assert stats.match_list(conn, exclude_abnormal=False, exclude_bot=False)["rows"]
