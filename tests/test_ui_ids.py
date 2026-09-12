# -*- coding: utf-8 -*-
"""前端元素契约：app.js 里 $("id") 引用的 id 必须存在于 index.html。

`web/app.js` 用 `$("some-id")` 直接取 DOM 元素；取不到就是 null，
紧接着的 `.textContent` / `.hidden` 赋值会在运行时抛错，整块功能静默失效。
合并或重命名板块时最容易漏改这类引用——本文件是合并「每日战报」与
「对局明细」两个板块时补上的，用来守住这条契约。
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 前面不能是 - 或单词字符：否则 data-page-node-id="..." 会被当成 id="..."
_ID_RE = re.compile(r'(?<![-\w])id="([^"]+)"')
# 只取简单 id 形态的引用；带空格的（如 $(" #t-m tbody")）是选择器，不是 id
_REF_RE = re.compile(r'\$\("([^"\s]+)"\)')


def test_app_js_ids_exist_in_html():
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")

    html_ids = set(_ID_RE.findall(html))
    assert html_ids, "index.html 里没解析出任何 id，正则可能失效了"

    missing = sorted(r for r in set(_REF_RE.findall(js)) if r not in html_ids)
    assert not missing, (
        "app.js 引用了 index.html 中不存在的 id（取到 null 会在运行时报错）：\n  "
        + "\n  ".join(missing)
    )
