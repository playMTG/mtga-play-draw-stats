# MTGA 对局统计：当前设计

更新：2026-09-10。本文替代早期综合运气指数方案。

## 产品范围

支持日志与导入记录中的争锋、构筑、轮抽、现开及其他赛事。主将维度只适用于主将赛事；不能把其他赛事没有主将算作识别失败。目标是可核验的战报与体感校准，不判断匹配系统的意图。

## 数据与可靠性

日志 → parser / SessionBuilder → SQLite → stats / insights → FastAPI → 本地网页。数据、日志归档、卡名缓存和个人配置留在本机。

- matches 以 match_id 幂等写入；games 按场次和局号、mulligans 按场次局号座位、commanders 按场次座位卡牌 ID 合并。不完整回放保留已有子记录。
- 监听器检查文件身份、大小和开头指纹。轮换时重置解析状态；未结束的物理行等换行后再解码。写入失败回滚并保留待重试记录。
- 本地套牌来自对应赛事的 CourseDeckSummary / CourseDeck；不随意把账号下的任意套牌附到对局。保存名称、ID 和构筑指纹。
- 未知先后手、结果、调度、日期单独计数。未知调度不等于零调度。
- BO3 的 matches 是整场胜负、首局先后手；games 保留逐局资料。不要把场数当成游戏局数。

## 统计与界面

所有统计由后端计算，赛事大类、具体赛事、BO 模式、套牌、Bot 筛选统一传递。日报按服务所在电脑的本地自然日；近 N 天包含今天共 N 个自然日。全史包括未知日期，近期窗口不包括未知日期。

日报展示胜负、已知先后手与未知量（**2026-09-14 起不再展示常遇主将和逐赛事拆分**——用户口径「罗列数据全都没必要」，整块 `#daily-events` 已删）。不同主将数不等于不同玩家数。明细默认按时间分组，每页 200 场，可翻阅全部记录，也可按赛事、套牌、主将分组；分组计数只表示当前页。

近期分析不合成总分：先后手与 50% 简单模型作双侧比较；调度和对手构成须明确选择同赛事、同套牌，并有一致版本及窗口之前的非重叠基线。样本数、期望频数不足或版本混合时只描述资料，不推断。全史没有此前基线，因此不做这两项历史比较。连败只描述实际最长连败。p 值不是被针对概率，多次比较可能偶遇小 p 值。

本地和 Untapped 构筑统一到 titleId 身份空间，按各区数量生成 title-v1 指纹。未知卡牌映射保留 local 前缀，不能跨来源强行合并。未知版本也不能当作一致版本。

空日期（首屏默认落在「今天」，而当天往往还没打牌）只保留「没有已记录对局」的说明、跳转入口和跨日累计的连续纪录。当天胜率／先手率／后手率三张卡在空日恒为 `–%`、`0 场`，是零信息，直接隐藏；口径仍默认「今天」不变（见 R1）。跳转入口只在所选日期确无对局时出现。

前端约定：浏览器默认的 `[hidden]{display:none}` 来自 UA 样式表，作者样式里任何 `display:grid`／`display:flex` 都会盖掉它——结果是 DOM 里 `hidden=true`、画面上照样显示，而前端单元测试用的是假 DOM、没有 CSS，照不出来。`web/index.html` 因此自带一条 `[hidden]{display:none!important}` 兜底，凡是用 `el.hidden` 切换显隐的元素都依赖它。`tests/test_ui_ids.py::test_hidden_attribute_rule_beats_display_classes` 守住这条规则（匹配前先剥掉 CSS 注释，否则说明文字里的示例写法就能骗过断言）。

## Untapped 补全

旧 JSONL 扁平记录丢掉了原始主将与起手信息。`app/deckstrings.py` 解析原始 deckstring 的主将元数据，并区分伙伴与主将。其 titleId 必须借助公开卡表转换为 Arena grpId，不能直接当作 grpId；双面卡归到主要牌面。

`python -m tools.enrich_untapped` 默认预览；加 `--apply` 才备份后写入。输入为 `data/untapped/raw_b*.json`、公开卡表 `cards-review.json` 和英文名称 `loc-en-review.json`。只匹配库中既有导入 ID，不创建新对局；不更改 matches 的胜负或先后手。原始记录缺失、跨源重叠跳过的记录不会猜测补全。请保留原始文件，只有旧扁平文件无法恢复已经丢掉的字段。

## 隐私与开发

默认 `card_sync_enabled=false`。主动启用时查询 Scryfall 公开卡名；手动 Untapped 抓取会访问第三方服务。不会自动调用大模型。个人数据库、报告、账号与日志不得提交。

安装 requirements.txt 和 requirements-dev.txt 后运行 `python -m pytest tests -q`。测试使用合成记录；更改解析或持久化时必须覆盖残缺回放、重复执行、未知字段与赛制筛选。

## 后续范围

抽牌体验仍需完整套牌、起手、抽牌和检索/滤牌过程的采集与分类；目前不能回答关键 Ramp 牌为什么未抽到。优先统一跨源构筑指纹并提供可比版本筛选，再推进逐局抽牌分析。大模型仅适合未来可选的汇总解释，不是日报的前置条件。


## 日报历史比较（本轮新增）

日报比较基线为所选日期之前 30 个自然日，排除当天及未来资料。构筑按具体赛事、BO 模式、同名套牌及构筑版本分组；限赛按具体赛事（保留系列与规则）及 BO 模式分组，明确套牌池不同的限制。每组历史至少 20 场有胜负才算可比。按当天各组场数加权历史胜率，仅在可比子集计算差值，显示覆盖分母，不把这个差值解释成因果。

日报列出 BO1、BO3、未知三组整场战绩。传统赛事或已观察到多局的对局归 BO3，只有已明确支持的单局赛事归 BO1；不会因为只记录了一局便认定 BO1。未知赛事规则保留未知并排除比较。近期窗口同样返回分层战绩比较，原先调度和主将分布的推断继续采用更严格的单版本条件。

专属展示：非主将赛事不参与主将近期分析；日报有非主将赛事时显示已有对手类型标签及覆盖率，没有标签时不自动猜测类型。

尚未完成：跨不同赛事名称的限赛规则规范化、每日变化的可靠原因归因。当前差值是描述性比较，不是“下降由某模式导致”的因果结论。（2026-09-13 修正：原句还列着「构筑对手类型采集/分类流程」，那是 2026-09-09 写下的；R10.2 已在 09-10 落地**手动**标注流程。**自动分类仍不做**——既定口径是「未标注时不自动猜测」，所以这不是欠账，是排除项。）


## R1 每日一句评语

评语使用所选日期和筛选范围内的事实，无需历史或大模型。单场直接描述结果和先后手；多场从候选事实里按固定优先级取最多两条：场次（肝度）、高胜率、连续先后手（legendary 级优先）、先后手偏斜、重复主将。大场次（≥15 场）时弱信号会被丢掉，只留真正突出的。重复主将里，「连续 N 把撞上同一个人」换成更重的说法（见「收尾 2026-09-12 界面减负」第 2 条）。并列主将按稳定 ID 排序，避免刷新时随机变动。

未知先后手不计入全先手/全后手声明；主将亮点只统计适用赛事，缺失主将不猜测。评语不推断技术、逆风翻盘或平台意图。有对局但没有任何突出信号时返回空列表，`plain` 留空、前端隐藏该段落——不再兜底成「已记录 N 场，X 胜 Y 负」（那个数字下方统计卡已逐项列过）。

API 返回评语类别、相关场数、范围分母、对应对局 ID 及只读证据字段。页面“查看评语依据”展开逐场记录。日报的 BO 模式行只在存在模式拆分（≥2 种）时显示，单一模式不重复当天总数（见「收尾 2026-09-12 界面减负」第 1 条）。空日期可跳至当前筛选下最近有记录的一天。请求序号及范围校验防止较慢的旧请求覆盖新日期或筛选。

验证：`python -m pytest tests -q`；`node tests/test_daily_ui.cjs` 验证日报旧请求及筛选范围变化；`node --check web/app.js` 检查语法。


## R2 先后手主要指标与连续纪录

日报将当天胜率、先手率、后手率并列展示，先后手比例只以已知先后手为分母；全史概览将总胜率、先手率、后手率并列，并把先手时/后手时胜率明确作为另一组指标。全史概览沿用有结果对局口径，日报保留待确认结果的记录。

连续统计基于当前筛选内的比赛首局，以 start_time 排序。当前连续统计到所选日末，可跨天，且排除之后的记录。（**2026-09-14 起页面上只显示这一条**：「当天最长」「历史最长」和末场时间都不再显示——它们是复述，用户口径「罗列数据全都没必要」。后端 `play_draw.history_streaks` 仍在算，接口字段没变。）

未知先后手会打断连续段；相同时间的记录无法确定次序，也打断连续段。若范围内存在日期未知的记录，不输出该范围的最长或当前连续，避免跳过未知位置后虚构连续。空范围显示无记录。不会为这些连续纪录计算被针对概率。

测试包含切换先后手、未知末场、空样本、比例分母、日期缺失、同时间顺序、跨天、历史截止、赛事筛选与 BO3 首局口径。

首页 HTML 与业务脚本响应使用 `Cache-Control: no-store`，防止本地升级后旧 HTML 与新脚本混用。R2 实际页面验收覆盖日期切换、轮抽空日报和窄屏指标布局。

## R3 赛事中文化

`app/event_names.py` 统一提供展示名称，概览图表、赛事筛选、日报、历史比较、评语证据和明细均使用同一映射。原始 event_id / key / value 保持不变；按赛事分组仍以原始 ID 为键。CSV 保留原始赛事编号便于外部处理。

名称包含已识别的赛事类型、系列及日期／版本后缀；未识别部分原样保留，完全未知的赛事显示原编号，缺失值显示“赛事未记录”。赛事中文是项目描述性译名，不声称所有名称与官方客户端逐字一致。传统赛事不再显示误导的“双备牌”。

页面可展开中文／原文对照，悬停赛事文字或图表可查原编号。`data/event_names.zh.json` 支持原始编号到自定义中文的映射，保存后刷新生效，删除条目恢复内置名称；文件缺失、损坏或非法值安全回退。纠正方法就是上面这条，不再单独放进页面（见「收尾 2026-09-12 界面减负」第 3 条：页面只放数据）。

系列名称核验来源：
- [斑隆洛](https://magic.wizards.com/zh-Hans/news/announcements/a-first-look-at-bloomburrow)
- [光雷驿镖客](https://magic.wizards.com/zh-hans/products/outlaws-of-thunder-junction)
- [神河霓朝纪](https://magic.wizards.com/zh-Hans/products/kamigawa-neon-dynasty)
- [多明纳里亚：众志成城](https://magic.wizards.com/zh-Hans/news/feature/dominaria-united-product-overview-2022-08-18)
- [邪军压境](https://magic.wizards.com/zh-Hans/news/feature/collecting-march-of-the-machine)

验证覆盖未知赛事、缺失值、特殊后缀保留、本地覆盖与损坏回退，以及同中文名不同赛事不合并、筛选仍用原始 ID、各 API 显示一致和历史记录不改写。

追加核验：[暮悲邸：鬼屋惊魂](https://magic.wizards.com/zh-Hans/products/duskmourn-house-of-horror)、[新卡佩纳：喧嚣黑街](https://magic.wizards.com/zh-Hans/news/feature/streets-of-new-capenna-mechanics)、[兄弟之战](https://magic.wizards.com/zh-Hans/products/the-brothers-war)、[非瑞克西亚：万界归一](https://magic.wizards.com/zh-Hans/products/phyrexia-all-will-be-one)、[斯翠海文](https://magic.wizards.com/zh-Hans/products/strixhaven)、[依夏兰迷窟](https://magic.wizards.com/zh-Hans/products/the-lost-caverns-of-ixalan)、[卡洛夫庄园谋杀案](https://magic.wizards.com/zh-Hans/products/murders-at-karlov-manor)。繁体来源按简体显示。PickTwoDraft 使用“选两张轮抽”，纠正原来的“二选一轮抽”。未核验系列保留代码。

### 2026-09-13 核验：赛事类型译名四项 + 系列名补齐

**四项赛事类型译名**的代码改动早已落地（`EXACT` 的 `Play_Brawl_Historic`＝史迹争锋、`Play_Brawl`＝标准争锋；`PREFIXES` 的 `MWM_`＝周中、`Yargle_Day_`＝雅骨尔日；`TERMS` 的 `Momir`＝莫秘维），本轮补齐的是**来源**，确认不是凭口述定的：

- **史迹争锋／标准争锋**：官方赛制页作[「争锋赛」](https://magic.wizards.com/zh-Hans/formats)（Brawl）。这两个模式本身没有排位，去掉「（非排位）」是对的。同页的「纯普赛」也印证了既有的「史迹纯普」写法。
- **周中**：客户端本地化库（`Raw_ClientLocalization_*.mtga` 的 `Events/Event_Cat_MWM_*`）里官方英文事件名是 `Midweek Magic`；社区中文站[十七地](https://shiqidi.lenitatis.com/calendar)作「周中万智牌」——「周中」是它的简称。
- **莫秘维**：Paratranz 译名库 stage=9（官方级）作「莫秘维」（`DIS·110 Experiment Kraj` 等多处风味文字署名）；十七地的赛事名同作「莫秘维」。原「莫米」是不完整译名。**注**：官方赛制页把 Momir Basic 写作「莫秘基本地」，短了一截；赛事与卡牌一律用「莫秘维」，本插件跟随后者。
- **雅骨尔日**：Paratranz stage=9 作「雅骨尔」（`2X2·384 Muldrotha` 风味文字）；真卡 `PSSC·4 Happy Yargle Day!` 译「雅骨尔日快乐！」；客户端 `Achievements/UI/YargleDayAchievementsHeader` 英文为 `Yargle Day`；十七地赛事名同作「雅骨尔日」。

**系列名补齐**：核验中发现「未核验系列保留代码」这条口径让一批**官方中文站已给过中文名**的系列还显示代码，一并补入 `SETS` 六个（来源均为官方中文站，繁体来源按简体显示）：

| 代码 | 英文 | 中文 | 来源 |
|---|---|---|---|
| HOB | The Hobbit | 霍比特人 | [孩之宝中国 WPN 产品页](https://www.cnwizards.com/products)（2026.08） |
| SOS | Secrets of Strixhaven | 斯翠海文的秘密 | 同上（官方产品卡作「斯翠海文的祕密」，简体归「秘」） |
| TMT | Teenage Mutant Ninja Turtles | 忍者神龟 | 同上（2026.03.06） |
| TLA | Avatar: The Last Airbender | 降世神通：最后的气宗 | 同上 + [官方导航](https://magic.wizards.com/zh-Hans/products) |
| FIN | Final Fantasy | 最终幻想 | [官方产品页](https://magic.wizards.com/zh-Hans/products/final-fantasy)（标题用 IP 原名，正文与产品系列名一律《最终幻想》） |
| HBG | Alchemy Horizons: Baldur's Gate | 炼金新篇：博德之门 | MTGA 官方公告译文（2022-07-14，旅法师营地／头条同文） |

**仍保留代码的六个**（ECL 94 场、EOE 52、FDN 36、YECL 7、SIR 4、DBL 4）：官方中文站对这些系列**只给英文名**——`Lorwyn Eclipsed`、`Edge of Eternities`、`Foundations` 在官方产品页与「最新产品」列表里都是英文（实测 `…/products/edge-of-eternities` 全篇用英文系列名）。社区译名互相冲突（Lorwyn Eclipsed 有「洛温：蚀」「洛温：日蚀」两说，Edge of Eternities 有「虚空边域」「永恒边缘」两说，Foundations 有「基石构筑」「初创」两说），按「不凭口述直接改」的口径保留代码，等官方给出中文名再补。守卫 `tests/test_event_names.py::test_unverified_sets_keep_their_codes` 钉住这条。

## R4 主将与卡牌中文化

`app/card_names.py` 是显示名称与元数据的共用入口。主将档案、日报与证据、近期观察、明细和 CSV 使用该映射。返回中文、英文、grpId 和译名来源；页面主将名称可展开，其他位置悬停回查。

优先级：按 grpId 的本地纠正 > 已导入中英文目录 > 旧卡名缓存 > 英文 > grpId。`card_name_lang=en` 使用英文；日报与主将档案遵循相同配置。旧缓存无法追溯的中文明确标注“来源未记录”。本地纠正文件 `data/card_names.zh.json` 格式为 `{"123":{"name_zh":"我的译名","source":"出处说明"}}`，保存刷新生效；社区或自定译名不冒称官方译名。

`python -m tools.import_card_names --source <快照目录>` 从本地 ParaTranz 中英文快照生成 `data/card_names.catalog.json`。导入按英文牌名、系列与收藏编号优先精确对齐到 Arena grpId；同英文名存在冲突且无法定位印刷时不猜测。默认只收录 stage 5 及以上译名，机器候选保留英文。当前验收快照 `2026_09_09_15_01_23_f88612` 含 533 个牌名文件和 39,694 条记录，匹配当前 Arena 卡名库 16,034 个 ID 中的 16,026 个。

双面、连体、历险、隔间等多名称牌只需至少一个名称命中；已命中部分显示中文，缺失部分保留英文，并把“部分译名”与命中面数写入来源。统计仍以整张牌的 grpId 为身份。`tools.sync_card_names` 保留为显式在线补漏工具，不由本地导入自动触发，也不改写战绩。

统计身份仍为原始 grpId：不同印刷、重平衡版本、双面卡记录不因同名自动合并。既有导入器明确链接正反面的规则保持；本项不进行身份迁移。修复了日报常遇主将、近期低胜率主将和明细分组原先按显示名合并的问题。名称下载不把 A- 重平衡卡冒用为原版印刷，旧同步也不再剥掉 A- 编号查原版。

验证包括多名称牌单面命中与英文回退、重平衡卡精确译名、中文／英文选择、本地覆盖／坏文件回退、低阶段译名跳过、冲突名称按印刷定位、无卡库回退、同名不同 ID 分开计数与展示。测试隔离个人卡名目录，避免本地目录污染合成数据。

## R5 我方套牌、主将与明细减负

对局明细的固定列为时间、赛事、我的套牌、我的主将、先后手、结果、对手、对手主将和详情。回合、用时、我方调度、结束原因、来源与对局编号移入每场的展开详情；有资料时再显示套牌 ID、构筑版本、Bot 与异常诊断。未知资料不占据主表，也不会从数据库删除。CSV 增加“我方主将”列并保留诊断列。

我方主将只来自明确身份资料。本地日志在争锋赛事匹配且我方座位可确认后，读取 `CourseDeck.CommandZone`；争锋的 GRE 主将区仍可补充双方主将。其他赛制的特殊指令区对象不作为主将，旧记录即使残留此类对象也不会在明细显示。Untapped 历史只读取 `friendly_deckstring` 的 commander 段，并按公开卡表将 titleId 精确映射到 Arena grpId。伙伴不会作为主将，套牌名称不会用于推断，无法解析或映射的记录保持“未记录”。同一主将在双方出现时按座位分别保存。

历史补全只匹配数据库中既有的 Untapped 精确合成 ID，执行写入前先备份，并断言总对局数不变。2026-09-09 实际补全后仍为 10,945 场：Untapped 争锋 1,775 场中我方主将已知 1,740 场、对手主将已知 1,605 场；日志争锋 65 场双方各已知 65 场。余下缺口表示原始资料没有可采信的主将身份，不由套牌名填充。

测试覆盖日志 `CommandZone`、Untapped 牌组编码、重复执行、同名双方主将、未知主将不猜测、明细 API、CSV 和折叠详情。实际页面需确认固定列、中文卡名、展开诊断及浏览器控制台无错误。

## R6 套牌独立详情与身份

对局明细中的套牌名称可点击；套牌筛选选中名称后也可进入详情。详情是页面内的独立对话框，时间范围支持今天、昨天、近 20 场、近 7 天和全部，默认近 20 场。汇总场数包含结果待确认的记录；胜率只以胜负已知为分母；先手率和后手率只以先后手已知为分母。范围内记录最多展示最近 200 场，汇总仍计算全部并明确是否截断。

套牌身份不使用显示名称直接合并。每场记录的 `my_deck_id` 与 `my_deck_version` 作为身份图节点：共享任一可靠值的记录相连，并继续沿另一个字段连接，支持同一 ID 改名／改版及相同构筑指纹连接本地日志与 Untapped。相同名称但 ID 与版本均不相连的记录排除，并显示未合并数量。完全没有 ID 和构筑指纹时才按名称回退；名称入口若对应多个互不相连的可靠身份，进入最近使用的一组并明确说明。

默认汇总身份中的全部构筑版本，页面显示已知版本数量和未记录版本数量；版本按最近使用时间编号，可限定单一版本或仅看版本未记录。原始构筑指纹保留在选项提示中。跨版本整体仅用于战绩和遭遇复盘；调度、抽牌等依赖构筑一致性的比较仍需限定单一版本。

API 为 `/api/deck_detail`，身份锚点、时间范围、版本选择和 Bot／异常排除均由后端处理，首页赛事筛选不限制套牌整体详情。合成测试覆盖跨来源版本桥接、改名、同名隔离、名称回退、五种范围、版本筛选、Bot 排除和参数校验；真实资料验证常用套牌能连接本地日志与 Untapped。

## R7 我方套牌 × 对手主将

套牌详情在当前身份、时间范围与构筑版本内统计对手主将。只有 `event_id` 属于争锋的对局进入适用分母；非争锋对局不算主将缺失。页面分别显示适用场数、对手主将已知场数、未记录场数和不适用场数。每位主将的出现占比以“对手主将已知场数”为分母，同时保留占全部适用场数的后端字段供后续使用。

主将身份始终为原始 Arena grpId，中文名只负责显示。每场先按 grpId 集合去重，因此重复解析行不会重复计数；双主将／伙伴主将会让同一场分别进入两位主将的行，页面明确提示占比总和可能超过 100%。主将出现次数表示对局数，不表示遇到的不同玩家数。

每行返回出现对局数、已知分母占比、先手／后手／未知局数、胜负／待确认数、总胜率及分先后手胜率。胜率只以结果已知为分母，先后手胜率同时要求对应先后手与结果已知。没有主将资料时保持空状态，不从对手名、套牌名或卡牌显示名猜测。

`/api/deck_detail` 接受可选的 `opponent_commander` grpId。未选择时记录区仍为范围预览，全部范围最多显示最近 200 场；选择后返回当前套牌、范围和版本内该主将的全部对应对局，不应用 200 场上限。双主将对局会在记录中显示该场所有已知对手主将，并可一键恢复全部记录。

合成验证覆盖非争锋排除、主将缺失、同场重复去重、双主将、多身份同中文名不合并、先后手与胜负拆分、全部记录回查及非法主将参数。R7 只提供可核验的遭遇分布，不计算均匀主将基线或“被针对概率”。

## R8 小样本亮点与连续概率

每日战报与套牌详情共用确定性亮点规则，不调用大模型。每日战报使用当天当前筛选的全部记录；套牌详情继续限定 R6 的套牌身份、时间范围及可选构筑版本。连续 3 场先手或后手开始生成带数字的评价，先手与后手分别取最长可确认连续段，并按概率从小到大展示。套牌没有连续段时可用重复主将或范围战绩摘要填补空白；重复主将同时显示已知主将分母、实际占比、胜负和先后手。

连续概率采用“每场先后手相互独立且各 50%”的简单参考模型。实现用动态规划精确计算当前记录范围内至少出现一次指定方向连续 N 场的概率，而不是把事先指定 N 场均为同一方向的 `1/2^N` 冒充扫描概率。页面在折叠说明中同时列出两者。未知先后手、相同时间记录会切断可确认记录段；多个记录段分别计算后再合并。存在日期未知记录时不输出连续判断。

用语随扫描概率分级：低于 1% 为“离谱级连庄”，低于 5% 为“非常少见”，低于 15% 为“明显连庄”，其余从连续 3 场起称“值得记录”。这个概率只用于决定亮点显著程度，不代表平台针对概率，也不判断匹配机制。主将遭遇没有均匀概率基线，不为重复主将计算“被针对概率”。

每条亮点返回稳定 key、文字、等级、相关 match_id 和可选概率口径。`/api/deck_detail` 接受 `observation` 参数，选中亮点后返回当前范围内全部证据记录；它与 `opponent_commander` 互斥。每日战报在既有“查看评语依据”中列出相关记录，并可单独展开概率说明。

## R9 首页信息减负

近期观察首页只保留一至两条摘要。第一条固定回答当前窗口的先手、后手、已知分母和先手率；第二条按可用资料依次选择与此前可比战绩的差值、一个低胜率主将记录或最长连败。摘要不显示综合分，也不把小样本或 p 值写成平台意图。先后手、调度、主将和连败四个维度的完整文字、p 值、历史覆盖、低胜率主将列表及免责声明仍在就近的展开区。

调度卡首页显示有胜负结果对局中的调度已知覆盖率，以及“调度过”和“已记录且未调度”两组的场数与整场胜率。展开区显示调度未知场数、逐局留牌分布和来源。BO3 的调度胜率以 match 为分母，逐次留牌分布以 game 为分母；页面明确禁止把两者直接混用。旧记录缺少留牌事件时保持未知。

日报资料说明默认折叠。标题只突出会影响阅读的缺失：当天套牌未记录数、争锋对手主将未记录数和未分配到日期的记录数。展开后列出当天总场数、调度和套牌覆盖，以及只以争锋适用场数为分母的主将覆盖。未知不按零处理，非主将赛事不计为主将缺失。当天没有记录且没有日期未知记录时不显示资料说明。

R9 只调整信息层级，不改变 API 的统计数值与过滤口径。对手主将档案的类型来源当时改成了折叠说明，后来按「页面只放数据」的口径从页面删除（见「收尾 2026-09-12 界面减负」第 3 条）；类型来自手动打标或 `commander_archetypes.json` 先验，手动打标优先。

## R10.1 BO 模式统一筛选与逐局入口

`matches.match_mode` 保存 BO1、BO3 或未知，并在旧库迁移和每次对局更新后统一计算。赛事名明确为传统模式，或 `games` 已实际保存至少两局时归 BO3；只有白名单内明确的单局赛事归 BO1。未知赛事即使当前只有一局也保持未知，之后补入第二局会自动改为 BO3。该字段建立索引，避免各接口重复用不同规则推断。

首页模式筛选传给总览、日报、调度、近期观察、主将档案、筛选候选、对局明细和 CSV 导出。模式选项显示当前赛事／赛制范围下的场数，套牌选项再按所选模式收窄。套牌详情保持独立于首页赛制与赛事的产品口径，并在详情内按该套牌身份提供单独的模式筛选；构筑版本选项随模式重算。

比赛级的 `my_result` 与 `play_draw` 仍分别表示整场胜负和首局先后手。明细“模式／逐局”展开区只读取 `games` 表里的局号、逐局先后手、逐局结果、结束原因与已保存时长；没有逐局资料时显示“逐局未记录”，不使用整场字段填充。对局 CSV 增加“比赛模式”列，仍以一行一场比赛导出。

## R10.2 构筑对手类型标签流程

`is_constructed_opponent_event` 是对手类型的适用范围判定。排位与自由对战直接适用；赛事编号中明确含 Constructed、Cons Event、Explorer Event、Metagame Challenge、Standard Challenge 或 Explorer Challenge 的非争锋赛事适用。含 Brawl、Draft、Sealed 的赛事和无法确认规则的活动不适用，避免把轮抽、现开或特殊活动算成类型缺失。

`matches.opp_archetype_tag` 保存单场人工标签，值限定为 Aggro、Control、Combo、Ramp、Midrange、Other 或空。`POST /api/opp_tag` 对非主将构筑只更新传入的 match_id；类型可以修改和清除，不按对手名字传播。争锋仍使用既有的主将档案标签逻辑，保持历史功能兼容。

`GET /api/opponent_types` 与日报覆盖统计复用首页的赛事、赛制、BO 模式、套牌、Bot 和异常筛选。响应同时给出 eligible、known、unknown 与各标签战绩；零标注时显示空状态。对局明细和套牌详情在适用场次显示选择框，争锋显示主将，其余显示“不适用”。

## R10.3 分赛事历史变化摘要

`compare` 保留原始可审计分组和既有 20 场历史门槛。`summarize_by_event` 只把这些结果整理为赛事与 BO 模式层级：同一赛事／模式中的多个套牌版本可在页面合并阅读，但只有 `usable` 的严格子组参与期望胜场和百分点差值，不会用不可比版本填充基线。

限赛的比较键为同一原始赛事编号与 BO 模式，确保系列、赛制结构和规则一致；构筑键额外包含我方套牌身份与构筑版本。每项返回当天战绩、可比场数、当天有结果场数、历史样本和差值状态。部分可比时显示 `可比场数/当天场数`；完全不可比时仍输出当天胜负事实。

每日战报首页显示一条变化重点，全部赛事与比较口径收进就近展开区。绝对差值最大的可比赛事作为重点；正负 5 个百分点以内称为“接近”。所有文字明确 30 天只是查找窗口，差值只描述个人记录，不能说明调度、匹配或平台意图。

## R12.1 卡名离线补齐

**问题**：卡名此前只有一个来源 `data/mtga_cards.db`，而它由 Scryfall 同步（`card_sync_enabled` 默认关闭）或社区快照导入（需自备快照）填充。全新解压、未改配置的用户，对手主将全部显示成 `grpId:12345`，与 README 承诺的卡名能力不符。

**来源**：MTGA 客户端自带 `MTGA_Data/Downloads/Raw/Raw_CardDatabase_<hash>.mtga`。扩展名虽是 `.mtga`，实际是标准 SQLite（文件头 `SQLite format 3`）：

```sql
Cards(GrpId, TitleId, …)
Localizations_enUS(LocId, Formatted, Loc)   -- LocId = TitleId，Formatted=1 为卡名
```

它随客户端安装下载，覆盖全部卡牌，因此英文卡名可以完全离线补齐。客户端库不含中文（只有 enUS/ptBR/frFR/itIT/deDE/esES/jaJP/koKR），中文仍走快照导入或 Scryfall——与「中文优先、缺译名回落英文」一致。

**实现**：

- `app/client_cards.py`：定位（`Config.client_raw_dirs()` 从会话日志目录反推 `MTGA_Data/Downloads/Raw`，覆盖官方客户端与 Steam 多库；可用 `log_paths.client_raw_extra` 覆盖）、只读读取（`mode=ro`）、写回本机卡名缓存。只补 `pending_grpids` 缺失的 grpId，不覆盖已有名称。
- `app/main.py`：回填完成后在 boot 阶段跑一次（保证首次打开页面就有卡名），常驻 `_cards_loop` 每 5 分钟增量补齐；`POST /api/card_names_seed` 供页面手动触发。联网同步仍由 `card_sync_enabled` 决定。
- 开关：`card_offline_seed` 默认 true，置 false 即完全不触碰客户端目录。
- 富文本清洗：客户端卡名是 Unity 富文本。`<nobr>` 是排版提示直接去掉；`<sprite … name="arena_a">` 是炼金重平衡的「A-」图标，必须还原成字面量 `A-`，否则同一张牌在客户端叫 `Acererac the Archlich`、在 Scryfall 叫 `A-Acererak the Archlich`，`CardNames.get` 会因英文身份不一致丢弃已有的中文译名目录条目。卡名本身可以含 `&`（`Minsc & Boo, Timeless Heroes`），不能当实体转义。
- 来源文案：完全无名称时 `name_source` 显示「缺卡名（客户端库与译名库均未命中）」，不再误标「英文回退」。

**配套修正**：`backfill_zh` 增加 `scope` 与 `zh_tried`。前者让后台只查 stats 里出现过的 grpId，后者避免「本就无中文印刷」的卡（如 Arena 专属 A- 编号）每轮重试。同时 `sync_pending_cards` 不再以「本轮拉到过英文」作为中文补全的前提——离线补齐后 pending 为空，旧条件会让中文补全永远不执行。`_curl_json_checked` 区分「明确无此数据」与「网络失败」，只有前者才标记 `zh_tried`。

## R12.2 回填与监听水位线

**问题**：`backfill()` 每次启动重解析全部来源，而 `data/archive/` 只增不减（实测 32 份 / 330 MB，外推每次启动约 43 秒）；`LogWatcher` 又从偏移 0 开始，把 Player.log 与 Player-prev.log 再读一遍。

**规则**：水位线只在「文件自上次记录以来一个字节都没变」时生效。

| 情况 | 行为 |
|---|---|
| 身份（dev/ino）一致、`size == 已记录偏移`、`mtime_ns` 一致 | 整份跳过 |
| 文件变大 / 变小 / 被原地改写（mtime 变化）/ 身份不符 | 从 0 重新解析 |

**为什么不在中途续读**：MTGA 日志有跨行 pretty-printed JSON，中途起点很难保证落在逻辑记录边界上；而且会话解析器是有状态的，错过一场对局的开头会让后续事件失去归属（R11.1 修的正是结果串场）。从 0 重放是幂等的（`match_id` upsert），代价只有那一份文件；真正的大头——不再变化的归档——被完整跳过。这个规则同时保证记录下来的偏移一定落在真实边界上，所以 `resume_offset()` 返回非零时，`LogWatcher` 可以直接从那里继续 tail。

**实现**：

- `app/ingest_marks.py`：`ingest_marks` 表（path 主键 + dev/ino/size/offset/mtime_ns/last_ts）；`IngestMarks.resume_offset()` 返回可安全续读的偏移，`is_unchanged()` 用于跳过。
- `app/parser.py`：新增 `iter_records_with_offsets()`，在逻辑记录边界上产出字节偏移；`iter_records()` 变为它的薄封装。
- `app/backfill.py`：逐文件先查水位线，未变化则跳过并计入 `skipped`；只在真正读到内容后落盘。
- `app/watcher.py`：`LogWatcher(path, start_offset=...)`；新增 `offset` / `last_ts` 只读属性。
- `app/main.py`：`_watch_loop_inner` 用回填刚记录的偏移接管监听的起点（顺带消掉「Player.log 被解析两遍」）；`save_marks()` **只在 `SessionBuilder.in_progress` 为假时落盘**——半场处记位置会让下次启动错过那一场的开头。
- `/api/status` 的 `boot_backfill` 增加 `skipped`，启动日志可见跳过了几份。


## R12.5 卡名库「已挂载」与「表可用」对齐

**问题**：R12.1 把 `store.connect()` 改成「不管卡名库文件是否存在都 ATTACH」。出发点是好的——全新安装时 `data/mtga_cards.db` 还不存在，它是在启动后才由 `cards_db_connect` 创建的；若因为文件不存在就跳过挂载，主连接此后永远看不到 `cards` 表。

但 SQLite 对不存在的路径是**新建一张空库**再挂载，而 `cards` 表当时还没建。于是出现一个中间态：`cards_db` 挂上了，表却不在。这个窗口在两种情况下并不短暂——客户端卡牌库缺失的机器上可能整个启动期都没有表。

**后果**（实测，修前）：

| 位置 | 是否有保护 | 结果 |
|---|---|---|
| `app/main.py:635` 主将档案打标的存在性子查询 | 无 | **接口 500** |
| `app/main.py:709` 对局打标的 `LEFT JOIN cards_db.cards` | 无 | **接口 500** |
| `app/stats.py:382` 探针、`app/card_names.py:58`、`app/main.py:643/732`、`app/store.py:88` | 有 `try/except` | 静默降级 |

**修法**：ATTACH 之后**立即**把表补出来，让「已挂载」与「表可用」成为同一步的两种说法，中间态不再存在。

- `app/cards_sync.py`：`_CARDS_SCHEMA` 提升为公开的 `CARDS_SCHEMA`，作为 cards 表结构的**单一事实源**。
- `app/store.py`：import 该常量并加 `cards_db.` 前缀生成 `_CARDS_TABLE_DDL`；ATTACH 后无条件执行它。只读挂载等场景 `except sqlite3.OperationalError: pass` 降级为仅 grpId。
- `app/main.py`：新增 `cards_joinable(conn)` 探测，两条原先裸露的路径改为先探测再拼 SQL；无表时退化为纯 grpId 形态。属于纵深防御——建表落地后这个分支在正常启动中不会走到。
- `tests/test_cards_db_attach.py`：覆盖「ATTACH 后表立即存在」「两条裸露 SQL 形态不抛异常」「store 建出的列与 `cards_sync` 完全一致」。

**为什么用 import 而不是复制 DDL**：卡名表结构会随迭代增加列（M4 加过 `name_zh`，R12.1 加过 `source`/`zh_tried`）。两处各写一份迟早漂移，一旦漂移就会出现「谁先建表谁说了算」的隐蔽 bug。统一从 `cards_sync` 取，测试里断言两边列集合相等。


## R12.3 启动期并发安全

**问题**：启动阶段有三处同类的「检查与动作之间存在窗口」，都是并发下才会暴露。

### 1. `get_conn()` 无锁无双检

首屏请求、启动回填线程和监听线程是并发起来的，此前无锁会让两个线程各自 `connect()` 一次，后来者覆盖全局 `_conn`，**先前那个连接连同它的 WAL 句柄被丢在一边却仍被调用方使用**。

**修法**：独立的 `_conn_lock` + 双检。

```python
if _conn is not None:      # 快路径：已建好直接返回
    return _conn
with _conn_lock:
    if _conn is None:      # 慢路径：只有第一个线程真正建连接
        _conn = store.connect(...)
    return _conn
```

**关键约束：这里不能复用 `_db_lock`。** `q()` 的实现是 `with _db_lock: fn(get_conn(), ...)`——若 `get_conn` 也用 `_db_lock`，就是自锁，所有走 `q()` 的接口会直接挂死。所以初始化单独用一把锁，`tests/test_startup_concurrency.py` 里专门有一条用例守着这个死锁。

### 2. `_boot_tasks` 中的 `tag_bot_decks` 在锁外写库

`store.tag_bot_decks(...)` 是写操作，却直接在 `_db_lock` 之外调用，会与 API 的读写撞在一起。修法与紧邻的 cards 阶段保持一致，包进 `with _db_lock:`。

### 3. `/api/retry_boot` 的检查-置位窗口

原实现「先读 `booting` → 起线程」，两次点按之间线程还没跑到置位，就会**起两个回填线程并发写库**。修法是把检查与置位放进同一临界区（`_boot_lock`），置位先生效：

```python
with _boot_lock:
    if _state.get("booting"):  return {...仍在进行中}
    if not _state.get("boot_error"): return {...无错误}
    _state["booting"] = True   # 先占位，窗口关闭
threading.Thread(target=_boot_tasks, daemon=True).start()
```

`_boot_tasks` 自身开头的 `booting = True` 保持幂等，不冲突。

**测试**：`tests/test_startup_concurrency.py` 用 `Barrier` 让 8／6 个线程同时冲进上述路径，断言只建 1 个连接、只起 1 个回填线程；另有一条用源码缩进断言 `tag_bot_decks` 处于锁内。三条关键用例都已用「临时回退修复 → 断言失败 → 还原」验证过不是空转。


## R13 争锋主将档案增强

R13 由三个可独立验收的点组成，按 R13.1 → R13.2 → R13.3 推进。

### R13.1 主将区只认卡牌（徽记过滤）

**问题**：客户端会把徽记（Emblem）也塞进 `ZoneType_Command` 的 `objectInstanceIds`。徽记恒为 `grpId=2` / `objectSourceGrpId=87496`，旧解析把它当成第二个主将写进 `commanders`。全量实测 33 份归档：Command 区只有 `Card`(317) 与 `Emblem`(16) 两种 `GameObjectType`。

**解析侧**（`events._on_commanders`）：只认 `GameObjectType_Card`；`type` 字段缺失时**放行**，兼容合成日志与旧格式。

**历史残留**（`store._migrate`）：重连时 `DELETE FROM commanders WHERE grp_id = '2'`。`grpId=2` 不可能是合法卡牌——客户端 `Raw_CardDatabase` 的 `Cards` 最小 `GrpId` 为 6，本机卡名库最小为 6873，两处都查不到 2。

**实测影响**：本机库里那一行落在**我方座位**（`seat = my_seat`），所以没有污染对手档案，而是混进了 CSV 导出的「我方主将」列（`export_rows` 的 `my_cmdrs` 子查询按 `c.seat = m.my_seat` 取 `GROUP_CONCAT`）；对手座位上的伪主将则由解析层用例覆盖。迁移实测 `commanders` 3515 → 3514，逐行核对确认只删掉那一行。

**测试**：`tests/test_core.py` 四条解析用例（徽记被过滤／只有徽记时解析出 0 个主将／伙伴双主将不受影响／无 `type` 字段照常解析）加一条重连迁移用例。

### R13.2 类型多标签

**问题**：争锋里很多卡组有多种玩法轴——始霸埃泰力既是 Ramp 也是组合技，拿杜既是组合技也靠加速。原来的类型字段是**严格单值**的（`ARCH_KEYS` 里的一个字符串），一场对局／一个主将只能落进一个类型，表达不了这种多轴卡组。

#### 存储格式

标签集合序列化为**逗号分隔串**（`"Ramp,Combo"`）。单标签时就是它自己，因此**旧数据无需迁移**——`"Combo"` 读出来就是 `["Combo"]`。

```python
parse_tags(None)          -> []
parse_tags("Ramp,Combo")  -> ["Ramp", "Combo"]
parse_tags(["Combo"])     -> ["Combo"]
parse_tags("Ramp,Bogus")  -> ["Ramp"]     # 非法标签只丢那一个
```

`commander_archetypes.json` 的**值支持两种形态**，向后兼容：

```json
{ "Nadu, Winged Wisdom": "Combo",
  "Etali, Primal Conqueror": ["Combo", "Ramp"] }
```

#### 统计口径：重叠计数

一场标了 `Ramp,Combo` 的对局，在按类型聚合时**两个类型各计一次**，两侧分母都包含它。这样「遇到这类玩法时的胜率」才准确，代价是各类场次之和会超过总场次——UI 上需要说明。

#### 优先级与覆盖

手动打标（`opponent_profiles.archetype_user`）**整体覆盖**先验：在 UI 上给某主将加一个轴，会替换掉先验里的全部标签，不是增量追加。清除手动标即可回落到先验。

#### 本次范围

**只改争锋主将档案链路**：先验表 + 主将档案打标控件。

非主将构筑的逐场标签（`matches.opp_archetype_tag`）**保持单选**，`opponent_type_stats` 的按 `==` 分组逻辑未动。

注意 `opp_tag_by_name` 给争锋主将打标时仍会回填 `matches.opp_archetype_tag`（可能写入多值）；这些场次都是 Brawl，而 `is_constructed_opponent_event` 对 Brawl 返回 False，**不进非主将构筑统计的分母**，故不受影响。

#### 前端

`archTag()` 接受数组，逐标签渲染 chip；`archSelect()` 改为 `<details>` 折叠 + chip 组多选，点击即 toggle 并提交整个集合（`toggleOppTag` 按 `ARCH_ZH` 固定顺序收集，保证存储稳定）。

**测试**：`tests/test_commander_archetype_ui.cjs`（渲染层，含单值兼容、多 chip、空集合、单引号转义）与 `tests/test_matchups.py` 的 `parse_tags`／多标签先验／手动覆盖用例。

### R13.3 战报与明细共用日期

**问题**：战报区与对局明细各有一套日期状态（`#daily-date` 输入框 vs `matchDay`），改一处另一处不同步，用户得在两个地方分别选同一天。

**改法**：日期状态统一为顶层 `matchDay`。`d-today`／`d-yesterday`／`d-all`／`d-date` 都经 `setDay()` 写 `matchDay`，再一起刷新 `loadDaily()` 与 `loadMatches()`；战报不再从输入框读日期。

选「全部日期」（`matchDay === ""`）时**藏起战报区**并显示替代说明——战报是单日口径，全部日期下没有意义；下方明细仍列出全部记录。

主将档案新增排序开关：`sort=count`（按场次，默认）／`sort=recent`（按最近相遇，打标时不用翻页找）。`last_time` 取 `MAX(m.start_time)`，`NULL` 排在最后。

**踩过的坑**：`api_commanders` 一度把带 `sort` 的同一个 kwargs 词典同时传给 `stats.matchups` 与 `stats.commander_coverage`，后者没有该参数 → `TypeError` → **整个 `/api/commanders` 500**，对手主将档案页全白。`sort` 只属于 rows。回归测试见 `tests/test_matchups.py::test_commanders_api_accepts_both_sorts`。

**测试**：`tests/test_daily_ui.cjs` 用 `vm` 跑 `loadDaily` 片段，断言旧响应与作用域不匹配的响应都被丢弃、赛事名与历史条正确渲染，以及「全部日期不再请求 `/api/daily`」。注意 `matchDay` 与 `syncMatchDayBtns` 定义在切片之外，测试需显式注入。

### R13.4 区块加载独立容错

**问题**：`reload()` 用 `Promise.all` 并发跑九个 loader，任一抛错就让页面顶部出现一条红色横幅，内容是 `app.js` 内部的行号与堆栈——**看不出是哪个区块坏了**，而且看起来像整个面板都挂了（实测撞到过一次：服务进程陈旧导致 `loadDaily` 读到缺失字段）。其余区块其实照常渲染了，只是被这条横幅盖住了。

**改法**：`Promise.allSettled` + 汇总提示。

```js
const results = await Promise.allSettled(
  RELOAD_SECTIONS.map(([, fn]) => Promise.resolve().then(fn)));
```

- `Promise.resolve().then(fn)` 包一层：即使某个 loader **同步**抛错也会变成 rejected promise，不会在 `map` 阶段炸掉整个 `reload`。
- 失败的区块名与错误消息汇总进 `#load-error`，逐个点名；未失败的区块不出现。
- **筛选条件取不到**是另一种性质：那时 `reload()` 根本不会开始，页面什么都加载不出来。所以 `reportLoadFailures(..., fatal=true)` 把标题改成「页面未能初始化」，避免用户误以为只是某个区块坏了。

**取舍**：没有把失败改成静默——失败区块仍被点名，只是不再独占整页。「响亮失败」保留，只是把音量调到与影响面匹配。

**测试**：`tests/test_load_error_ui.cjs` 断言「一个区块失败不阻止其余八个加载」「未失败的区块不被点名」「致命态标题不同」「恢复成功后错误区自动收起」；已用「临时退回 `Promise.all` → 断言失败 → 还原」验证过能捕获。


## V1 限制赛临时牌组的可区分显示名

**问题**：MTGA 给轮抓／现开牌组的是通用名（"轮抽套牌" / "Draft Deck" / "现开赛"），本机实测 250 次 draft 挤在三个名字里。后果是两处都认不出「哪一次」：

- 对局明细「我的套牌」列每行都写「轮抽套牌」——链接本身带 `deck_id`，点开是对的详情，但用户看不出点的是哪次；
- 套牌详情页标题是「轮抽套牌」，还会提示「另有 **1156** 场同名记录无法与此身份连接，未合并」——那些本来就是别的 draft，不是「未合并的同名套牌」，纯属噪音。

**判据（不硬编码名字）**：客户端本地化会变（英文客户端就叫 `Draft Deck`），所以判据不写死字符串，改用两条与语言无关的事实：

1. 该 deck 的对局里 ≥60% 属于限制赛（`event_id` 含 `Draft` / `Sealed`）；
2. 它的 `my_deck_tag` 在库中被**多个** `my_deck_id` 共用——名字已不足以标识身份。

两条同时满足才派生显示名 `赛制 · 首次对局时间`（如「轮抓 · 2026-06-10 12:16」）。赛制取「轮抓」或「现开」；时间取该 deck **最早**一场的本地时间，不是最后一场。

**为什么必须再限制赛制**：只按「名字被多个 deck_id 共用」判断会**误伤用户自己起的重名套牌**。本机 314 个套牌名里 39 个不具唯一性，绝大多数是用户自起的（「红黑牺牲」「脂牙」「大綠」「蒂法争锋」各 2 个 id，「黑白中速」4 个）。加上限制赛条件后：

| | deck_id 数 | 场次 |
|---|---|---|
| 命中（限制赛 + 名字不唯一） | 301 | 1996 |
| 排除（保持原名不动） | 125 | 1435 |

逐条核对：**被排除的 125 个里没有任何限制赛对局**——既没有漏网，也没有误伤。

**`?` 不能当「临时牌组名」处理**：本机 `my_deck_tag = '?'` 的 347 场横跨三种赛制（其他 246 / 轮抓 66 / 争锋 35），它是「未命名套牌」的通用占位。所以判定必须**逐个 deck_id 看它自己的赛制构成**，不能按名字归类。

**实现**：

- `app/deck_names.py`：`ambiguous_tags()`（被多个 deck_id 共用的 tag）、`limited_labels()`（deck_id → 派生名）、`label_for()`（派生名优先、回落原名）。
- `app/stats.py`：`match_list` 每行新增 `my_deck_label`；原始 `my_deck_tag` 保留不动，既有契约不破。
- `app/deck_detail.py`：命中时 `title` 用派生名，`same_name_unlinked` 归零，并在 `identity.note` 里说明改名由来（原名留痕）；`records` 也带 `my_deck_label`。
- `web/app.js`：`deckLink` 与详情页核对表的套牌列改用 `my_deck_label || my_deck_tag`。

**测试**：`tests/test_deck_names.py` 八条（含「用户自起重名套牌保持原名」「非限制赛不派生」「同一 tag 混合赛制只改限制赛那个」三个不误伤方向）+ `tests/test_deck_label_ui.cjs`（前端取字段顺序与回退）。两条关键断言都用「临时回退 → 断言失败 → 还原」验证过不是空转。


## V1 续做 套牌筛选二级联动

**问题**：套牌筛选下拉按 `my_deck_tag`（客户端牌组名）分组，本机 314 项里 **39 个名字被多个 `my_deck_id` 共用，占 3,492 场 = 31.9%**。选「红黑牺牲」把两副不同的牌合在一起看；选「轮抽套牌」则把 188 次 draft 合成一个 1625 场的条目。上一节已解决**显示名**（明细和详情页能认出来了），但**筛选下拉**仍认不出，首页所有区块都收不到「只看某一次 draft」这个粒度。

**为什么不把下拉展开成 630 项**：按 `deck_id` 拆开会让下拉从 314 项涨到约 630 项，而且 250 个 draft 条目长得一样。**改成二级联动**——第一级仍是 314 个名字，只有选中「重名」名字时才出现第二级，正好覆盖那 39 项。

**两级语义是「求交」，不是替换**：`deck`（名字）与 `deck_id`（身份）同时出现时两个条件都加。

```sql
WHERE COALESCE(my_deck_tag,'') = ? AND COALESCE(my_deck_id,'') = ?
```

选「脂牙 → 2022-06-02 起」要的是「**脂牙这个名字下、属于这一副**」的对局，而不是这一副套牌的全部对局（它可能还用过别的历史名字）。这样两级下拉的场数才加得起来：47 + 37 = 84 = 「脂牙」的场数。**写成「`deck_id` 优先于 `deck`」是错的**——实测会出现「身份行显示 192 场（全库口径）而该名字下只有 47 场」的自相矛盾。

**身份名不带场数**：第二级选项写「轮抓 · 2026-06-10 12:16」而不写「192 场」。`identity_labels` 是全库口径的名字，而场数按当前筛选算，混在一起就会出现「下拉写 192 场、选完只有 47 场」的矛盾（改过名的套牌就是这样）。场数放在括号里按当前筛选单独算（`全部（113）` / `111 场` / `2 场`），两者职责分开。

**实现**：

- `app/deck_names.py`：抽出 `_deck_rows()` 供 `limited_labels()`（明细显示名）与 `identity_labels()`（二级下拉名）共用，保证「下拉里看到的名字」与「明细里看到的名字」永远一致；`identity_labels` 覆盖**所有**重名身份，限制赛派生「轮抓／现开 · 时间」，其余「时间 起」，刻意不带场数。
- `app/stats.py`：`_filters` 加 `deck_id`（求交）；新增 `_deck_scope_cond()`（从 `filter_options` 抽出，供身份列表复用）与 `deck_identities()`（身份名取自全库、场数按当前筛选）；`filter_options` 的每个 deck 项加 `ids`（该名字下的 deck_id 数）。`deck_id` 透传到 `overview`／`opponent_type_stats`／`matchups`／`commander_coverage`／`match_list`／`export_rows`／`mulligan_stats`／`targeting_index`。
- `app/main.py`：8 个既有端点加 `deck_id` 参数并透传；新增 `GET /api/deck_identities?deck=<名字>`。
- `web/app.js`：`params()` 只在两级都选中时加 `deck_id`（`deck` 保留）；`loadFilters` 记下每个名字的 `ids`；`syncDeckIdentities()` 在 `ids > 1` 时才请求并显示第二级，否则收起清空；换名字时清空二级再刷新。
- `web/index.html`：`#f-deck` 后加 `#f-deck-id-wrap`（默认 `hidden`）；缓存失效参数 `0.4.2-deck-cascade`。

**测试**：`tests/test_deck_identities.py` 七条（含「两级求交而不是替换」这条关键断言）+ `tests/test_deck_cascade_ui.cjs`（`ids>1` 才请求、选项值必须是 deck_id、换名收起）。「求交」那条已用「临时改成 `deck_id` 优先 → `assert 5 == 3` 失败 → 还原」验证过不是空转。

**实测**：`ids > 1` 正好 39 项。「红黑牺牲」出现第二级（`全部（113）`／`111 场`／`2 场`）→ 选大的一副 → 明细 `共 111 场`；「轮抽套牌」188 个 draft／合计 1288 场，选一个 → `共 132 场`；`W3`／`W4`（唯一名）第二级不出现；切回唯一名第二级消失。场数加总独立核对：`脂牙` 47+37=84、`红黑牺牲` 111+2=113、`轮抽套牌` 188 项合计 1288，全部与 `/api/filters` 的 `n` 一致。


## 收尾 2026-09-12 界面减负（三处用户反馈）

### 1. 单一 BO 模式不再在日报里复述一遍

**问题**：某天 3 场全是史迹争锋 BO1 时，日报会先列一行「史迹争锋：3 场 · 1 胜 2 负」，紧接着再列一行「BO1：3 场 · 1 胜 2 负」——后一行把当天总数原样复述了一遍，零信息。

**口径**：`modes` 只在**确实存在模式拆分（≥2 种）**时才占一行。后端 `/api/daily` 的 `modes` 字段保持原样（如实给出当天出现过的模式），是否值得显示由前端判定——它纯粹是「这行会不会只是复述总数」的呈现问题。`app.js` 因此写成 `(r.modes || []).length > 1 ? … : ""`。

**测试**：`tests/test_daily_ui.cjs` 加两条——单一模式时 `#daily-events` 不得出现「BO1：」，两种模式时 BO1／BO3 两行都要在。已用「临时改成 `length > 0` → 断言失败 → 还原」验证过。

### 2. 连续遭遇同一主将换成更重的说法

**问题**：评语库只有一批轻说法（「又和 {name} 碰上了，挺有缘分」）。连打三把全撞上同一个人时，这句话明显不够——「连续三把」和「一天里零散遇到三次」不是一回事。

**口径**：以**当天的完整对局顺序**为准（`start_time, match_id` 排序），只有该主将的对局才算「撞上」，中间夹了别的对局就断。`_longest_commander_run()` 取这段最长连续段；`len(run) >= 3` 时用新话术 `repeat_commander_streak`（`level="legendary"`，证据 `match_ids` 只挂连着的这几场，`streak` 字段记长度）；否则沿用原来的 `repeat_commander`。`kind` 保持 `repeat_commander` 不变——同一现象、两种力度。

**测试**：`tests/test_daily_highlights.py` 把原来那条拆成「零散遇到保持轻说法（无 `streak` 字段）」与「连续三把升级（`streak==3`、`level=='legendary'`、证据只挂这三场、且不落回轻话术）」两条，另加一条守住两套话术不共用句子。已用「临时去掉连续分支 → `KeyError: 'streak'` → 还原」验证过。

### 3. 删掉纯说明性的折叠入口

**问题**：页面上散着一批「只讲道理、不给数据」的 `<details>`——卡名显示规则、主将类型来源、本地译名怎么改。用户反馈：「这种解释性的三角符号太多了，完全不是插件该有的东西」。

**口径（2026-09-14 已被推翻，见「收尾 2026-09-14 全站信息减负」）**：当时定的是**页面只保留「展开看数据」的折叠**（赛事中文／原文对照表、评语依据、分赛事历史比较、资料覆盖、近期波动明细、构筑版本变更、逐次留牌分布、主将名详情、单场明细、类型打标）。纯说明文字一律写进本文档。据此删掉三个入口：「卡名显示与译名纠正」「主将类型来源」以及嵌套在赛事对照里的「如何纠正本地译名」。`data/card_names.zh.json`、`data/event_names.zh.json` 的用法见 R4／R3 两节。

**测试**：`tests/test_ui_ids.py::test_no_explanatory_folds_in_page` 解析所有 `<summary>` 文本，禁止这三个标题回来。已用「临时加回 `主将类型来源` → 断言失败 → 还原」验证过。

**三处验收**：`pytest tests/ -q` 全绿；`node --check web/app.js` 通过；`tools/check_privacy.py --all` 通过。




## V3 收尾 首页套牌入口与赛制自适应（2026-09-13）

### 1. 背景：V3 的赛制自适应此前是死代码

`applyFormatFocus()` 用 `const filtering = !!(params().toString())` 判断「用户有没有手动筛选」。但 `params()` **永远**会 `set("exclude_bot", …)`，所以 `toString()` 恒非空、`filtering` 恒为真，函数每次都在第一行 `return`。

后果：提示条 `#format-focus-note` 永远隐藏、`document.body.dataset.formatFocus` 永远是空串、`#commander-card` / `#rank-card` / `#opponent-types-card` 的收放从来没被设过。VISION 里 V3 那节写「首页提示条 + 收放对手主将/段位/构筑类型区块」——**从 `4ccb511` 落地那天起就没生效过**，纯前端 `.cjs` 假 DOM 测试也照不出来（没有 `params` 依赖链，也没有 CSS）。

**口径**：判的是「用户真的挑了筛选条件」，即四个筛选控件有没有值：

```js
const filtering = ["f-family", "f-event", "f-mode", "f-deck"].some(id => $(id)?.value);
```

`exclude_bot` 是「排除开关」，不是赛制筛选，不该参与这个判断。

### 2. 首页缺 V1 主路径的入口

V1 把套牌旅程（身份 → 版本 → 单次复盘）做完了，但首页没有任何入口：只能靠筛选下拉的「查看套牌详情」或明细表里的套牌名。后端 `overview` 的 `by_deck`（314 条）与 `by_event`（254 条）算了却从没渲染。

新增 `#recent-decks-card`，位置在**每日战报之后、三张总览卡之前**——是「接着去哪」的跳板位，也是排位焦点时段位卡会被挪到的地方。

### 3. 聚合粒度：按 `my_deck_id` 成行，不按名字

这是本节最容易做错的地方。本机实测：

| 口径 | 行数 |
|---|---|
| `(my_deck_tag, my_deck_id)` 组合 | 708 |
| distinct `my_deck_id` | 687 |
| 按 id/version 二部图求连通分量 | 677 |

- **按名字聚合是错的**：「轮抽套牌」一个名字压着 188 次 draft，聚合后只剩一行 1288 场，入口直接废掉。
- **按 `(tag, did)` 聚合会拆行**：本机 20 个 `did` 挂了多个 `tag`（如 `9ebde2d1` =「脂牙」+「脂牙 BO1」192 场）。拆出来的两行点进去是**同一个详情页**，正是入口最不该有的样子。
- **按 `did` 聚合**与二级下拉（`deck_identities`）、`openDeck` 的 payload 是同一个单位，一行一个目的地。
- **没有进一步按 `my_deck_version` 求连通分量**（那才是 `deck_detail._identity` 的完整语义）：要遍历全库建图，首页每次加载都跑太重。代价是本机 10 个「同版本号跨 id」的分量（3–230 场，多数是 `?`／`Imported Deck` 占位名）会占两行、点进去同一页；其余 677 个身份都是一行一个目的地。**这是一处已知取舍，不是遗漏。**

只有名字、没有 `deck_id` 的记录仍按名字单独成行（它们点进去也是按名字找）。

### 4. 显示名：派生名优先，其次最近一次的 tag，撞名才补时间

```
label = limited_labels[did]  ||  该 did 最近一次对局的 my_deck_tag
```

与详情页标题同规则（`deck_detail` 先取 `recent_name`、再被 `derived_label` 覆盖），所以**点进去不会「换个名字」**。

**撞名时补「首次对局时间 起」**：本机「现开赛」×5、「?」×22、「已导入的套牌」×10、「黑白中速」×4 等，摆五行一模一样的名字等于没法挑。只有真的撞名才补，不撞就保持用户自己的名字（「阿耶尼史迹争锋」不加尾巴）。

- 时间用**分钟**精度：`Yargle_Day_20260903` 那 5 副是同一天连着开的，只到日期会重名五次。
- 补完时间还撞（同一分钟开的两副）再用 `deck_id[:6]` 兜底，保证行行可分。
- 判定在**切片之前**做，所以「补不补」只取决于筛选、不取决于 `limit`。

**为什么 `Yargle_Day_*` 拿不到派生名**：`deck_names._is_limited()` 只认 `event_id` 里含 `Draft`/`Sealed`，而 `Yargle_Day_20260903` 这个特别活动的 event_id 两者都不含 → `limited` 计数为 0 → 派生名规则认不出。**没有去放宽 `_is_limited`**：那 92 个不含 Draft/Sealed 的 event_id 里混着 `Ladder`、`Explorer_Event_v2`、`Play_Brawl_Historic`、`Constructed_Event_2022` 这类**根本不是限制赛**的赛事，放宽会大面积误伤。撞名补时间的做法对「占位名」与「用户自起的重名」一视同仁，不依赖赛事名。

### 5. 赛制收窄（`focus`）

`recent_decks(focus=True)`：**仅当调用方没显式给赛事／赛制／模式时**，按 `format_focus()` 算出的近 30 天主赛制收窄。响应里的 `focus` 字段回传实际口径（`applied`／`primary`／`label`／`window_days`／`share`），前端据此写提示条。主赛制为 `unknown`（近 30 天无数据）时不收窄——否则入口会空掉。

首页两个按钮「主赛制 / 全部」对应 `focus=1 / 0`，默认「主赛制」。

### 6. 刻意不收套牌筛选

`recent_decks` 的签名里没有 `deck` / `deck_id`，API 层也不收。它是**选择器**，跟随套牌筛选就退化成一张永远只有一行的卡片。赛事／赛制／模式照常收窄。前端在套牌筛选生效时会写一句「套牌筛选不影响这个区块——它就是用来挑套牌的」，避免看起来像坏了。

### 实现

- `app/stats.py`：新增 `recent_decks()` 与 `_day_of()`；`_event_scope` 复用于赛事／赛制收窄。
- `app/main.py`：新增 `GET /api/recent_decks`（`limit` 1–50，默认 12；`focus` 默认 false）。
- `web/app.js`：抽出 `deckOpenButton()`（payload 形状只在一处拼，明细与入口区共用；`deckLink` 改为调用它）；新增 `loadRecentDecks()` / `recentDecksNote()` / `setRecentDecksScope()`；登记进 `RELOAD_SECTIONS`（10 项）；修 `applyFormatFocus` 的 `filtering`。
- `web/index.html`：新增 `#recent-decks-card`（`#rd-focus` / `#rd-all` / `#recent-decks-note` / `#recent-decks-rows`）；缓存失效参数 `0.5.0-recent-decks`。

### 测试

- `tests/test_recent_decks.py` 15 条：一个 did 多 tag 并成一行、只有名字的行单独保留、限制赛 draft 各自成行且拿到派生名、撞名补时间、唯一名不加尾巴、同分钟再撞用 id 兜底、未记录套牌只计数不占行、排序与 limit、场次与先后手、异常／bot 开关、`focus` 四种情形、签名里不得出现 `deck`/`deck_id`。
- `tests/test_recent_decks_ui.cjs`（已登记进 `CJS_TESTS`）：赛制自适应真的生效（提示条显示、`body.dataset.formatFocus`、三张卡收放、排位焦点把段位卡上移）、入口按钮 payload、口径提示条、空态。**上下文里故意注入了一个非空的 `params()`**——将来谁把 `filtering` 改回 `params().toString()`，这条会红在断言上，而不是悄悄退回死代码。
- 同步：`test_deck_ui.cjs` / `test_deck_label_ui.cjs` 的切片起点改为 `function deckOpenButton`（`deckLink` 现在复用它的 payload）；`test_load_error_ui.cjs` 的 loader 清单从写死 9 改成显式列出 10 项。

**空转验证**（三处，全部还原）：把 `filtering` 改回 `params().toString()` → cjs 报「没手动筛选时提示条必须显示」；把聚合键改回 `(tag, did)` → `assert 2 == 1`；去掉撞名补时间 → `assert '现开赛 · y1' == '现开赛 · 2026-09-04 19:19 起'`。

**实测**（真实库 10,964 场，Chromium 快照 + playwright-core）：

- 默认「主赛制」：提示条显示「近 30 天主赛制：争锋（约 70.5%）」，`body.dataset.formatFocus="争锋"`，`#rank-card` / `#opponent-types-card` 的 `getComputedStyle().display` 均为 `none`、高度 0（`[hidden]{display:none!important}` 兜底生效），`#commander-card` 保留。
- 8 行，首行「拿杜史迹争锋生物版 277 场 · 胜率 57%（158 胜）· 先手 125 · 后手 141 · 最近一次 2026/09/12 23:11」；点第一行 → 详情弹窗标题「拿杜史迹争锋生物版」，与行内名字一致。
- 切「全部」：`共 686 套牌`，`现开赛 · 2026-09-04 19:19/19:59/21:07/22:25/22:43 起` 五行各不相同；`另有 6 场没记录套牌`。
- 手选赛制：提示条改为「已按当前筛选收窄，赛制切换以筛选为准。」，`format-focus-note` 隐藏、`dataset.formatFocus` 清空。
- 卡片位置：`previousElementSibling` 是每日战报的 `section.card`，`nextElementSibling` 是总览 `grid g3`。控制台无错误。

## 清理 2026-09-13 前端死代码与一条假覆盖测试

V3 收尾时发现 `applyFormatFocus` 整块是死代码（见上一节），顺着用同一条判据扫了一遍：**「定义了但文件内部没人引用」**。`web/app.js` 里三个函数中招，其中一个是「测试守着一个页面永不调用的函数」。

### 三个死函数（连带的两个变量、一个插件）

| 名字 | 调用点何时被删 | 当时为什么删 |
|---|---|---|
| `barChart` + 误差线插件 `ciPlugin`（含 `Chart.register(ciPlugin)`） | `396677b`「Drop redundant play/draw and per-event charts」 | 先后手柱状图与各赛事柱状图与上方指标卡重复 |
| `matchDetails` | 同上（同一提交把 `<td>${matchDetails(r)}</td>` 换成「…」+ title） | 「BO1 rows no longer expand a long details panel」——每行一块折叠面板太高 |
| `dimVerdictColor` | `66be77d`「targeting card rewrite - plain-language verdicts」 | 彩色判定改成朴素 `.tag` 标签 |

连带死掉的还有：`fmtDur`（只被 `matchDetails` 用）、顶层变量 `pdChart` 与 `eventChart`（那两张图的实例变量，只剩 `trendChart`／`rankChart` 在用）。

**确认没有孤儿 DOM**：`index.html` 里只有 `#c-trend`、`#c-rank` 两个 canvas，与现存的两张图一一对应。

### 关键问题：`tests/test_match_ui.cjs` 在守死代码

它调用 `context.matchDetails(known)` 并断言 6 条（`<summary>查看</summary>`、用时、结束原因、数据来源、套牌 ID、构筑版本）。而 `matchDetails` 在同一提交里就已经没人调用了——**测试全绿，但它守的代码页面永不执行**。这比「没有测试」更坏：它让「这块有人管」看起来成立。

改法：删掉 `matchDetails` 的断言，改为断言**页面真正渲染的东西**——最后一列 `…` 的 `title`（`来源 X · 调度 Y · 结束原因 Z · match_id`），并加一条 `assert.doesNotMatch(row, /<details/)` 钉住「行内不再有折叠面板」。

顺带补了一条**列数契约**：表头 `<th>` 数 == `matchRow` 的 `<td>` 数 == 分组行的 `colspan`。`396677b` 把列数从 10 减到 9 时三处必须一起改，之前没有任何守卫。实测：200 行数据、9 个 `<td>`、9 个 `<th>`、`colspan="9"`。

### 新增守卫：`test_ui_ids.py::test_no_dead_top_level_definitions_in_app_js`

浏览器只加载 `app.js`，`index.html` 也没有内联事件处理器（全部走 `addEventListener`），所以**只被 `.cjs` 测试引用的函数同样是死代码**。守卫的做法是：抽出 app.js 所有顶层函数／箭头常量定义，逐个统计它在 **app.js 内部**的出现次数，`<= 1`（只有定义）即报错。`$` 与 `Chart` 是 DOM／CDN 全局，进白名单。

**空转验证两处**（全部还原）：临时加 `function deadProbe(){}` → 报 `['deadProbe']`；临时把 `matchDetails` 加回去（只被 `.cjs` 测试引用）→ 报 `['matchDetails']`。第二处正是本次要防的情形，说明「测试引用」不会让它蒙混过关。

**范围说明**：这条守卫只看 app.js 内部引用，所以它守不住「被调用但判断恒假」（上一节那个 `params().toString()` 就属于那一类）——那类问题只能靠行为断言，见 `tests/test_recent_decks_ui.cjs` 注入非空 `params()` 的做法。

### 不丢能力

被 `matchDetails` 展示过的字段里，**时长(秒)、总回合、异常、异常原因、我方调度、match_id 都在 CSV 导出里**（`export_rows` 的 matches 表头）。所以这次清理不减少可获取的信息，只是把明细行的 title 维持在原来的子集（`…` 列表头写的「来源、调度、结束原因等」）。

### 验收

`pytest tests/ -q` → **270 passed**（较 269 多 1 条守卫）；`node --check web/app.js` 通过；`git diff --stat` 净删 72 行（app.js 6 增 78 删）。浏览器实测：`#c-trend` 仍有 Chart 实例且画布 539×220（**删掉 `Chart.register(ciPlugin)` 没有影响现存两张图**），`#c-rank` 有实例但按 V3 口径在争锋焦点下隐藏，明细 200 行 9 列、行内 0 个 `<details>`、控制台 0 错误。缓存失效参数 `0.5.0-recent-decks` → `0.5.1-dead-code`。

## 收尾 2026-09-14 全站信息减负（用户口径「要大改」）

用户看过实际页面后的三条反馈，合起来是同一件事——**页面上不该出现「为了完整而完整」的东西**：

1. 「整个插件每个地方都非常喜欢罗列数据，这些数据全都没必要，要大改」（截图指向连续纪录块、调度覆盖率长句、周胜率趋势双序列图、常遇主将行）；
2. 「这些能点开的三角完全没必要」（截图点名 5 处折叠）；
3. 「这个 bot 对局也不要显示，直接排除 bot 对局就完了」。

### 口径：折叠从「只留数据类」推到「一个都不留」

上一版的口径是「页面上只保留『展开看数据』的折叠」。用户看过真实页面后明确否掉了数据类折叠，于是现在**`index.html` 里一个 `<details>` 都没有**。想看细节去对局明细或导出 CSV；说明性文字一律留在本文档。

守卫从「逐个列禁止标题」改成「出现 `<details>` 就报错」——比维护一份标题黑名单结实。唯一例外是 `app.js` 动态生成的**对手类型打标控件**（`arch-edit`）：它是输入控件（R10.2 的多标签标注）、不在页面初始 DOM 里、也不是「点开看数据」，守卫对它做了显式放行。

| 删掉的折叠 | 内容去向 |
|---|---|
| 赛事中文／原文对照与译名纠正 | 删。赛事名本来就带原文 `title` |
| 查看评语依据 | 删。对局明细里逐场都有 |
| 查看全部赛事、BO 模式与比较口径 | 删，只留 `history_summary.headline` 那一句结论 |
| 资料说明（覆盖分母） | 删。缺失资料不影响结论，不必写在页面上 |
| 查看详细分布、资料覆盖与统计口径（4 项） | 删。p 值／分母／维度判定就是用户点名的「罗列」 |
| 构筑版本变更 | 删。版本信息在套牌详情的表格里 |
| 逐次留牌分布、未知量与来源 | 删 |
| 主将名详情（英文名／grpId／最近相遇） | 删，表格只留主将名 |
| 概率口径 ×2（评语依据、套牌观察） | 删 |

### 删掉的罗列区块

- **连续纪录三行 → 一行**：「当天最长」「截至所选日期的历史最长」和那句统计口径全部去掉，只留「当前连续先手 N 场」。连续是这个面板存在的理由（R2），所以留一条；另外两条是复述。
- **逐赛事罗列 + 常遇主将 + BO 模式拆分 + 对手类型覆盖率**（`#daily-events` 整块）删掉。
- **周胜率趋势图**（双序列折线）删掉——它是「罗列」的图形版，而且与总览卡重复。
- **调度卡**：从「资料覆盖 10397/10782 场（96.4%）。调度过 1868 场，整场胜率 52.2%；已记录且未调度 8529 场，整场胜率 58.7%。」压成一句「调度过 1868 场（胜率 52.2%），未调度 8529 场（胜率 58.7%）。」——只留对比本身。
- 总览卡上「另有 N 场未计入（Bot 局…）」也删掉（同属罗列式说明）。

**没有动的**：当天评语、三张总览卡、最近在打的套牌入口、先后手局数分布、近期波动的一两句摘要、段位曲线、对手主将档案、对局明细。它们是「看一眼就知道」的部分。

### Bot 局：一律排除

`#f-bot` 开关删掉，`params()` 与套牌详情请求一律带 `exclude_bot=true`。后端**保留** `exclude_bot` 参数（默认 True）：导出 CSV 与测试需要显式控制它，去掉只会让「Bot 局在数据里长什么样」变得不可验证。

### 评语：更带劲 + 场次不再垄断

用户原话：「评语现在很有问题，不够激情，太平淡了，而且一旦打长了就必然只有一条说今天打了很久」。

两处改动：

1. **话术**（`app/daily_copy.py`）：往「有情绪、有画面」重写（「这状态再打下去要被人举报了」「22 场连轴转，牌桌都快坐穿了」「7 连后手，今天牌桌跟你杠上了」）。两条红线没破：不编事实、不用纯感叹词凑数（`卧槽`／`哇`／`太美` 有测试守着）。
2. **优先级**（`app/daily_highlights.py`）：**场次从第 1 位降到末位**。以前 `volume` 排第一，加上 `_filter_for_volume` 在耐力局（n≥15）里把非离谱级信号全丢掉，于是 22 局的日子若没有离谱级连续就只剩一句「今天打了很久」。现在：
   - 排序：高胜率 → 离谱级连续 → 连续撞同一主将 → 先后手偏斜 → 零散重复主将 → 普通连续 → **场次**；
   - `_filter_for_volume` 不再按**占比**丢重复主将（22 场里遇到 3 次＝13.7%，旧规则丢弃），改为按**绝对次数**保留——一天里遇到同一个人 3 次与当天打了多少场无关。

真实库效果（2026-09-14，22 场）：

```
改前：22 场打满。
改后：又和 拿卡地贱民阿耶尼 碰上了，这缘分不浅。 22 场连轴转，牌桌都快坐穿了。
```

### 测试

- `tests/test_ui_ids.py`：`test_no_explanatory_folds_in_page` → `test_no_folds_in_page`（出现 `<details>` 即报错，`arch-edit` 显式放行）。
- `tests/test_daily_highlights.py`：`test_marathon_day_beats_ordinary_streak` 去掉「场次必须排第一」；新增两条——`test_volume_never_leads_when_a_real_signal_exists`（两个真亮点可以把场次挤出名额）、`test_long_day_with_only_scattered_repeat_still_gets_two_lines`（用户原场景：22 场 + 零散遇到 3 次 → 必须是两条，真事实在前）。
- `tests/test_daily_ui.cjs`：切片起点改为 `let dailyRequest …`（原哨兵 `dailyQualityView` 已删，indexOf 返回 -1 时崩过一次）；断言改为「只有当前连续一条」「空日仍保留跨日连续」。
- `tests/test_r9_ui.cjs`：删掉 `dailyQualityView` 段；调度断言改为新的一句对比，并断言 `detail` 字段已不存在。
- `tests/test_deck_ui.cjs`：概率折叠断言改为 `assert.doesNotMatch(html, /<details/)`。

**空转验证**：把 `_rank` 里 `volume` 改回返回 0 → 两条新测试同时失败（`['volume', 'hot_wr']` 与 `['volume', 'repeat_commander']`），已还原。

### 验收

`pytest tests/ -q` → **277 passed**；`node --check web/app.js`；`tools/check_privacy.py --all` 扫 109 文件通过。浏览器实测（Chromium 快照，全部日期下 214 行明细）：页面 `<details>` 只剩明细里的打标控件；`#c-trend` 与 `#event-name-list` 都不存在；连续纪录只剩「当前连续先手 1 场」；调度卡一句话；控制台 0 错误。缓存失效参数 `0.5.2-no-bot-toggle` → `0.5.3-quiet-page`。

## 今日评价 v2 规划（2026-09-15，用户口径「这个体系不太行，重新规划」）

### 现状的三个毛病

用户原话：「我还是感觉今日评价这个体系不太行。」对照实现，问题有三个，都不是话术问题而是**选材与结构**问题：

1. **并列而非叙事**。现在是「按固定优先级取前两条事实，各自成句拼起来」。两句之间没有任何关系，读起来像两条互不相干的播报。例（2026-09-15 实际输出）：
   「又和 拿卡地贱民阿耶尼 碰上了，这缘分不浅。 24 场连轴转，牌桌都快坐穿了。」
2. **规则固定 → 天天同一句**。候选事实来自固定规则集，而本机 1.1 万场里大部分日子都会触发同样那 2–3 条规则，于是同一句调侃会反复出现。用户看到的「孽缘又续上了」正是这样。
3. **只看得见当天**。`highlights(rows)` 只拿到当天的行，说不出「这是你第 N 场争锋」「这个对手你上次赢了」「比上周同一天好」这类话，也挑不出「今天最值得记住的那一局」。

### 新体系：解说员模型

把评语从「事实清单」改成**一段三拍解说**：

| 拍 | 作用 | 长度 | 是否必有 |
|---|---|---|---|
| 开场 lede | 当天最值得说的一件事，带态度 | 一句 | 有对局就必有 |
| 转折 turn | 让开场成立的那个「怎么发生的」 | 一句 | 戏剧分够高才有 |
| 收尾 kicker | 真正的「大日子」才给：一个预测或玩笑 | 一句 | 极少 |

**三拍必须分属不同「主题」**，避免同义反复——现在两条经常都在说先后手。主题划分：`运气`（先后手连击、偏斜、高胜率）／`对手`（重复主将、重复对手）／`节奏`（场次、闪电局、当天走势）。

### 选材：戏剧分，而不是优先级表

现在用固定优先级表（`_rank`：高胜率 → 离谱级连续 → … → 场次）。**优先级表的问题是没有量纲**：它只知道「A 类比 B 类重要」，不知道「今天这个 A 有多罕见」。

新体系给每个候选算一个戏剧分：

```
drama = 稀有度 × 分量 × 新鲜度 × 个人相关度
```

- **稀有度**：这件事多罕见。有理论概率的直接用（先后手连击已经在算 `probability`）；没有的用历史频次估（例如「同一天遇到同一对手 3 次」在历史上出现过几天）。
- **分量**：影响多大——胜率偏离、连击长度、场次。
- **新鲜度**：**最近 7 天说过同类事实就降权**。这是治「天天同一句」的关键，实现上把最近 7 天的对局重算一遍候选、统计各 `kind` 的出现次数即可，不需要新增持久化状态。
- **个人相关度**：涉及「你」的历史（宿敌、老对手、里程碑）加权。

开场取戏剧分最高者；转折取**不同主题**里分最高且过阈值者；收尾只在总分超过「大日子」阈值时出现。

### 新增候选类别（「放开想象」的部分）

从本机数据能算出来、且玩家真的会想看的：

| 类别 | 一句话 | 数据来源 | 依赖 |
|---|---|---|---|
| 崩盘／回魂 | 先赢后连输、先输后连赢——当天的转折点 | 当天有序对局 | 只需当天 |
| 闪电局 | 今天有 N 场在一分钟内结束 | `duration_sec` | 只需当天 |
| 主力套牌 | 今天主打的套牌战绩突出／拉胯 | 当天套牌分组 | 只需当天 |
| 里程碑 | 第 N 场、第 N 场争锋、累计胜场整数关口 | 全库累计计数 | 需全库上下文 |
| 复仇 | 今天赢了之前连输 N 次的对手 | 对手名 + 历史战绩 | 需全库上下文 |
| 苦主 | 今天又输给一直输的那个对手 | 同上 | 需全库上下文 |
| 稀有对手 | 撞上很久没见的主将／对手 | 全库频次 | 需全库上下文 |
| 与昨天对比 | 比最近 30 天的自己好／差 | 已有 `history_summary` | 已有 |

### 呈现与话术

- 仍然**一段话、不折叠、不加区块**（用户口径：页面要少而准）。
- `level`（legendary／rare／unusual）改由**戏剧分**决定，不再绑在规则上——它决定左边色条与字号，应该反映「今天这事有多炸」而不是「命中了哪条规则」。
- 话术库按「**拍 × 类别**」组织，同一格多句轮换；种子仍按证据哈希，保证刷新不换句。
- 话术可引用的上下文扩充：现有 `{n}` `{name}` `{side}` `{hours}`，再加 `{wins}` `{losses}` `{total}`。

### 落地顺序

1. **选材引擎**（戏剧分 + 新鲜度降权）——不依赖新数据，先把 `_rank` 换掉。**已完成**。
2. **三拍结构**（lede／turn／kicker + 主题去重）——改 `highlights()` 的装配与 `plain` 拼装。**已完成**（实际是两拍：开场 + 转折；收尾在实测里没找到既稳定又不啰嗦的触发条件，先不做）。
3. 新类别按「数据可得性」逐个加：
   - **已完成（只需当天）**：崩盘／回魂、闪电局。
   - **已完成（2026-09-15）**：里程碑、复仇、苦主——`highlights()` 新增 `context` 入参，
     上下文由 `insights.history_context(dated, chosen)` 用**已经加载好的全量 rows** 算出来
     （`total_before` / `opponents` / `commanders`），**不新增持久化状态、也不额外查询**。
     触发条件：里程碑＝当天跨过 `MILESTONES` 里的整数关口（100/250/500/1000…，刻意稀疏）；
     复仇＝今天赢了「之前交手负 ≥2 且负 > 胜」的对手；苦主＝今天输给「从没赢过（负 ≥3、胜 0）」
     的对手。历史战绩**只算真人**（排除 `is_bot` 与 `AIBotMatch`，与「反复遇到的对手」同口径）。
   - **下一步**：~~主力套牌（当天套牌分组）、久违的主将~~ —— 见下。
   - **久违的主将（2026-09-15 已完成）**：见过、但距今 `RARE_COMMANDER_DAYS = 180` 天没再遇到；
     取缺得最久的那一个，≥365 天升 legendary。实测全历史 882 天会触发 **45 天 = 5%**，稀有度合适。
     **从没见过的不算**（那是「首次相遇」，不是「久违」）——`context["commanders"]` 里没有该 grpId
     时必须不报，否则新系列一上市就会天天触发。
   - **主力套牌（2026-09-15 量过之后否决，不做）**：实测 n≥5 的 692 天里，**65% 的日子一副牌占
     ≥90%、中位数 100%**——这个用户基本一天只打一副牌，报「今天主打 X」等于每天复述同一件事。
     **凡是「每天都在发生」的事实都不该进评语**，这跟场次那条是同一个道理。留着这个结论，
     以后别再提。
4. 全历史 882 天的触发频率实测（用于判断「会不会天天同一句」）：
   `play_draw_streak` 307 天、`hot_wr` 249、`volume` 226、`pd_skew` 88、`blitz` 31、
   `repeat_commander` 28、**`revenge` 24**、`arc` 23、`single` 16、**`milestone` 15**、
   `repeat_opponent` 5、**`nemesis` 2**。新加的三类都真的会触发，且都属稀有档。
