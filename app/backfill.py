# -*- coding: utf-8 -*-
"""回填 CLI：三来源（Player.log / Player-prev.log / UTC_Log 目录）一次性入库。

用法：
    python -m app.backfill              # 按配置回填
    python -m app.backfill --file X.log # 单文件回填（测试用）

身份探测：config.my_player_id 为空时，统计所有 reservedPlayers 行中
userId 出现频次——每场都在场的是我（对手来回换），取最高频者。
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

from .config import Config, load_config
from .events import SessionBuilder
from .ingest_marks import IngestMarks
from .parser import iter_records_with_offsets
from . import store

USERID_RE = re.compile(r'"userId"\s*:\s*"([A-Z0-9]{8,})"')


def _safe_exists(path: Path) -> bool:
    """Path.exists 在 Windows 上可能因日志被独占抛 PermissionError。"""
    try:
        return path.exists()
    except OSError:
        return False


def collect_sources(cfg: Config, extra_file: Path | None = None) -> list[Path]:
    files: list[Path] = []
    if extra_file:
        files.append(extra_file)
    # 归档目录优先：客户端可能已删除原始会话日志，归档是持久来源
    archive_dir = cfg.root / "data" / "archive"
    archived: dict[str, int] = {}
    if archive_dir.is_dir():
        for f in sorted(archive_dir.glob("UTC_Log*.log")):
            files.append(f)
            try:
                archived[f.name] = f.stat().st_size
            except OSError:
                pass
    for p in (cfg.player_log, cfg.prev_log):
        if _safe_exists(p):
            files.append(p)
    for d in cfg.session_log_dirs():
        if not d.is_dir():
            continue
        for f in sorted(d.glob("UTC_Log*.log")):
            try:
                size = f.stat().st_size
            except OSError:
                continue
            if archived.get(f.name) == size:
                continue  # 归档中已有同名同大小副本，避免重复解析
            files.append(f)
    return files


def detect_player_id(files: list[Path]) -> str | None:
    counts: Counter[str] = Counter()
    for f in files:
        try:
            with open(f, "r", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    if "reservedPlayers" in line:
                        counts.update(USERID_RE.findall(line))
        except OSError:
            continue
    return counts.most_common(1)[0][0] if counts else None


def backfill(cfg: Config, files: list[Path]) -> dict:
    my_id = cfg.my_player_id or detect_player_id(files)
    if my_id is None:
        print("!! 未能探测到玩家身份（日志中无 reservedPlayers）", file=sys.stderr)

    conn = store.connect(cfg.db_path)
    marks = IngestMarks(conn)
    total_new = total_updated = total_skipped = 0
    per_file: list[tuple[str, int, int]] = []

    for f in files:
        src_name = f.name
        # 水位线：文件自上次消费以来一个字节都没变 → 整份跳过（R12.2）。
        # 归档日志是这一步的主要收益：它们不再变化，却占了全部解析量的大头。
        if marks.is_unchanged(f):
            total_skipped += 1
            continue
        sb = SessionBuilder(source="log", my_player_id=my_id)
        consumed = 0
        try:
            for text, ts, end in iter_records_with_offsets(f):
                sb.feed(text, ts)
                consumed = end
        except OSError as e:
            print(f"!! 读取失败 {f}: {e}", file=sys.stderr)
            continue
        result = sb.close()
        new = upd = 0
        for m in result.matches:
            if store.upsert_match(conn, m, cfg):
                new += 1
            else:
                upd += 1
        for snap in result.ranks:
            store.insert_rank(conn, snap)
        # 只有真正读到内容才落水位线；中途失败不记录，下次重来
        if consumed:
            marks.put(f, consumed, sb.last_ts)
        conn.commit()
        per_file.append((src_name, len(result.matches), result.unparsed_lines))
        total_new += new
        total_updated += upd

    st = store.stats(conn)
    conn.close()
    return {
        "my_id": my_id,
        "new": total_new,
        "updated": total_updated,
        "skipped": total_skipped,
        "stats": st,
        "per_file": per_file,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="MTGA 日志回填入库")
    ap.add_argument("--file", type=Path, default=None, help="只回填指定日志文件")
    args = ap.parse_args()

    cfg = load_config()
    files = collect_sources(cfg, args.file)
    if not files:
        print("没有找到任何日志文件，请检查 config.json 的 log_paths", file=sys.stderr)
        return 1

    r = backfill(cfg, files)
    print(f"身份探测: {r['my_id']}")
    print(f"来源文件: {len(files)} 份（跳过未变化 {r['skipped']} 份）")
    for name, n, bad in r["per_file"]:
        print(f"  {name}: 解析对局 {n}, 损坏行 {bad}")
    st = r["stats"]
    print(f"\n入库: 新增 {r['new']}, 更新 {r['updated']}")
    print(f"对局总数 {st['matches']}（有胜负 {st['with_result']}, "
          f"含主将 {st['with_commanders']}, 异常局 {st['abnormal']}）")
    print(f"games {st['games']} | mulligans {st['mulligans']} | 段位快照 {st['ranks']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
