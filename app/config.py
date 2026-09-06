# -*- coding: utf-8 -*-
"""配置加载：config.json（gitignored）缺失时回退到内置默认。"""
from __future__ import annotations

import json
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

DEFAULTS: dict = {
    "port": 8765,
    "db_path": "data/mtga_stats.db",
    "watch_on_start": True,
    "log_paths": {
        "player_log": "%USERPROFILE%\\AppData\\LocalLow\\Wizards Of The Coast\\MTGA\\Player.log",
        "prev_log": "%USERPROFILE%\\AppData\\LocalLow\\Wizards Of The Coast\\MTGA\\Player-prev.log",
        "steam_session_logs": "C:\\Program Files (x86)\\Steam\\steamapps\\common\\MTGA\\MTGA_Data\\Logs\\Logs",
    },
    "abnormal_match": {"max_duration_sec": 150, "max_turns": 2},
    "targeting_index": {
        "weights": {"play_draw": 0.25, "matchup": 0.35, "mulligan": 0.2, "streak": 0.2},
        "min_sample": 20,
        "p_normal": 0.10,
    },
    "my_player_id": "",  # MTGA userId；留空则回填时自动探测
    "my_deck_tags": {},
    "card_name_lang": "zh",  # 卡名显示语言：zh=中文优先（缺中文回落英文）| en
    "bot_deck_patterns": ["bot"],  # 套牌名含这些子串（不区分大小写）→ Bot 刷分局，统计默认排除
    "untapped_import": {"account_id": "", "player_id": ""},
}


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


class Config:
    def __init__(self, data: dict, root: Path):
        self._d = data
        self.root = root

    def __getitem__(self, key):
        return self._d[key]

    def get(self, key, default=None):
        return self._d.get(key, default)

    @property
    def port(self) -> int:
        return int(self._d["port"])

    @property
    def db_path(self) -> Path:
        p = Path(self._d["db_path"])
        return p if p.is_absolute() else self.root / p

    def expand(self, path: str) -> Path:
        return Path(os.path.expandvars(path))

    @property
    def player_log(self) -> Path:
        return self.expand(self._d["log_paths"]["player_log"])

    @property
    def prev_log(self) -> Path:
        return self.expand(self._d["log_paths"]["prev_log"])

    @property
    def steam_logs_dir(self) -> Path:
        return self.expand(self._d["log_paths"]["steam_session_logs"])

    @property
    def my_player_id(self) -> str:
        return str(self._d.get("my_player_id") or "")

    @property
    def abnormal_max_duration(self) -> float:
        return float(self._d["abnormal_match"]["max_duration_sec"])

    @property
    def abnormal_max_turns(self) -> int:
        return int(self._d["abnormal_match"]["max_turns"])


def load_config(root: Path = REPO_ROOT) -> Config:
    cfg_file = root / "config.json"
    data = DEFAULTS
    if cfg_file.exists():
        try:
            data = _deep_merge(DEFAULTS, json.loads(cfg_file.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            pass  # 配置损坏时静默回退默认值
    return Config(data, root)
