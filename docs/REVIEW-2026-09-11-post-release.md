# 发布后全项目复查（2026-09-11，v0.3.0 之后）

本文件是 v0.3.0 发布之后的独立复查记录，与同日 [REVIEW-2026-09-11.md](REVIEW-2026-09-11.md) 互补：那一份记录 R11 的修复过程，本份记录**发布之后仍然存在、且未进入任何 R 编号**的问题。

本轮只做检查、复现和登记，没有修改业务代码，也没有把下列事项标记为已修复。

## 结论

v0.3.0 的功能与数据正确性已经可用：工作区干净，全量测试 166 项通过，R11 修复全部落地并已发布。代码质量上也没有发现新的数据污染路径——SQL 全部参数化，日志解析的时序问题在 R11.1 已经封闭。

但有三类问题会让用户对"这个工具到底好不好用"产生落差，且都不需要新功能就能修：

1. **新用户第一次打开面板，看到的卡名是 `grpId:12345`**，而不是 README 承诺的中文卡名；
2. **每次启动都要重解析全部历史日志**（当前约 43 秒，且随归档单调增长）；
3. **文档已经和实际状态互相打架**，下一轮开发可能照着错误口径实施。

建议按下面的 A → B → C 顺序处理，A 和 C 成本很低，适合和下一轮功能一起进版本。

## 验证基线

- Python 全量测试：`python -m pytest tests/ -q` → **166 passed**（6 个 DeprecationWarning）
- 工作区：`git status --porcelain` 为空；标签 `v0.1.0`、`v0.2.0`、`v0.3.0`
- 发布包：`dist/mtga-play-draw-stats-v0.3.0-windows.zip`，92 个条目
- 当前资料库（只读核对）：对局 **10950**（log 111 + untapped 10839），含主将记录 **1829**（16.7%），games 12836，mulligans 12449，段位快照 381
- 归档日志：`data/archive/` 32 份 / **330 MB**

---

## A 级：影响新用户第一次使用

### A1. 发布包不含卡名数据，开箱即显示 `grpId`

**位置**：`dist/*.zip` 打包内容、`app/card_names.py`、`app/config.py::DEFAULTS`

**现状**：发布 ZIP 由已跟踪文件生成，**不含 `data/` 目录**；卡名的三个来源全部落在这里：

| 来源 | 路径 | 是否入库 |
|---|---|---|
| 卡名库（英文 + 中文） | `data/mtga_cards.db` | 否（`data/` 被 gitignore） |
| 译名目录 | `data/card_names.catalog.json` | 否 |
| 用户本地译名 | `data/card_names.zh.json` | 否 |

而 `DEFAULTS["card_sync_enabled"] = False`（`app/config.py:16`），后台同步线程不启动；`app/main.py` 只在 `card_sync_enabled` 为真时才挂 `_cards_sync_loop`。

**复现**（临时库，不传卡名库，模拟全新解压）：

```python
conn = store.connect(tmp / "s.db")          # 不传 cards_db_path
# 写入 1 场 Brawl 对局 + 对手主将 grp_id='12345'
stats.matchups(conn, root=tmp)
```

得到：

```text
对手主将显示为: grpId:12345
name_source: 英文回退
```

`app/stats.py:396-397` 在无卡名库时直接用 `'grpId:' || c.grp_id`；`app/card_names.py:78` 同样回落到 `f'grpId:{gid}'`。

**影响**：

- "对手主将档案""套牌 × 对手主将""每日战报的常遇主将"这些核心区块，对新用户全部显示成一串数字；
- README「功能」第 43 行把"中文卡名"写成已有能力，与开箱体验不一致；
- 断网用户（README 强调的默认离线场景）没有任何补名路径，除非自己找到牌库快照。

**顺带缺陷**：`app/card_names.py:73` 在**完全没有译名也没有英文名**时，仍把 `name_source` 标成"英文回退"，与展示的 `grpId:12345` 不符。

**修复方向**：

- 发版时附一份牌名快照（只含 grpId→名称，不含任何对局数据，不违反隐私承诺），或
- 首次启动引导用户二选一：开启 Scryfall 同步 / 指定本地牌库快照目录；
- 无论哪种，`name_source` 在无任何名称时应显示"缺译名（英文亦缺）"之类，不能写"英文回退"。

**验收**：全新解压后不改任何配置，打开面板能看到卡名（或看到明确的补全引导），而不是 `grpId`。

---

## B 级：启动成本与并发安全

### B1. 每次启动全量重解析全部日志，没有水位线

**位置**：`app/backfill.py::backfill` / `collect_sources`，`app/watcher.py::LogWatcher`

**现状**：`backfill()` 每次启动都重新解析全部来源（归档目录 + Player.log + Player-prev.log + 会话日志目录），逐条 `upsert_match`。它靠 `match_id` 幂等保证不重不漏，但**没有"这个文件已经处理到哪"的记录**。

**实测**（本机当前资料，只解析不入库）：

```text
归档 32 份 / 330 MB；抽样 3 份 / 18.7 MB 用时 2.4s
推算每次启动全量解析约 43s（不含入库）
```

另需加上 `Player.log`（3.98 MB）与 `Player-prev.log`（11.75 MB）——而且这两个文件**会被解析两遍**：`backfill` 读一遍，`LogWatcher` 又因为初始 offset 为 0 从头读一遍（`app/watcher.py:62-63`，`self._fp = _Fingerprint(self.path, size, 0)`）。

**影响**：

- 启动后约 45 秒内页面数据不完整，而 `start.bat` 的健康探测打的是 `/api/status`，它因为 boot 在后台线程会**立刻返回成功**，浏览器提前打开，用户看到的是半成品面板；
- 成本随归档单调增长（归档只增不减），一两年后可能变成数分钟；
- `data/archive/` 已占 315 MB，是工作区最大的一块。

**修复方向**：为每个来源记录水位线（文件指纹 dev/ino + 大小 + 最后处理的时间戳或字节偏移），启动时只处理新增部分；`LogWatcher` 初始 offset 从水位线接管，而不是 0。

**验收**：第二次及以后的启动，归档日志零重解析（或解析量与原文件增长量成正比）；日志不变时启动解析耗时接近 0。

### B2. 启动后台线程绕过数据库锁

**位置**：`app/main.py::_boot_tasks`（`app/main.py:297`）、`app/main.py::get_conn`

**现状**：API 端点统一走 `q()`，它在 `_db_lock` 内执行（`app/main.py:342-345`）。但 `_boot_tasks` 里：

- `store.tag_bot_decks(get_conn(), ...)` 直接用 `get_conn()`，**没有持锁**；
- `get_conn()` 本身也没有锁或双检（`app/main.py:43-47`），boot 线程和首个 API 请求可能同时创建连接。

`store.connect()` 用 `check_same_thread=False` 打开连接，设计前提是"配合 main.py 的全局锁"（`app/store.py:70`）。boot 阶段 API 已经可以服务，两条路径会**在同一个 sqlite3 连接对象上并发**。

**影响**：低概率但非零——可能出现 `cannot commit - no transaction is active`、游标读到另一条语句的中间状态，或连接泄漏（创建两个连接、其中一个永不关闭）。当前 45 秒的 boot 窗口正好是暴露面最大的时段。

**修复方向**：`_boot_tasks` 中所有库操作改为走 `q(...)`；`get_conn()` 用 `_db_lock` 做双检初始化。

**验收**：启动窗口内并发请求不产生 `last_error`；连接创建有且仅有一次。

### B3. `/api/retry_boot` 存在竞态

**位置**：`app/main.py:518-526`

**现状**：先读 `_state.get("booting")`，为假才起线程。线程真正把 `booting` 置为 `True` 是在 `_boot_tasks` 内部（`app/main.py:272`），两者之间有一个窗口。快速双击重试会并发启动两个 `_boot_tasks`，同时执行归档与回填。

**修复方向**：用锁 + 状态位原子置位，或改用只允许单实例的线程句柄判断。

**验收**：连续快速调用 10 次 `/api/retry_boot`，实际只跑一次 boot。

---

## C 级：工具链与文档一致性

### C1. 隐私扫描有覆盖盲区，且空暂存区会给出"通过"假象

**位置**：`tools/check_privacy.py:24-25`

**现状**：

- `TEXT_EXT = {".py", ".js", ".md", ".json", ".txt", ".html", ".yml", ".yaml", ".toml", ".cfg", ".example"}` **不含 `.bat` / `.cmd` / `.cjs` / `.ps1` / `.vbs`**。仓库里有 3 个 `.bat`（`start.bat`、`stop.bat`、`register_task.bat`）和 5 个 `.cjs` 测试脚本，**永远不会被扫描**。这三个 `.bat` 恰恰是含本机路径、端口、进程名的高风险文件。
- 暂存区为空时，`main()` 直接打印"隐私扫描：无待提交文件"并返回 0（`tools/check_privacy.py:82-84`）。这本身没错，但和"通过"共用同一出口，容易被读成"已检查且干净"。

**本轮实测**：全仓模式扫描 98 个文件，命中 1 处（`config.json` 中的真实玩家 ID）——该文件被 gitignore，属预期。也就是说**当前没有真实泄漏**，这是覆盖率问题，不是已发生的事故。

**修复方向**：补齐扩展名；无暂存文件时输出改为明确的"未扫描任何文件，请先 `git add`"，与"通过"区分开。

**验收**：在 `start.bat` 里故意写一个假 userId，扫描能命中。

### C2. 文档口径与实际状态不一致

| 文件 | 位置 | 现状 | 应为 |
|---|---|---|---|
| `docs/ROADMAP.md` | 第 3 行 | "R1—R10.3 已完成；R11.1—R11.5 已完成" | 补上 R11.6 |
| `docs/ROADMAP.md` | 第 40 行 | R11.6 状态「待开始」 | 已完成（v0.2.0 / v0.3.0 已发布） |
| `docs/REVIEW-2026-09-11.md` | 第 9-11 行结论 | "修复并核对历史数据前不建议发布当前工作区" | 与同文件 R11.1—R11.6「已完成」矛盾，需标注为"R11 之前的判断，已被后文替代" |
| `docs/VISION.md` | 第 28、48、49、76 行 | "双面／转化牌只显示正面名称"、"无基线整段隐藏" | 上一轮复查已点名，仍未更新；需按 R10 决策改写或标注为被替代的旧提案 |

**影响**：不影响运行，但会让下一轮开发按错误口径实施——尤其是 VISION 那两条，会直接引导出和现实现相反的功能。

### C3. 没有 CI，前端测试不在 pytest 收集范围内

**现状**：仓库无 `.github/`。`tests/` 下有 5 个 `.cjs` 页面脚本测试（`test_daily_ui.cjs`、`test_deck_ui.cjs`、`test_match_ui.cjs`、`test_opponent_types_ui.cjs`、`test_r9_ui.cjs`），pytest 不会收集它们，只能手动 `node` 运行。上一轮复查基线里"5 个前端 UI 脚本通过"也是手工跑的。

**影响**：改了 `web/app.js` 之后，跑一遍 `pytest` 会全绿，但前端回归可能已经坏了。

**修复方向**：加一个最小 CI（或在 `tests/` 加一个 `test_ui_runner.py` 用 `subprocess` 调 node），把 5 个 `.cjs` 纳入统一入口。

---

## D 级：观察与遗留

### D1. 数据修正有粘性，重跑回填无法纠正旧胜负

`app/store.py:209` 与 `:232-234` 都用了 `COALESCE(excluded.my_result, matches.my_result)` / `COALESCE(?, result)`：**已有值不会被新解析结果覆盖**。好处是防止半截数据冲掉完整数据，代价是 R11.2 之后若再发现历史串场，重跑回填也修不回来，必须走显式的更正通道。建议把这一点写进 DESIGN，避免下一轮误以为"重跑一遍就好"。

### D2. 数据覆盖现状（供 UI 文案核对）

10950 场里本机日志只有 111 场，10839 场来自 Untapped；Untapped 路径不含对手主将信息，所以**含主将记录仅 1829 场（16.7%）**。所有依赖主将的区块（对手主将档案、套牌 × 对手主将、构筑对手类型）都只在这个子集上有意义，UI 的覆盖率提示不能省。BO 模式分布：BO1 5117 / BO3 1301 / 未知 4532——"未知"占 41%，`match_mode` 的推断口径值得再看一眼。

### D3. 其他

- `@app.on_event("startup"/"shutdown")` 已废弃（`app/main.py:315,326`），测试输出里有 DeprecationWarning；建议迁到 lifespan。
- `store.connect()` 每次连接都跑全表 `_migrate` + `_refresh_match_modes`，实测 **130 ms**（其中 `_refresh_match_modes` 全表 33 ms）。当前规模可接受，数据量再上一个量级需要改成按需。
- 工作区残留：`.review-test-tmp`（无访问权限，gitignored）、`NVIDIA Corporation/`（gitignored）、`data/` 共 432 MB（archive 315 MB / untapped 44 MB / dev-deps 35 MB / backups 26 MB）。
- 未发现任何 `TODO` / `FIXME` / `HACK` 遗留标记。

---

## 建议拆分

| 编号 | 独立交付点 | 完成标准 | 建议顺序 |
|---|---|---|---|
| R12.1 | 开箱卡名可用 | 全新解压后不改配置即可见卡名或补全引导；`name_source` 文案不再误标 | 1 |
| R12.2 | 增量回填水位线 | 日志未变化时启动解析耗时接近 0；`LogWatcher` 从水位线接管 | 2 |
| R12.3 | 启动期并发安全 | boot 全程走 `_db_lock`；`retry_boot` 单实例 | 3 |
| R12.4 | 工具链与文档收口 | 隐私扫描覆盖 `.bat`/`.cjs`；ROADMAP/REVIEW/VISION 口径与实际一致；5 个 `.cjs` 纳入统一测试入口 | 4 |

## 完成定义

沿用项目约定：先确定口径和可验收输出，再改实现；自动测试和实际资料验证全部完成后才能标为已完成。个人日志、数据库和对局截图继续只保存在被忽略的 `data/`，不得写入公开文档或 Git 历史。
