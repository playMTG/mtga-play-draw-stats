# -*- coding: utf-8 -*-
"""前端静态契约：id 引用、`hidden` 兜底、折叠入口，以及**没有死函数**。

`web/app.js` 用 `$("some-id")` 直接取 DOM 元素；取不到就是 null，
紧接着的 `.textContent` / `.hidden` 赋值会在运行时抛错，整块功能静默失效。
合并或重命名板块时最容易漏改这类引用——本文件是合并「每日战报」与
「对局明细」两个板块时补上的，用来守住这条契约。

2026-09-13 追加「没有死函数」：`barChart` / `matchDetails` / `dimVerdictColor`
三个函数在调用点被删掉后仍留在文件里，其中 `matchDetails` 还被
`test_match_ui.cjs` 断言着——**测试守着一个页面永不调用的函数**，是假覆盖。
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
# app.js 顶层的函数定义与箭头常量定义（`const name = (...) =>`）
_TOP_DEF_RE = re.compile(
    r"^(?:async\s+)?function\s+([A-Za-z_$][\w$]*)"
    r"|^(?:const|let)\s+([A-Za-z_$][\w$]*)\s*=",
    re.MULTILINE,
)
# 浏览器/DOM 全局，天然只出现一次，不算死代码
_EXTERNAL_NAMES = {"$", "Chart"}


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


# 用户口径演进：先是「解释性的三角符号太多」→ 只保留「展开看数据」的折叠；
# 2026-09-14 看过实际页面后进一步明确「这些能点开的三角完全没必要」。
# 所以现在页面上一个折叠都不留，想看细节去对局明细或导出 CSV。
def test_no_folds_in_page():
    """`index.html` 里不应再有任何 `<details>` 折叠。

    比逐个列标题更结实：只要出现折叠就报错，不用维护「哪些标题算说明性」。
    唯一允许保留的 `<details>` 是 `app.js` 动态生成的对手类型打标控件
    （`arch-edit`）——它是输入控件、不在页面初始 DOM 里，也不是「点开看数据」。
    """
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    # 先剥 HTML 注释：注释里若举了 `<details>` 的例子就会被当成真折叠。
    body = re.sub(r"<!--.*?-->", "", html, flags=re.DOTALL)
    folds = re.findall(r"<details[\s>]", body, flags=re.IGNORECASE)
    assert not folds, (
        f"index.html 里又出现了折叠（<details> × {len(folds)}）："
        "页面口径是一个折叠都不留，说明写 docs/DESIGN.md、细节看对局明细"
    )

    js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    js_folds = re.findall(r"<details[^>]*class=\"([^\"]*)\"", js)
    assert js_folds == ["arch-edit"], (
        "app.js 里动态生成的折叠只允许保留对手类型打标控件（arch-edit），"
        f"实际是：{js_folds}"
    )


def test_no_dead_top_level_definitions_in_app_js():
    """app.js 里不该有「定义了但文件内部没人引用」的顶层函数／常量。

    浏览器只加载 app.js，`index.html` 也没有内联事件处理器（全部走
    `addEventListener`），所以只被 `.cjs` 测试引用的函数同样是死代码——
    而且更坏：它让测试看起来在守某个功能，实际页面永不执行那段代码。
    本机踩过的三个：`barChart`（连同只给它用的误差线插件 `ciPlugin`）、
    `matchDetails`、`dimVerdictColor`，调用点分别在 `396677b` 与 `66be77d` 被删。
    """
    js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    defined = [a or b for a, b in _TOP_DEF_RE.findall(js)]
    assert len(defined) > 30, f"只解析出 {len(defined)} 个顶层定义，正则可能失效了"

    dead = []
    for name in defined:
        if name in _EXTERNAL_NAMES:
            continue
        # 定义处本身算一次，所以「只出现一次」= 没有任何引用点
        if len(re.findall(r"\b" + re.escape(name) + r"\b", js)) <= 1:
            dead.append(name)
    assert not dead, (
        "app.js 里这些顶层定义没有任何引用点（删掉，或把调用点接回来）：\n  "
        + "\n  ".join(sorted(set(dead)))
    )
