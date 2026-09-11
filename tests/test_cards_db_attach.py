# -*- coding: utf-8 -*-
"""R12.5 全新解压时 cards_db.cards 必须可用。

背景：store.connect() 无论卡名库文件是否存在都会 ATTACH（R12.1），
但 SQLite 会为不存在的路径新建一张空库——此时 cards 表还没建
（表原先只由 cards_sync.cards_db_connect 创建）。结果「已挂载但无表」，
所有裸查会撞 no such table: cards_db.cards（main.py 里两条路径会 500）。

这里断言：ATTACH 之后表立即存在，且结构与 cards_sync 完全一致。
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import cards_sync, store


def _fresh(tmp_path: Path):
    """模拟全新解压：stats 库与 cards 库都不存在。"""
    return store.connect(tmp_path / "stats.db", cards_db_path=tmp_path / "cards.db")


def test_cards_table_exists_right_after_attach(tmp_path):
    conn = _fresh(tmp_path)
    try:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM cards_db.sqlite_master WHERE type='table'")}
        assert "cards" in tables
    finally:
        conn.close()


def test_bare_cards_query_does_not_raise(tmp_path):
    """main.py:635 / :709 两条裸露路径用到的 SQL 形态。"""
    conn = _fresh(tmp_path)
    try:
        # 主将档案打标（存在性子查询形态）
        conn.execute("SELECT COALESCE((SELECT name FROM cards_db.cards WHERE grp_id = c.grp_id),"
                     " 'grpId:' || c.grp_id) FROM commanders c LIMIT 1")
        # 对局打标（LEFT JOIN 形态）
        conn.execute("SELECT cards.name FROM commanders c"
                     " LEFT JOIN cards_db.cards cards ON cards.grp_id = c.grp_id LIMIT 1")
    finally:
        conn.close()


def test_schema_matches_cards_sync(tmp_path):
    """单一事实源：store 建出的列必须和 cards_sync 的一模一样。"""
    conn = _fresh(tmp_path)
    try:
        from_store = {r[1] for r in conn.execute("PRAGMA cards_db.table_info(cards)")}
    finally:
        conn.close()

    other = cards_sync.cards_db_connect(tmp_path / "other.db")
    try:
        from_sync = {r[1] for r in other.execute("PRAGMA table_info(cards)")}
    finally:
        other.close()

    assert from_store == from_sync


def test_cards_joinable_probe(tmp_path, monkeypatch):
    """探测函数：有表返回 True，未挂载返回 False。"""
    from app import main

    conn = _fresh(tmp_path)
    try:
        assert main.cards_joinable(conn) is True
    finally:
        conn.close()

    # 不挂载卡名库的连接
    plain = sqlite3.connect(tmp_path / "plain.db")
    try:
        assert main.cards_joinable(plain) is False
    finally:
        plain.close()
