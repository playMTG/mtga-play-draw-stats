# -*- coding: utf-8 -*-
"""日志行切分与 JSON 提取。

MTGA 详细日志存在两种条目形态：
  1. 单行：`[UnityCrossThreadLogger] ==> 事件名 {json...}`（可能单行数 MB）
  2. 多行 pretty-printed JSON 块（客户端 API 响应，跨行缩进）

因此按"逻辑记录"组装：跨行括号深度计数（字符串感知），深度归零即产出
一条完整记录，再从中提取 JSON。偏移以字节计（tail 用，避免换行翻译漂移）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

TS_RE = re.compile(r'"timestamp"\s*:\s*"(\d{13})"')


@dataclass(slots=True)
class LineRecord:
    line_no: int
    text: str
    ts_ms: int | None = None  # 行内最近一次出现的 epoch 毫秒时间戳
    nbytes: int = 0           # 原始字节长度（tail 偏移推进用）


def extract_jsons(text: str) -> list[str]:
    """提取文本中所有顶层 JSON 对象（{} 平衡、字符串感知）。"""
    out: list[str] = []
    depth, start, in_str, esc = 0, None, False, False
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start is not None:
                    out.append(text[start : i + 1])
                    start = None
    return out


class RecordAssembler:
    """把物理行组装成逻辑记录（跨行 JSON 块合并）。

    用法：逐行 feed(text)，返回该行触发的完成记录列表（0 或 1 条）。
    """

    def __init__(self) -> None:
        self._buf: list[str] = []
        self._depth = 0
        self._in_str = False
        self._esc = False
        self._open = False  # 缓冲区里有未闭合的 '{'

    def _scan(self, text: str) -> None:
        for ch in text:
            if self._in_str:
                if self._esc:
                    self._esc = False
                elif ch == "\\":
                    self._esc = True
                elif ch == '"':
                    self._in_str = False
                continue
            if ch == '"':
                self._in_str = True
            elif ch == "{":
                self._depth += 1
                self._open = True
            elif ch == "}" and self._depth > 0:
                self._depth -= 1

    def feed(self, text: str) -> list[str]:
        """喂入一行；若该行使 JSON 块闭合（或本就是无 JSON 的普通行）则返回完整记录。"""
        self._scan(text)
        self._buf.append(text)
        if self._open and self._depth == 0:
            record = "".join(self._buf)
            self._reset()
            return [record]
        if not self._open and text.strip() and "{" not in text:
            self._reset()
            return [text]
        return []

    def flush(self) -> list[str]:
        """文件结束时未闭合缓冲兜底产出。"""
        if self._buf and any(s.strip() for s in self._buf):
            record = "".join(self._buf)
            self._reset()
            return [record]
        return []

    def _reset(self) -> None:
        self._buf = []
        self._depth = 0
        self._in_str = False
        self._esc = False
        self._open = False


def iter_lines(path: Path, start_offset: int = 0) -> Iterator[LineRecord]:
    """二进制模式流式读取（偏移精确到字节）。"""
    ts_ms: int | None = None
    with open(path, "rb") as f:
        if start_offset:
            f.seek(start_offset)
        for line_no, raw in enumerate(f, 1):
            text = raw.decode("utf-8", errors="replace")
            if m := TS_RE.search(text):
                ts_ms = int(m.group(1))
            yield LineRecord(line_no, text, ts_ms, len(raw))


def iter_records(path: Path, start_offset: int = 0) -> Iterator[tuple[str, int | None]]:
    """产出逻辑记录 (text, ts_ms)：单行或多行 JSON 块已合并。

    时间戳上下文跨记录延续（不少记录块自身不带 timestamp，如段位响应），
    取"最近一次出现的时间戳"——与文件顺序单调一致。
    """
    asm = RecordAssembler()
    pending_ts: int | None = None

    for rec in iter_lines(path, start_offset):
        if m := TS_RE.search(rec.text):
            pending_ts = int(m.group(1))
        done = asm.feed(rec.text)
        if done:
            yield done[0], pending_ts
    for record in asm.flush():
        yield record, pending_ts  # 文件尾截断块兜底产出


def walk_dicts(obj) -> Iterator[dict]:
    """深度优先遍历所有嵌套 dict（防御式解析：结构未知/变动的兜底手段）。"""
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from walk_dicts(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk_dicts(v)
