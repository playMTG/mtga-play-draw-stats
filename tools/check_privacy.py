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

import argparse
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
USERID_RE = re.compile(r"\b[A-Z0-9]{20,}\b")
WINPATH_RE = re.compile(r"C:\\Users\\[^\\\"'\s]+", re.IGNORECASE)
BAD_EXT = {".db", ".jsonl", ".log"}
# 会被扫描内容的文本类扩展名。脚本类（.bat/.cmd/.cjs/.ps1/.vbs）也在仓库里，
# 同样可能夹带用户名或路径，必须一并扫（R12.4）
TEXT_EXT = {
    ".py", ".js", ".cjs", ".md", ".json", ".txt", ".html",
    ".yml", ".yaml", ".toml", ".cfg", ".example",
    ".bat", ".cmd", ".ps1", ".vbs",
}


def staged_files() -> list[Path]:
    try:
        out = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
            cwd=REPO, capture_output=True, text=True, check=True,
        ).stdout
        files = [REPO / f for f in out.splitlines() if f.strip()]
        return [f for f in files if f.exists()]
    except (subprocess.CalledProcessError, FileNotFoundError):
        return all_text_files()


def all_text_files() -> list[Path]:
    """扫描整个仓库（含未跟踪文件），跳过 gitignored 路径。

    用 `git ls-files --cached --others --exclude-standard` 取「未被忽略的
    已跟踪 + 未跟踪」文件，这样 config.json／data/ 这类本机私有文件不会
    一直刷屏——它们本来就不会被发布出去。
    """
    try:
        out = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
            cwd=REPO, capture_output=True, text=True, check=True,
        ).stdout
        files = [REPO / f for f in out.splitlines() if f.strip()]
        return [f for f in files if f.is_file()]
    except (subprocess.CalledProcessError, FileNotFoundError):
        skip = {"data", ".workbuddy", ".workbuddy-ai", ".git", "__pycache__",
                ".venv", "node_modules", "dist"}
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="提交前隐私扫描")
    parser.add_argument("--all", action="store_true",
                        help="扫描整个仓库（含未跟踪文件），而非仅暂存区")
    args = parser.parse_args(argv)

    files = all_text_files() if args.all else staged_files()
    if not files:
        # 空暂存区不是「通过」：这一句如果和通过共用出口，脚本在 CI 或
        # 「什么都没 staged」时都会静默绿灯，扫过一个空集合却看起来像扫过了（R12.4）
        print("⚠️  隐私扫描：暂存区为空，本次没有扫描任何文件")
        print("    请先 git add 再运行；若要扫描整个仓库，加 --all")
        return 2
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
