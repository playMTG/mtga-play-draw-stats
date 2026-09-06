# MTGA 先后手对局统计插件 — 设计文档 v1

> 2026-09-05 · 基于本机 `Player.log`（44MB，含 21 场完整对局）实测验证，非纸上谈兵。

## 0. 可行性实测结论

| 需求 | 日志依据（本机实测） | 结论 |
|---|---|---|
| 先后手判定 | `GameStateMessage.turnInfo`（965 条），首个 `turnNumber==1` 的 `activePlayer` 即先手方 | ✅ 可行 |
| 对局结果 | `finalMatchResult` × 21 场，含 `resultList`（scope/result/winningTeamId/reason） | ✅ 可行 |
| 对手信息 | `matchGameRoomStateChangedEvent` → `playerName`、`platformId`（2024-07 只删了 tag 字段，名字还在） | ✅ 可行 |
| **Brawl 对手主将** | `ZoneType_Command` 区 → `gameObjects` 含 `grpId`、`ownerSeatId`；实测抓到双主将（partner 两张牌同区） | ✅ 可行，需 grpId→卡名映射 |
| 调度统计 | `ClientMessageType_MulliganResp` × 87 条 | ✅ 可行 |
| 段位 | `RankGetCombinedRankInfo` → 当前 Gold 4 | ✅ 可行 |
| 套牌名（自己的） | `StartHook` 响应中 `DeckSummaries`，本机日志未见 `DeckSummariesV2` | ⚠️ M1 验证，失败则手动标注 |
| **对局精确时长** | 客户端 API 响应行自带 `"timestamp": "<epoch毫秒>"`，匹配开始/结束事件各一个，相减即得（实测 24 场：13s–729s） | ✅ 可行，历史日志同样适用 |

已确认废弃、不得依赖的字段（实测本机日志全为 0）：`GetPlayerCardsV3`（卡牌收藏）、`Inventory.Updated`（库存增量）、`LogBusinessEvents`（比赛结果）、MMR（2022-08 移除）。

当前对局构成：全部为 `Play_Brawl_Historic`（86 条 eventId），126 次投降结束，无轮抓数据（轮抓解析列为 P2 预留）。

## 1. 功能清单

### P0 — v1 核心
| # | 功能 | 说明 |
|---|---|---|
| 1 | 日志监听与解析 | 轮询 tail `Player.log` + 启动时全量回填**三个来源**（见下方"历史日志来源"）；括号深度计数提取 JSON；按 `match_id` 幂等去重 |
| 2 | 对局库持久化 | SQLite 单文件，按 `match_id` 幂等 upsert，重复解析不产生脏数据 |
| 3 | **先后手胜率看板** | 先手/后手各胜率、样本量、95% 置信区间（**Wilson 区间**，小样本下正态近似会越界，禁用）；按赛事、按自己套牌、按时间（周/月）细分 |
| 4 | **对手主将档案** | 每个对手主将一行：交手次数、总胜率、我方先手胜率 vs 后手胜率、我的主将；点击展开历史对局 |
| 5 | 调度统计 | 每局调度次数分布，调度次数 vs 胜率关联，先/后手分开统计 |
| 6 | 对局明细表 | 时间、赛事、对手、对手主将、先后手、回合数、结果、结束原因、用时；支持筛选与排序 |
| 7 | **异常对局记录** | 开局后极短时间内结束的对局自动打标（秒投/闪退/挂机）。判定阈值可配，依据实测数据划分（见下）；面板支持"排除异常局"开关——秒投局会污染先后手胜率（先手秒投负局实为排队遭遇问题，而非先手劣势） |
| 8 | **对手卡组类型打标** | 给对手套牌标注类型（快攻/控制/组合技/Ramp/中速/其他）。三层方案：① 手动——对局详情页下拉打标，一键套用到同主将历史对局；② 主将先验——Brawl 对手主将即最强类型信号，内置常见主将→类型映射表（仓库根目录 `commander_archetypes.json`，随代码分发、可编辑），新对局自动继承；③ 启发式（P1）——按对手已亮出的牌统计法术力曲线与功能牌密度自动分类（1-3费生物密度→快攻；扫场/反击→控制；加速咒语→Ramp）。与 Untapped 的做法一致（其数据模型即 `opponent_revealed_*` 字段，但公开 API 不提供分类结果，全为 null，Premium 才有） |
| 9 | **"你被针对了吗"评价** | 类抽卡游戏"欧非分析"的统计体检：把运气成分拆成四个可检验维度，算出 0–100 的**被针对指数**（越高越"非"）。方法论见 §3.5，所有维度附样本量与 p 值，小样本自动降权 |

### P1 — v2 增强
| # | 功能 | 说明 |
|---|---|---|
| 7 | 段位进度曲线 | 每场对局后的段位快照（Gold4 → …），涨跌可视化 |
| 8 | 中文卡名 | 主将名双语显示（英文为主，中文可选），本地缓存 |
| 9 | 数据导出 | CSV / JSON 全量导出 |
| 10 | 多账号隔离 | 按 userId 区分（防换号混淆） |

### P2 — 远期
- 轮抓（Quick Draft / 人轮）选牌与胜率（本机暂无数据，解析器预留事件位）
- 游戏内悬浮窗 Overlay（半透明置顶、鼠标穿透）
- 实时对局中提示（对手主将历史战绩弹窗——即"见了这主将该怎么打"）

## 2. 技术架构

```
Player.log ──> Watcher（500ms 轮询 tail + 启动全量回填）
                   │
                   v
             Parser（条目切分 [UnityCrossThreadLogger] / JSON 括号深度提取）
                   │
                   v
             事件分类器（对局生命周期 / 主将 / 调度 / 段位）
                   │
                   v
             SQLite（matches / games / commanders / mulligans / rank_snapshots）
                   │
                   v
        FastAPI（127.0.0.1 绑定，/api/* + 静态页）
                   │
                   v
        Web 面板（原生 HTML + Chart.js 本地文件，零 CDN、零外联，完全离线）
```

- **语言/运行时**：Python 3.13（本机 managed 版），依赖仅 `fastapi` + `uvicorn`（标准库为主，解析不依赖第三方库）
- **端口**：`127.0.0.1:8765`（仅本地回环，不监听外网——符合隐私原则）
- **数据库模式**：SQLite 开启 **WAL**——watcher/store 单写、FastAPI 多读，面板查询与解析写入互不阻塞
- **配置**：`config.json`（日志路径、端口、DB 路径、异常局阈值 `abnormal_max_duration_sec`/`abnormal_max_turns` 均可改）
- **卡牌库**：`data/mtga_cards.db`——本地 grpId→卡名映射（社区开源卡表导入 + `tools/update_cards.py` 手动更新）；未知 grpId 显示 `#96352` 兜底，不影响统计

## 3. 数据模型（SQLite）

```sql
matches     (id, match_id UNIQUE, source,     -- 'log'|'untapped'（跨源去重依据，见 §3.6）
             event_id, start_time, end_time, duration_sec,
             my_seat, opponent_name, opponent_platform,
             play_draw,                       -- 第 1 局先后手（BO1 即整场口径；BO3 逐局看 games）
             my_result, end_reason, total_turns, my_deck_tag,
             my_rank_class, my_rank_level, format_class,
             is_abnormal, abnormal_reason,   -- 'short_duration'/'few_turns'/两者
             opp_archetype_tag,              -- 手动覆盖的对手卡组类型
             opp_commander_name)             -- 冗余存储便于按主将聚合
opponent_profiles (commander_name PRIMARY KEY, archetype_auto, archetype_user,
                   updated_at)              -- 主将→类型映射，手动打标自动沉淀
games       (id, match_id, game_no, result, reason, duration_sec,
             play_draw)                      -- BO3 逐局先后手（每局换边，必须逐局记录）
mulligans   (id, match_id, game_no, seat, kept_on)                        -- kept_on=0 首抓即留
commanders  (id, match_id, seat, grp_id, card_name, colors, partner_idx)  -- 一场每人 1~2 行
rank_snapshots(id, ts, constructed_class, constructed_level, limited_class, limited_level)
```

关键判定逻辑：
- **先后手**：每局首个 `turnNumber == 1` 的 `turnInfo.activePlayer` 所在 seat = 该局先手；BO3 每局换边，**逐局判定写入 `games.play_draw`**，`matches.play_draw` 冗余存第 1 局值（BO1 即整场口径）
- **主将**：`ZoneType_Command` 区的 `objectInstanceIds` → `gameObjects` 中 `grpId` + `ownerSeatId`；同区 2 个实例 = 伙伴主将（`partner_idx` 0/1）
- **胜负**：`finalMatchResult.resultList` 中 `scope == MatchScope_Match` 的 `winningTeamId`；`MatchScope_Game` 行拆入 `games`
- **回合数**：该场最后一条 `turnInfo.turnNumber`
- **调度**：`MulliganResp` 按 `(match_id, game_no, seat)` 聚合计数
- **精确时长**：匹配开始（`MatchGameRoomStateType_Playing`）与结束（`MatchCompleted`）事件行的 `"timestamp"`（epoch 毫秒）相减；历史回填同样适用
- **异常对局**：`duration_sec ≤ abnormal_max_duration_sec`（默认 150s）**或** `total_turns ≤ abnormal_max_turns`（默认 2）即打标；阈值写入 `config.json` 可随时调整

### 3.6 统计口径约定（全面板统一，写死不漂移）

| 口径 | 约定 |
|---|---|
| 分母 | 胜率/被针对指数默认以 **match 层**为样本（一场=1）；`games` 层仅用于 BO3 换边分析与调度统计，不进胜率分母 |
| 异常局 | `is_abnormal=1` **默认排除**出一切胜率与被针对统计（只在明细表展示）；面板"包含异常局"开关切换后所有数字联动刷新 |
| 先后手 | 分母 = 该口径下 play/draw 各自的 match 数；BO3 用首局口径（与 BO1 同质） |
| 时间 | 存储一律 epoch 毫秒（日志自带 `timestamp`），仅显示层做本地化 |
| 实现 | 所有面板共用 `stats.py` 单一实现，**禁止前端各自重算**——口径只有一份 |

**跨源去重策略**：本地日志用 `matchId`，Untapped 用 `short_id`，两套 ID 不可比。处理：`matches.source` 标记来源；Untapped seed **只导入早于最早本地日志（2026-09-02）的对局**，重叠时段以本地日志为准（字段更全、含对手名与主将）——时间窗切分，简单且不会算重。

### 3.5 "你被针对了吗"——被针对指数方法论

灵感来自抽卡游戏的欧非分析：不问"我菜不菜"，只问"运气分布是否偏离统计预期"。四个维度独立检验，最后合成 0–100 综合指数（默认等权，可在 config 调整）：

| 维度 | 检验什么 | 统计方法 | "非"的表现 |
|---|---|---|---|
| **A. 先后手运** | 我方拿先手的比例是否偏离 50% | 二项检验（n=先手数+后手数，p₀=0.5） | 长期拿后手 |
| **B. 对手运** | 遭遇的对手主将/类型分布是否异常偏向克制我的类型 | 卡方检验：**滚动窗口对比**——近 30 天遭遇分布 vs 此前全部对局（基线随时间前移；若用终身基线，长期被针对会被历史平均掉）；再按"该对局我的历史胜率<40%"加权 | 总撞上克星主将 |
| **C. 起手运** | 调度次数、起手地数是否劣于超几何分布期望 | 观测调度率 vs 期望调度率（按套牌地数计算）；P1 接入起手具体牌张后升级为逐局地数分析 | 天天 1 地起手/卡地 |
| **D. 连败运** | 连败长度是否超出该胜率下的合理范围 | 给定整体胜率 p，计算观测最大连败长度的出现概率（负二项/模拟法） | 胜率 55% 却常年 7 连败 |

输出设计：
- **综合被针对指数 0–100**：四个维度各映射为 0–100（p 值越小、偏离越大分越高；p>0.10 一律视为"正常运"计 50 以下），加权平均
- **分段评语**（娱乐化文案，可配置）：0–30 欧皇 / 30–50 手气不错 / 50–70 正常人 / 70–85 有点邪门 / 85–100 建议卸载重装
- **每个维度独立展示**：观测值 vs 期望值对比条形图 + p 值 + 样本量；样本 <20 场的维度显示"样本不足"灰色态，不计入综合分
- **时间窗可选**：最近 7 天 / 30 天 / 全部，便于区分"这周点背"和"长期被针对"
- **诚实声明**：面板固定脚注——"MTGA 无公开的匹配操纵证据；本功能是统计自检+娱乐，小样本极易误报，样本量永远显示在结论旁边"

数据需求：全部基于既有字段（play_draw、mulligans、opponent_profiles、my_result），**P0 零新增采集**；维度 C 升级版需起手牌张（GRE `GameStateMessage` 手牌区，P1）。

### 异常局阈值划分依据（2026-09-05 实测 24 场）

时长呈明显双峰：短局簇 13–119s（10 场），正常局 153–729s（14 场），**119s 与 153s 之间有天然断档**，故默认阈值取 150s（二选一判定，另含回合 ≤2 的兜底，可捕捉"慢慢磨但极早结束"的局）。0 回合局实测 5 场（13–43s）：既有秒投胜（对手看到对局直接退）也有秒投负（我方跳对局），这正是需要单独记录、且默认从胜率统计中排除的原因。阈值后续随样本量增长在面板"时长分布图"上复核。

## 4. 目录结构

```
MTGA先后手插件/
├─ docs/DESIGN.md            本文档（脱敏后即为 GitHub 版）
├─ docs/PRIVACY.md           隐私说明（见 §9）
├─ .gitignore                data/、config.json 等一律不进仓库
├─ config.example.json       配置模板（占位符；复制为 config.json 后填本机信息）
├─ config.json               本机配置（gitignored，含日志路径/端口/阈值/被针对指数权重）
├─ requirements.txt
├─ app/
│  ├─ main.py                FastAPI 入口 + 启动回填
│  ├─ watcher.py             日志监听（tail）
│  ├─ parser.py              条目切分 + JSON 提取 + 时间戳
│  ├─ events.py              事件分类 → 结构化记录
│  ├─ store.py               SQLite 读写 / upsert
│  └─ stats.py               胜率/置信区间/被针对指数计算
├─ web/
│  ├─ index.html             单页面板
│  ├─ chart.umd.js           Chart.js 本地文件（无 CDN）
│  └─ app.js
├─ tests/                    解析器单测（合成日志片段，不含真实数据）
├─ data/
│  ├─ mtga_stats.db          对局库（自动生成，gitignored）
│  └─ mtga_cards.db          grpId→卡名映射（gitignored）
└─ tools/
   ├─ probe_log.py           日志探测脚本（开发期验证用）
   ├─ import_untapped.py     Untapped 全史 JSONL 导入（时间窗去重）
   ├─ analyze_history.py     赛制回填 + 全史分析报告（输出至 data/）
   ├─ update_cards.py        卡牌库更新（含 --zh 中文卡名）
   ├─ check_privacy.py       push 前隐私扫描（见 §9.4）
   └─ merge_untapped.py 等   Untapped 抓取期一次性脚本（发布前清理，见 P0 清单）
```

## 5. 里程碑

| 阶段 | 交付 | 验收标准 |
|---|---|---|
| **M1 解析核心** | watcher + parser + events + store + 仓库初始化（.gitignore/config.example.json/check_privacy.py）+ **合成日志单测**（tests/，从真实日志脱敏剪段，含字段缺失/损坏容错用例与滚动切换用例） | 回填三个日志来源并按 match_id 去重，入库 ≥70 场；主将识别正确（含伙伴双主将）；先后手逐局判定正确；单测全过（含 rotation 切换用例）；check_privacy 扫描通过 |
| **M2 看板** | FastAPI + 总览/先后手/明细三个面板 | 浏览器打开即见 M1 回填的全部对局（≥70 场）的先后手胜率 |
| **M3 主将档案 + 调度** | 主将表 + 调度面板 | 每个对手主将有先后手细分胜率 |
| **M4 增强** | 段位曲线 / 导出 / 中文卡名 | — |

## 6. 风险与对策

| 风险 | 对策 |
|---|---|
| WotC 持续删日志字段（2019→2024 已删 5 轮） | 解析器逐事件容错：单事件解析失败只跳过不崩溃；`store` 记录 schema 版本与解析统计，面板显示"解析健康度" |
| grpId 卡名库过时（新系列未收录） | 未知 grpId 显示 `#ID`；提供 `update_cards.py` 手动更新；统计不受影响 |
| 时间戳随系统 locale 变化（日/月歧义） | 支持 7 种已知格式逐一尝试；本地化时间仅用于显示排序，核心以消息顺序为准 |
| **Player.log 滚动**（MTGA 重启时被改名/重建，tail 失效） | watcher 记录当前文件指纹（路径+大小+读偏移）；检测到文件变小/重建即：先把旧文件（已成 Player-prev.log）剩余部分读完入库，再切到新 Player.log 从头回填——match_id 幂等保证不重不漏 |
| `DeckSummaries` 拿不到自己套牌名 | M1 实测；失败则 `my_deck_tag` 手动标注（对局表中一键打标） |
| MTGA 未开启详细日志 | 启动检测：日志无 JSON 游戏数据时，面板显著提示"请在 MTGA 选项→账户→勾选 Detailed Logs (Plugin Support)" |
| 被针对指数误报（小样本假阳性） | 每维度强制显示样本量与 p 值；样本 <20 灰色不计分；综合分随样本量收缩（见 §4.5） |

## 7. 历史日志来源与回填（2026-09-05 实测）

| 来源 | 路径 | 实测内容 |
|---|---|---|
| 当前会话 | `%LOCALAPPDATA%Low\Wizards Of The Coast\MTGA\Player.log` | 实时写入，tail 监听 |
| 上一会话 | 同目录 `Player-prev.log` | MTGA 启动时滚动覆盖 |
| **历史会话（关键）** | `C:\Program Files (x86)\Steam\steamapps\common\MTGA\MTGA_Data\Logs\Logs\UTC_Log - *.log` | 每会话一份，**含完整对局数据** |

实测回填量：UTC_Log 共 11 份（9 月 2 日—9 月 5 日），完成对局数 6+16+8+22+22 = **74 场**（今天的与 Player.log 重叠，按 match_id 去重）。含 `finalMatchResult`、`ZoneType_Command` 主将等全部事件，格式与 Player.log 一致。

- **边界**：MTGA 客户端自动清理旧日志，当前最早只到 9 月 2 日，更早的对局无法恢复（无服务器端导出渠道）
- **防丢机制（P0）**：watcher 启动时把 `UTC_Log` 目录中未见过的文件复制到 `data/archive/` 留存，客户端清理后插件库中数据仍在
- 时间戳：日志头无人类可读时间，但客户端 API 响应行（`{ "transactionId": ..., "timestamp": "<epoch毫秒>" ...}`）自带毫秒级时间戳，事件排序与时长计算均以它为准

## 8. Untapped 历史数据源（2026-09-05 打通）

档案设为公开后，其前端 API 可直接读取（无需登录），已抓取**生涯全史**：

```
GET https://api.mtga.untapped.gg/api/v1/games/users/{account_id}/players/{player_id}/?card_set={系列代码}
```

- `card_set` 按系列窗口返回该时段对局（需遍历多系列合并去重，按 `short_id` 幂等）
- 每场含：`match_start`、`event_name`、每局 `game_duration_seconds`、`active_player_id`（先后手）、`winning_team_id`、`friendly_deck_name/id`、段位 before/after、起手与调度、`opponent_revealed_colors/deckstrings`
- 实测规模：**10,000+ 场（2021-11 至今）**，Brawl 占八成以上——足以算出稳定的先后手基线（长期统计显示先手胜率显著高于后手，约 14 个百分点）
- 工具链：`tools/untapped_rebuild.js`（浏览器内聚合，账号 ID 从环境变量读取）→ 分批抓取（每批 ≤8 系列防限流）POST 到 `tools/dump_server.py`（127.0.0.1:8766）→ `tools/merge_untapped.py` 本地去重出报表
- 局限：`opponent_revealed_archetype` 公开接口全为 null；无逐场对手名（仅色组）；未登录会话对无头浏览器不稳定（SPA 频繁掉线，需分批+重试）
- 用途：本地插件的历史基线（日志只能回溯到 2026-09-02，Untapped 补齐此前全部）；**M1 完成后把 jsonl 导入 SQLite 作 seed 数据，按 §3.6 跨源去重策略执行（只导 2026-09-02 之前，`source='untapped'`）**

## 9. GitHub 开源规范（P0，与 M1 同步执行）

本项目以 MIT 协议开源。核心原则：**仓库里永远不出现任何用户的真实数据**——包括作者自己的。

### 9.1 隐私红线清单

| 类别 | 红线 | 处理方式 |
|---|---|---|
| 账号标识 | MTGA userId、accountId、屏幕名、对手真实名 | 一律不进仓库；运行时从 `config.json`（gitignored）或环境变量读取 |
| 本机路径 | 含 Windows 用户名的绝对路径 | 源码只用 `%LOCALAPPDATA%` 等环境变量拼接 |
| 对局数据 | `data/` 全目录（SQLite、jsonl、归档日志、Untapped 抓取） | 整目录 gitignore，绝不提交 |
| 示例数据 | README 演示截图/示例库 | 必须用 `tools/make_demo_data.py` 生成的**合成数据**（随机生成的虚构对局） |
| 个人战绩 | 文档中的个人胜率、段位、套牌名 | 文档用"示例/示意"表述，不引用真实个人数据 |

### 9.2 仓库结构

```
mtga-play-draw-stats/
├─ README.md                 中文为主 + English 简介段
├─ LICENSE                   MIT
├─ docs/DESIGN.md            本文档（已脱敏版）
├─ docs/PRIVACY.md           隐私说明：采集什么、存哪、为何零联网
├─ .gitignore                见 9.3
├─ config.example.json       配置模板（占位符，复制为 config.json 使用）
├─ requirements.txt
├─ app/ web/                 主程序
├─ tools/                    探测/导入脚本（全部参数化，零硬编码身份）
└─ tests/                    解析器单测（用合成日志片段）
```

### 9.3 .gitignore（核心条目）

```gitignore
data/            # 对局库、归档日志、Untapped 抓取、卡牌库——全部本地
config.json      # 运行时配置（含本机路径）
.workbuddy/      # 助手工作区记忆
*.log  *.db  __pycache__/  .venv/
```

### 9.4 提交前检查（CI 卡点）

`tools/check_privacy.py` 在 push 前扫描全部待提交文件，命中即失败：
- MTGA userId 模式（20 位大写字母数字）、UUID 模式、`C:\Users\<name>` 路径
- 数据文件扩展名（.db/.jsonl/.log）混入暂存区
- 建议配 GitHub Actions 跑同一脚本，双保险

### 9.5 代码规范

- Python：PEP 8，类型注解，模块职责单一（watcher/parser/events/store/stats 不反向依赖）
- 前端：无构建步骤，原生 ES Module；零 CDN、零外联是**硬约束**（README 与 PRIVACY.md 双重承诺）
- 提交信息：`feat|fix|docs|refactor: 简述`（英文），一个提交一件事
- 用户可见文案：中文为主（i18n 双语已降 scope 移除，英文用户可自行 fork）

## 9.6 M4 交付记录（2026-09-05）

- **段位曲线**：`/api/rank_curve?track=constructed|limited`。仅使用带时间戳快照
  （早期裸 JSON 行 ts=NULL 无法定位，不参与）；段位→单调数值刻度
  （Bronze4=1 … Diamond1=20，秘稀=21），相邻重复段位合并为一个台阶。
  面板支持构组/轮抽切换。
- **CSV 导出**：`/api/export?type=matches|ranks`，UTF-8 BOM（Excel 直开不乱码），
  遵循当前筛选条件（matches 支持排除异常局开关）。
- **中文卡名**：`mtga_cards.db` 增加 `name_zh`/`set_code`/`collector_number` 列
  （store.connect 挂载时幂等迁移旧库）。`tools/update_cards.py --zh` 走 Scryfall
  本地化路由 `cards/{set}/{cn}/zhs` 补全；Arena 编号带 `A-` 前缀的（如 A-Nadu）
  自动剥前缀回退查询。配置 `card_name_lang: "zh"`（默认）时前端与导出优先显示
  中文，缺中文印刷回落英文。
- **数据事实**：WotC 2023 年后的多数新系列（FIN/SPM/TDM/DFT/BLB/MH3 部分）已无
  简中印刷，这些卡保留英文名属数据现实，属预期行为。grpId 90800 不在 Scryfall
  arena 索引内，无法映射。

## 10. 已知事实备忘（2026-09）

- 日志路径：`%LOCALAPPDATA%\Wizards Of The Coast\MTGA\Player.log`（同目录 `Player-prev.log` 为上一会话；Steam 版另有安装目录 `MTGA_Data\Logs\Logs\UTC_Log-*.log` 历史会话，见 §7）
- 详细日志需在 MTGA 选项→账户→勾选 Detailed Logs (Plugin Support)
- 参考实现：manasight-parser（Rust, 活跃, MIT）、rconroy293/mtga-log-client（Python, 17Lands 官方）——仅参考事件名，本项目全部自研解析
- 本机个人信息（段位、账号、个人战绩）只存在于本地记忆与 data/，不进仓库

## 9.7 被针对指数 + 日志归档交付记录（2026-09-06）

### §3.5 被针对指数实现

- 新模块 `app/targeting.py`：零依赖统计原语（二项 CDF/SF 对称性加速、
  卡方生存函数=正则化不完全 Gamma（NR gser/gcf）、Feller 连败近似
  `1-exp(-N·p·q^L)`、p→分数 log 映射：p≥0.10→50，p≤1e-4→100）。
- `stats.targeting_index()`：A 先后手运（二项单侧，先手偏少）/ B 对手运
  （滚动 30 天遭遇类型分布 vs 此前基线卡方，低频类合并防新主将拉爆；
  附克星列表=窗口内 ≥3 场且胜率<40% 的主将）/ C 起手运（调度局占比 vs
  `mulligan_baseline`=10% 配置基线，单侧二项）/ D 连败运（最大连败
  vs 整体胜率下 Feller 期望）。样本 <`min_sample`(20) 的维度灰色态、
  不计入加权综合分。API `/api/targeting?window=7|30|all`。
- 局限（P0 已知）：Untapped 导入的场次无 mulligans/commanders 子表数据，
  维度 B/C 实际仅对日志对局有效；C 的 10% 基线是构组套牌经验值
  （起手 0/1/6/7 地率），按套牌地数计算留待 P1 起手牌张解析。

### mulliganResp 解析修正（重要数据事实）

- 真实日志的 `mulliganResp` 只有 `{"decision": "MulliganOption_Mulligan"|
  "MulliganOption_AcceptHand"}`，**没有 keptOn / playerSeatId**（旧解析与
  合成 fixtures 的臆造字段全为 NULL）。
- 新模型：每次 Mulligan 决策=调度一次（计数器）；AcceptHand 决策落一行
  `kept_on=已调度次数`（0=直接保留）。**mulligans 表一行=一局**，每局必有
  AcceptHand。seat 缺失时 upsert 填 my_seat（该事件仅出现在本地日志=我方）。
- 2026-09-06 前的旧行（kept_on 全 NULL、Keep/Mulligan 混杂不可区分）由
  `store._migrate` 删除并回填重建；查询层保留 `seat IS NULL OR seat=my_seat`
  兼容。注意 `MulliganReq`/`timerIds` 里的 "mulliganResp" 字符串是干扰项，
  只认带 `mulliganResp` 键的对象。
- 实测分布（79 场日志局）：kept_on 0×46 / 1×12 / 2×1（另 BO3 计 73 行）。

### 日志防丢归档

- `app/archive.py`：启动时把 Steam `UTC_Log-*.log` 复制到 `data/archive/`
  （同名同大小跳过，大小变化重拷）；回填来源优先归档目录，原始目录中
  与归档同名同大小的文件跳过解析。背景：客户端会自动清理旧会话日志，
  历史对局数据不可再生。
