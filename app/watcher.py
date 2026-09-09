# -*- coding: utf-8 -*-
"""日志监听：tail 轮询 + 滚动检测。

滚动场景（MTGA 重启）：Player.log 被改名/重建，当前句柄失效。
策略：记录指纹（路径+大小+读偏移）；检测到文件变小或消失时，
先把旧文件剩余部分读完，再对新文件从头回填——入库层 match_id
幂等保证不重不漏。
"""
from __future__ import annotations

import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from .parser import LineRecord, RecordAssembler, iter_lines


@dataclass
class _Fingerprint:
    path: Path
    size: int
    offset: int


class LogWatcher:
    """对单个日志文件做增量 tail；yield 新的逻辑记录（多行 JSON 块已合并）。

    必须用 RecordAssembler 合并多行块后再产出：MTGA 日志存在跨行
    pretty-printed JSON，逐物理行喂入解析器会因括号不平衡而整块丢弃
    （backfill 走 iter_records 是合并语义，两入口必须一致，否则监听
    重放 upsert 时子表重写会冲坏回填的正确数据）。
    """

    def __init__(self, path: Path, poll_sec: float = 0.5):
        self.path = path
        self.poll_sec = poll_sec
        self._fp: _Fingerprint | None = None
        self._asm = RecordAssembler()
        self._identity = None
        self._prefix = b""
        self._ts = None

    def _current_size(self) -> int | None:
        try:
            return self.path.stat().st_size
        except OSError:
            return None

    def poll(self) -> Iterator[LineRecord]:
        """非阻塞读取自上次位置以来的新内容（逻辑记录）；处理滚动/截断。"""
        size = self._current_size()
        if size is None:
            return
        st = self.path.stat()
        identity = (st.st_dev, st.st_ino)
        with self.path.open("rb") as f:
            prefix = f.read(min(size, 256))
        replaced = (self._identity is not None and identity != self._identity)
        replaced |= bool(self._prefix and not prefix.startswith(self._prefix))
        self._identity = identity
        if self._fp is None:
            self._fp = _Fingerprint(self.path, size, 0)
        elif replaced or size < self._fp.offset:
            # 旧文件若仍以改名形式存在（prev），由调用方决定是否补读；
            # 先把组装器里未闭合的块兜底产出，再把当前文件当新文件从头读。
            self._asm = RecordAssembler()
            self._ts = None
            self._fp = _Fingerprint(self.path, size, 0)
        self._prefix = prefix
        if size > self._fp.offset:
            for rec in iter_lines(self.path, start_offset=self._fp.offset):
                if not rec.text.endswith("\n"):
                    break  # 半行留到下一次读取，避免 UTF-8 或 JSON 被切断
                self._fp.offset += rec.nbytes
                if rec.ts_ms is not None:
                    self._ts = rec.ts_ms
                for done in self._asm.feed(rec.text):
                    # 逻辑记录的时间戳：iter_lines 的 ts_ms 跨行延续，
                    # 多行块的时间戳通常在首行，此处已携带正确上下文
                    yield LineRecord(rec.line_no, done, self._ts)
        else:
            self._fp.size = size

    def _flush_asm(self) -> Iterator[LineRecord]:
        for done in self._asm.flush():
            yield LineRecord(0, done)

    def follow(self) -> Iterator[LineRecord]:
        """持续跟随（阻塞式），供常驻进程使用。"""
        while True:
            yield from self.poll()
            time.sleep(self.poll_sec)
