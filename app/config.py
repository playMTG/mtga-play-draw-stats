# -*- coding: utf-8 -*-
"""配置加载：config.json（gitignored）缺失时回退到内置默认。"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

DEFAULTS: dict = {
    "port": 8765,
    "db_path": "data/mtga_stats.db",
    "watch_on_start": True,
    "log_paths": {
        "player_log": "%USERPROFILE%\\AppData\\LocalLow\\Wizards Of The Coast\\MTGA\\Player.log",
        "prev_log": "%USERPROFILE%\\AppData\\LocalLow\\Wizards Of The Coast\\MTGA\\Player-prev.log",
        # 历史会话日志（UTC_Log-*.log）：Steam 默认位置仅作候选之一，
        # 完整候选见 session_log_dirs()——官方客户端、Steam 多库、显式配置均支持
        "steam_session_logs": "C:\\Program Files (x86)\\Steam\\steamapps\\common\\MTGA\\MTGA_Data\\Logs\\Logs",
        # 额外会话日志目录（可选列表）：官方客户端自定义安装位置等场景手动指定
        "session_logs_extra": [],
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

    def session_log_dirs(self) -> list[Path]:
        """历史会话日志（UTC_Log-*.log）的全部候选目录。

        覆盖三种安装形态：
          1. Steam 默认位置（旧配置键，向后兼容）
          2. 官方客户端：默认 %ProgramFiles%\\Wizards of the Coast\\MTGA
          3. Steam 多库安装：解析 libraryfolders.vdf 里的所有库路径
        另合并 config 显式指定的 session_logs_extra 列表（优先级最高场景）。
        """
        dirs: list[Path] = [self.steam_logs_dir]
        lp = self._d.get("log_paths", {})
        for s in lp.get("session_logs_extra") or []:
            dirs.append(self.expand(str(s)))
        # 官方客户端默认安装位置
        for var in ("ProgramFiles", "ProgramFiles(x86)"):
            base = os.environ.get(var)
            if base:
                dirs.append(Path(base) / "Wizards of the Coast" / "MTGA"
                            / "MTGA_Data" / "Logs" / "Logs")
        # Steam 多库：libraryfolders.vdf 列出所有库
        pf86 = os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)")
        vdf = Path(pf86) / "Steam" / "steamapps" / "libraryfolders.vdf"
        if vdf.is_file():
            try:
                text = vdf.read_text(encoding="utf-8", errors="replace")
            except OSError:
                text = ""
            for m in re.finditer(r'"path"\s*"([^"]+)"', text):
                lib = Path(m.group(1).replace("\\\\", "\\"))
                dirs.append(lib / "steamapps" / "common" / "MTGA"
                            / "MTGA_Data" / "Logs" / "Logs")
        # 去重（Windows 路径大小写不敏感）
        seen: set[str] = set()
        out: list[Path] = []
        for d in dirs:
            key = str(d).lower().rstrip("\\")
            if key not in seen:
                seen.add(key)
                out.append(d)
        return out

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
