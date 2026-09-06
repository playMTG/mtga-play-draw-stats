# -*- coding: utf-8 -*-
"""生成合成演示数据（README 截图 / 演示库专用）。

随机生成虚构对局并写入指定 SQLite——不含任何真实玩家信息。
用法：
    python tools/make_demo_data.py                  # 默认 300 场 → data/demo.db
    python tools/make_demo_data.py -n 1000 -o out.db
"""
from __future__ import annotations

import argparse
import copy
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import store
from app.config import Config, DEFAULTS
from app.events import GameRecord, MatchRecord

EVENTS = [
    "Play_Brawl_Historic", "Ladder", "Play_Ladder_2026", "Standard_Ladder",
    "MWM_Modern_20260801", "PremierDraft_LCI",
]
DECKS = ["Demo Izzet Blitz", "Demo Brawl Aggro", "Demo Gold Control"]
COMMANDERS = [
    "96352", "96353", "105001", "107778", "110801", "112233",
]
OPP_NAMES = ["DemoPlayerA", "DemoPlayerB", "DemoPlayerC", "DemoPlayerD"]
REASONS = ["ResultReason_Concede", "ResultReason_Normal", "ResultReason_Timeout"]

BASE_MS = 1750000000000  # 合成起始时间


def make_match(rng: random.Random, i: int) -> MatchRecord:
    match_id = f"demo-{i:06d}"
    start = BASE_MS + i * rng.randint(600_000, 3_600_000)
    duration = rng.randint(120, 1_500)
    play_draw = rng.choice(["play", "draw"])
    # 先手轻微优势 + 随机噪声，制造"像真的"的分布
    win_p = 0.55 if play_draw == "play" else 0.48
    result = "win" if rng.random() < win_p else "loss"
    m = MatchRecord(match_id=match_id, source="log")
    m.event_id = rng.choice(EVENTS)
    m.start_ms = start
    m.end_ms = start + duration * 1000
    m.my_seat, m.my_team = 1, 1
    m.opponent_name = rng.choice(OPP_NAMES)
    m.opponent_platform = "PC"
    m.play_draw = play_draw
    m.my_result = result
    m.end_reason = rng.choice(REASONS).removeprefix("ResultReason_")
    m.total_turns = rng.randint(5, 24)
    g = GameRecord(game_no=1, play_draw=play_draw, result=result,
                   reason=m.end_reason)
    m.games = [g]
    m.commanders = [{"seat": 1, "grp_id": rng.choice(COMMANDERS), "partner_idx": 0},
                    {"seat": 2, "grp_id": rng.choice(COMMANDERS), "partner_idx": 0}]
    kept = rng.choices([0, 1, 2], weights=[70, 22, 8])[0]
    m.mulligans = [{"game_no": 1, "seat": 1, "kept_on": kept}]
    m.my_deck_tag = rng.choice(DECKS)
    return m


def main() -> int:
    ap = argparse.ArgumentParser(description="生成合成演示对局库（纯虚构数据）")
    ap.add_argument("-n", type=int, default=300, help="生成场数（默认 300）")
    ap.add_argument("-o", "--output", type=Path, default=None,
                    help="输出 db 路径（默认 data/demo.db）")
    ap.add_argument("--seed", type=int, default=42, help="随机种子（可复现）")
    args = ap.parse_args()

    root = Path(__file__).resolve().parent.parent
    out = args.output or (root / "data" / "demo.db")
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()  # 每次全新生成

    cfg = Config(copy.deepcopy(DEFAULTS), root)  # 内置默认阈值，不读本机 config.json
    conn = store.connect(out, None)
    rng = random.Random(args.seed)
    for i in range(args.n):
        store.upsert_match(conn, make_match(rng, i), cfg)
    conn.commit()
    st = store.stats(conn)
    print(f"已生成 {args.n} 场合成对局 → {out}")
    print(f"  有胜负 {st['with_result']} | games {st['games']} | "
          f"mulligans {st['mulligans']} | 主将 {st['with_commanders']} 场")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
