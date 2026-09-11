# -*- coding: utf-8 -*-
"""回填/监听水位线（R12.2）：记录每个日志来源已消费到哪个字节。

**问题**：`backfill()` 每次启动都重新解析全部来源。归档目录会随会话持续增长
（实测 32 份 / 330 MB，外推每次启动约 43 秒），而 `LogWatcher` 又从偏移 0
开始，把 Player.log 再读一遍。

**取舍**：水位线只在「文件自上次记录以来完全没有变化」时生效。

- `size == 已记录偏移` 且身份（dev/ino）一致 → 整份跳过，不再解析；
- 文件变大了 → **从 0 重新解析**，不从中途续读。

之所以不从中途续读：中途起点很难保证落在「逻辑记录边界」上（MTGA 有跨行
pretty-printed JSON），而且会话解析器是有状态的——错过一场对局的开头会让
后续事件失去归属（R11.1 修的就是结果串场）。从 0 重放是幂等的（`match_id`
upsert），代价只是那一份文件；而真正的大头（不再变化的归档）被完整跳过。

这个规则同时保证记录下来的偏移一定落在真实边界上，因此 `resume_offset()`
返回非零时，可以直接从该偏移继续 tail。
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

MARKS_SCHEMA = """
CREATE TABLE IF NOT EXISTS ingest_marks (
  path TEXT PRIMARY KEY,
  dev INTEGER, ino INTEGER, size INTEGER, offset INTEGER,
  mtime_ns INTEGER, last_ts INTEGER, updated_at INTEGER);
"""

# Windows 的文件索引是无符号 64 位，可能超过 SQLite 有符号 INTEGER 上限
# （实测 OverflowError）。这里只做相等比较，取低 63 位即可，碰撞概率可忽略。
_INT63 = 0x7FFFFFFFFFFFFFFF


@dataclass(frozen=True)
class Mark:
    path: str
    dev: int | None
    ino: int | None
    size: int
    offset: int
    mtime_ns: int | None
    last_ts: int | None


def fingerprint(path: Path) -> tuple[int, int, int, int] | None:
    """(dev, ino, size, mtime_ns)；文件不可读时返回 None。

    dev/ino 掩到 63 位以适配 SQLite 的有符号 INTEGER。
    """
    try:
        st = path.stat()
    except OSError:
        return None
    return (int(st.st_dev) & _INT63, int(st.st_ino) & _INT63,
            int(st.st_size), int(st.st_mtime_ns))


class IngestMarks:
    """水位线读写。连接可以是共享主连接，也可以是回填自己的连接。"""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        conn.executescript(MARKS_SCHEMA)

    def get(self, path: Path) -> Mark | None:
        row = self.conn.execute(
            "SELECT path, dev, ino, size, offset, mtime_ns, last_ts "
            "FROM ingest_marks WHERE path=?",
            (str(path),),
        ).fetchone()
        if row is None:
            return None
        return Mark(row["path"], row["dev"], row["ino"], row["size"],
                    row["offset"], row["mtime_ns"], row["last_ts"])

    def put(self, path: Path, offset: int, last_ts: int | None = None) -> None:
        """记录「已消费到 offset」，连同当时的文件指纹。"""
        fp = fingerprint(path)
        if fp is None:
            return
        dev, ino, size, mtime_ns = fp
        self.conn.execute(
            """INSERT INTO ingest_marks(path, dev, ino, size, offset, mtime_ns,
                                        last_ts, updated_at)
               VALUES(?,?,?,?,?,?,?,strftime('%s','now'))
               ON CONFLICT(path) DO UPDATE SET
                 dev=excluded.dev, ino=excluded.ino, size=excluded.size,
                 offset=excluded.offset, mtime_ns=excluded.mtime_ns,
                 last_ts=excluded.last_ts, updated_at=excluded.updated_at""",
            (str(path), dev, ino, size, int(offset), mtime_ns, last_ts),
        )

    def forget(self, path: Path) -> None:
        self.conn.execute("DELETE FROM ingest_marks WHERE path=?", (str(path),))

    def resume_offset(self, path: Path) -> int:
        """可安全继续的起始偏移；文件有变化或身份不符时返回 0（从头解析）。

        返回非零值意味着「文件自上次记录以来一个字节都没变」，因此该偏移
        必然落在逻辑记录边界上。
        """
        mark = self.get(path)
        if mark is None or mark.offset <= 0:
            return 0
        fp = fingerprint(path)
        if fp is None:
            return 0
        dev, ino, size, mtime_ns = fp
        if mark.dev is not None and mark.ino is not None:
            if (dev, ino) != (mark.dev, mark.ino):
                return 0          # 文件被替换（日志轮换/重装）
        if size != mark.offset:
            return 0              # 变大或变小：从头解析更安全
        if mark.mtime_ns is not None and mtime_ns != mark.mtime_ns:
            return 0              # 大小没变但被原地改写
        return mark.offset

    def is_unchanged(self, path: Path) -> bool:
        """整份已消费且没有任何变化 → 可以跳过。"""
        return self.resume_offset(path) > 0
