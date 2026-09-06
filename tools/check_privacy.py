#!/usr/bin/env python3
"""push 前隐私扫描：命中即退出码 1，配合 git pre-push hook 或 CI 使用。

扫描对象：git 暂存区文件（不在 git 仓库时则扫描整个工作区，忽略 .gitignore 条目）。
规则：
  1. UUID 模式
  2. 20 位以上连续大写字母数字（MTGA userId 形态）
  3. Windows 本机用户路径 C:\\Users\\<name>
  4. 数据文件扩展名混入（.db/.jsonl/.log）
  5. .privacy-extra.txt 中的自定义黑名单词（该文件本身被 gitignore）
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
USERID_RE = re.compile(r"\b[A-Z0-9]{20,}\b")
WINPATH_RE = re.compile(r"C:\\Users\\[^\\\"'\s]+", re.IGNORECASE)
BAD_EXT = {".db", ".jsonl", ".log"}
TEXT_EXT = {".py", ".js", ".md", ".json", ".txt", ".html", ".yml", ".yaml", ".toml", ".cfg", ".example"}


def staged_files() -> list[Path]:
    try:
        out = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
            cwd=REPO, capture_output=True, text=True, check=True,
        ).stdout
        files = [REPO / f for f in out.splitlines() if f.strip()]
        return [f for f in files if f.exists()]
    except (subprocess.CalledProcessError, FileNotFoundError):
        # 不在 git 仓库：扫描全部文本文件（跳过 gitignored 顶层目录）
        skip = {"data", ".workbuddy", ".git", "__pycache__", ".venv", "node_modules"}
        return [p for p in REPO.rglob("*")
                if p.is_file() and not (set(p.parts) & skip)]


def extra_blocklist() -> list[str]:
    f = REPO / ".privacy-extra.txt"
    if f.exists():
        return [ln.strip() for ln in f.read_text(encoding="utf-8").splitlines()
                if ln.strip() and not ln.startswith("#")]
    return []


def scan(files: list[Path]) -> list[str]:
    problems: list[str] = []
    blocklist = extra_blocklist()
    for f in files:
        rel = f.relative_to(REPO)
        if f.suffix.lower() in BAD_EXT:
            problems.append(f"[文件类型] {rel}: 数据文件不应提交")
            continue
        if f.suffix.lower() not in TEXT_EXT:
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if "config.example.json" in str(rel) and "LOCALAPPDATA" in line:
                continue  # 模板中的占位路径是允许的
            for rex, label in ((UUID_RE, "UUID"), (USERID_RE, "用户ID模式"),
                               (WINPATH_RE, "本机用户路径")):
                if m := rex.search(line):
                    if "<" in m.group(0):
                        continue  # <name> 等文档占位符允许
                    problems.append(f"[{label}] {rel}:{i}: {m.group(0)[:40]}")
            for word in blocklist:
                if word in line:
                    problems.append(f"[黑名单词] {rel}:{i}: ***")
    return problems


def main() -> int:
    files = staged_files()
    if not files:
        print("隐私扫描：无待提交文件")
        return 0
    problems = scan(files)
    if problems:
        print(f"❌ 隐私扫描失败，{len(problems)} 处命中：\n")
        for p in problems[:40]:
            print("  " + p)
        print("\n处理：删除/脱敏后再提交；确认误报可把该词加入白名单逻辑")
        return 1
    print(f"✅ 隐私扫描通过（{len(files)} 个文件）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
