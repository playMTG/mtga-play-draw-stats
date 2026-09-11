# -*- coding: utf-8 -*-
"""R12.3 启动期并发安全。

三处同类的「检查与动作之间存在窗口」问题：
1. `get_conn()` 无锁无双检——首屏请求与启动线程并发时各自 connect 一次，
   后来者覆盖全局连接，先前那个被丢弃却仍被调用方使用；
2. `_boot_tasks` 里 `store.tag_bot_decks` 在 `_db_lock` 之外写库；
3. `/api/retry_boot` 先读 `booting` 再起线程——两次点按能起两个回填线程。

这里用真实线程并发压这几条路径，断言最终只建一个连接、只起一个回填线程。
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import main, store


@pytest.fixture
def isolated_main(tmp_path, monkeypatch):
    """把 main 的全局连接状态隔离到临时库，跑完还原。"""
    monkeypatch.setattr(main.cfg.__class__, "db_path", property(lambda self: tmp_path / "s.db"))
    monkeypatch.setattr(main.cfg.__class__, "root", property(lambda self: tmp_path))
    monkeypatch.setattr(main, "_conn", None)
    yield tmp_path
    monkeypatch.setattr(main, "_conn", None)


def test_get_conn_builds_only_one_connection(tmp_path, monkeypatch):
    """并发调用 get_conn 只能建出一个连接，且所有调用方拿到同一个对象。"""
    monkeypatch.setattr(main, "_conn", None)
    calls: list[int] = []
    real_connect = store.connect

    def counting_connect(*a, **kw):
        calls.append(1)
        return real_connect(*a, **kw)

    monkeypatch.setattr(store, "connect", counting_connect)
    monkeypatch.setattr(main.store, "connect", counting_connect)

    results: list[object] = []
    barrier = threading.Barrier(8)

    def worker():
        barrier.wait()  # 尽量让 8 个线程同时冲进 get_conn
        results.append(main.get_conn())

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert len(results) == 8
    assert len(calls) == 1, f"并发下建了 {len(calls)} 个连接，应只有 1 个"
    assert len({id(r) for r in results}) == 1, "所有调用方应拿到同一个连接"
    monkeypatch.setattr(main, "_conn", None)


def test_get_conn_does_not_deadlock_inside_db_lock(tmp_path, monkeypatch):
    """q() 会在持有 _db_lock 时调用 get_conn()；两者必须用不同的锁。"""
    monkeypatch.setattr(main, "_conn", None)

    done = threading.Event()

    def call():
        main.q(lambda conn: conn.execute("SELECT 1").fetchone())
        done.set()

    t = threading.Thread(target=call, daemon=True)
    t.start()
    t.join(timeout=10)

    assert done.is_set(), "q() 内部调用 get_conn() 发生自锁"
    monkeypatch.setattr(main, "_conn", None)


def test_retry_boot_starts_single_thread(monkeypatch):
    """并发调用 retry_boot 只应起一个回填线程。"""
    started: list[int] = []
    RealThread = threading.Thread  # 先存下来，monkeypatch 会改掉模块属性

    class FakeThread:
        def __init__(self, target=None, daemon=None):
            self._target = target

        def start(self):
            started.append(1)  # 不真的执行 _boot_tasks

    monkeypatch.setattr(main.threading, "Thread", FakeThread)
    main._state["booting"] = False
    main._state["boot_error"] = "boom"  # 制造「上次失败」以便放行

    results = []
    barrier = threading.Barrier(6)

    def call():
        barrier.wait()
        results.append(main.api_retry_boot())

    threads = [RealThread(target=call) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    ok = [r for r in results if r.get("ok")]
    assert len(started) == 1, f"起了 {len(started)} 个回填线程，应只有 1 个"
    assert len(ok) == 1, "只应有一次调用真正启动任务"

    # 收尾：清掉占位，避免污染其他用例
    main._state["booting"] = False
    main._state["boot_error"] = None


def test_tag_bot_decks_runs_under_db_lock():
    """源码层面确认 tag_bot_decks 在 _db_lock 临界区内（缩进在 with 之下）。"""
    src = (Path(main.__file__)).read_text(encoding="utf-8")
    idx = src.index("store.tag_bot_decks(")
    # 往前找最近的语句行，确认它处于 with _db_lock 块内
    before = src[:idx]
    last_with = before.rfind("with _db_lock")
    assert last_with != -1, "tag_bot_decks 未包在 _db_lock 内"

    block = src[last_with:idx]
    # 该 with 与调用之间不应出现同级或更浅的语句（即调用仍在块内）
    for line in block.splitlines()[1:]:
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        assert indent > 4, f"tag_bot_decks 已脱离 _db_lock 块：{line!r}"
