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
# 兜底规则：[hidden]{display:none...}（允许 !important 与任意空白）
_HIDDEN_RULE_RE = re.compile(r"\[hidden\]\s*\{[^}]*display\s*:\s*none", re.IGNORECASE)


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


def test_hidden_attribute_rule_beats_display_classes():
    """`el.hidden = true` 必须真的藏得住元素。

    浏览器默认的 `[hidden]{display:none}` 来自 UA 样式表，作者样式里任何
    `display:grid` / `display:flex` 都会盖掉它——结果是 DOM 里 `hidden=true`、
    画面上照样显示（单元测试用的是假 DOM、没有 CSS，所以照不出来）。
    `app.js` 用 `.hidden` 切换显隐，因此页面必须自带一条兜底规则。
    `#daily-summary` 是 `.grid g3`，正是踩了这个坑才补的这条。
    """
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    # 先剥掉 CSS 注释：上面那条说明里就写着 `[hidden]{display:none}` 这个示例，
    # 不剥的话光靠注释就能让断言通过（空转验证时实测过）。
    css = re.sub(r"/\*.*?\*/", "", html, flags=re.DOTALL)
    assert _HIDDEN_RULE_RE.search(css), (
        "index.html 缺少 `[hidden]{display:none}` 兜底规则："
        "带 display:grid/flex 的元素用 el.hidden 将无法隐藏"
    )


# 用户反馈：「解释性的三角符号太多了，完全不是插件该有的东西」。
# 页面上只保留「展开看数据」的折叠（赛事对照表、评语依据、覆盖率、构筑版本变更…），
# 纯说明文字一律写进 docs/DESIGN.md。这几个标题就是当时删掉的那批，别再搬回来。
_EXPLANATORY_SUMMARIES = (
    "卡名显示与译名纠正",
    "主将类型来源",
    "如何纠正本地译名",
)


def test_no_explanatory_folds_in_page():
    """页面上不应再有「只讲道理、不给数据」的折叠入口。"""
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    # 先剥 HTML 注释：注释里若举了 `<summary>…</summary>` 的例子就会被当成真入口。
    # （当前注释里没有这种例子，实测剥不剥都一样；这一步是防以后加例子。）
    body = re.sub(r"<!--.*?-->", "", html, flags=re.DOTALL)
    summaries = re.findall(r"<summary[^>]*>(.*?)</summary>", body, flags=re.DOTALL)
    assert summaries, "没解析出任何 <summary>，正则可能失效了"
    leftover = [s for s in _EXPLANATORY_SUMMARIES if any(s in text for text in summaries)]
    assert not leftover, (
        "index.html 里又出现了纯说明性的折叠入口（说明应写进 docs/DESIGN.md）：\n  "
        + "\n  ".join(leftover)
    )
