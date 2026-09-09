# -*- coding: utf-8 -*-
"""Untapped 全史导入：data/untapped/untapped_matches_all.jsonl → SQLite。

去重口径（DESIGN §9 / M1 决策）：日志与 Untapped 两源按 match_id 天然不可联，
采用**时间窗切分**——只导入 start_time 早于日志覆盖起点（库内 source='log'
的最早对局）的 Untapped 对局；之后的对局由日志解析负责。幂等可重跑。

字段映射：
- match_id = ut_{ts}_{deck_id}_{on_play}（稳定伪 ID，重跑不重复）
- play_draw = on_play(1/0) → play/draw；my_result = win(1/0) → win/loss
- total_turns 不可得（置 0）；异常判定自动只按时长规则生效
- 此简化 JSONL 不含主将；原始 raw_b*.json 的 deckstring 可用 tools.enrich_untapped 补全

用法：python -m tools.import_untapped [--dry-run]
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path


from app.config import load_config
from app.events import MatchRecord
from app.store import connect, upsert_match

JSONL = Path(__file__).resolve().parent.parent / "data" / "untapped" / "untapped_matches_all.jsonl"


def log_cutoff(conn) -> int | None:
    """日志来源的最早对局时间（毫秒）；无日志数据时返回 None（全量导入）。"""
    row = conn.execute(
        "SELECT MIN(start_time) m FROM matches WHERE source='log'"
    ).fetchone()
    return row["m"] if row and row["m"] else None


def row_to_record(r: dict) -> MatchRecord:
    ts = int(r["ts"])
    dur = int(r.get("dur") or 0)
    return MatchRecord(
        match_id=f"ut_{ts}_{r.get('deck_id') or ''}_{r.get('on_play', 0)}",
        source="untapped",
        event_id=r.get("event") or None,
        start_ms=ts,
        end_ms=ts + dur * 1000 if dur else None,
        play_draw={1: "play", 0: "draw"}.get(r.get("on_play")),
        my_result={1: "win", 0: "loss"}.get(r.get("win")),
        my_deck_tag=r.get("deck") or None,
    )


def main() -> int:
    dry = "--dry-run" in sys.argv
    cfg = load_config()
    conn = connect(cfg.db_path)
    cutoff = log_cutoff(conn)
    print(f"日志覆盖起点: {cutoff}（该时刻之后的 Untapped 对局跳过，防双计）")

    rows = [json.loads(line) for line in
            JSONL.read_text(encoding="utf-8").splitlines() if line.strip()]
    todo = [r for r in rows if cutoff is None or int(r["ts"]) < cutoff]
    skipped = len(rows) - len(todo)
    print(f"全史 {len(rows)} 场 | 待导入 {len(todo)} 场 | 时间窗跳过 {skipped} 场")

    if dry:
        for r in todo[:3] + todo[-3:]:
            m = row_to_record(r)
            print(f"  {m.match_id} {m.start_ms} {m.event_id} {m.play_draw} {m.my_result}")
        return 0

    new = dup = 0
    for r in todo:
        if upsert_match(conn, row_to_record(r), cfg):
            new += 1
        else:
            dup += 1
        if (new + dup) % 2000 == 0:
            conn.commit()  # 分批提交，避免长事务
    conn.commit()

    # Bot 套牌打标（config 模式，幂等）
    from app.store import tag_bot_decks
    n_bot = tag_bot_decks(conn, cfg.get("bot_deck_patterns") or [])
    if n_bot:
        print(f"Bot 套牌打标：{n_bot} 场（模式：{cfg.get('bot_deck_patterns')}）")

    n = conn.execute("SELECT COUNT(*) c FROM matches").fetchone()["c"]
    by_src = conn.execute(
        "SELECT source, COUNT(*) c FROM matches GROUP BY source").fetchall()
    print(f"导入完成：新建 {new}，幂等跳过 {dup}；库内总对局 {n}（{[(r['source'], r['c']) for r in by_src]}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
