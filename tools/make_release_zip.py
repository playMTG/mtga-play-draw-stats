"""打发行 ZIP：把 git 跟踪的文件按版本号前缀打包到 dist/。

只用 `git ls-files` 作为打包清单来源——凡是没被 git 跟踪的文件（data/、
config.json、.workbuddy*/、.venv/、dist/ 自身等）一律不会进包，
避免把个人对局资料或本机设置带进发行包。

用法：
    python tools/make_release_zip.py 0.3.1
    python tools/make_release_zip.py 0.3.1 --name-prefix mytool

产出：dist/<name-prefix>-v<version>-windows.zip
包内根目录：<name-prefix>-v<version>/
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import zipfile
from pathlib import Path

DEFAULT_NAME_PREFIX = "mtga-play-draw-stats"
DEFAULT_ROOT_DIR = "dist"


def repo_root() -> Path:
    """以本脚本位置推断仓库根（tools/ 的上一级）。"""
    return Path(__file__).resolve().parent.parent


def tracked_files(root: Path) -> list[str]:
    """返回 git 跟踪的、且实际存在于磁盘上的文件（POSIX 相对路径）。"""
    proc = subprocess.run(
        ["git", "ls-files"],
        cwd=str(root),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if proc.returncode != 0:
        raise SystemExit(
            "git ls-files 失败，请确认当前目录是 git 仓库：\n" + (proc.stderr or "")
        )
    names: list[str] = []
    for line in proc.stdout.splitlines():
        rel = line.strip()
        if not rel:
            continue
        if not (root / rel).is_file():
            # 已删除但未 git rm 的残留条目：跳过
            continue
        names.append(rel)
    return sorted(names)


def build_zip(root: Path, version: str, name_prefix: str, out_dir: Path) -> Path:
    root_dir = f"{name_prefix}-v{version}"
    files = tracked_files(root)
    if not files:
        raise SystemExit("没有可打包的文件（git 跟踪清单为空）")

    out_dir.mkdir(parents=True, exist_ok=True)
    zip_path = out_dir / f"{root_dir}-windows.zip"

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        zf.writestr(f"{root_dir}/", "")
        for rel in files:
            zf.write(root / rel, f"{root_dir}/{rel}")

    return zip_path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="按 git 跟踪清单打发行 ZIP")
    ap.add_argument("version", help="版本号，例如 0.3.1（不要带 v 前缀）")
    ap.add_argument(
        "--name-prefix",
        default=DEFAULT_NAME_PREFIX,
        help=f"包名前缀（默认 {DEFAULT_NAME_PREFIX}）",
    )
    ap.add_argument(
        "--out-dir",
        default=DEFAULT_ROOT_DIR,
        help=f"输出目录（默认 {DEFAULT_ROOT_DIR}）",
    )
    args = ap.parse_args(argv)

    version = args.version.lstrip("vV")
    root = repo_root()
    out_dir = (root / args.out_dir).resolve()

    zip_path = build_zip(root, version, args.name_prefix, out_dir)

    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()

    size_kb = zip_path.stat().st_size / 1024
    print(f"已生成：{zip_path}")
    print(f"  条目数：{len(names)}（含根目录条目）")
    print(f"  体积：{size_kb:.1f} KB")
    print(f"  包内根目录：{args.name_prefix}-v{version}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
