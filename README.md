# MTGA 先后手统计面板

> MTGA（万智牌：竞技场）本地对局统计工具：从客户端日志解析每一场对局，回答一个问题——**你先手赢多还是后手赢多？近期体感与记录是否一致？**

## 不会使用 GitHub？从这里下载

### [点这里直接下载最新版 Windows ZIP](https://github.com/playMTG/mtga-play-draw-stats/releases/latest)

[查看版本说明和全部发行版](https://github.com/playMTG/mtga-play-draw-stats/releases)

这是 Windows 本地工具，不需要安装 Git，也不需要注册 GitHub 账号。下载后按下面操作：

1. 打开下载文件夹，找到名称中带 `windows.zip` 的发行包。
2. 右键压缩包，选择 **“全部解压缩”**。不要直接在压缩包预览窗口里运行文件。
3. 如果电脑尚未安装 Python，先从 [Python 官网](https://www.python.org/downloads/windows/)下载安装 Python 3.11 或更高版本；安装界面勾选 **Add Python to PATH**。
4. 打开解压后的 `mtga-play-draw-stats-v0.1.0` 文件夹，双击 **`start.bat`**。
5. 第一次运行会自动准备环境，可能需要半分钟左右；完成后浏览器会自动打开统计面板。

如果上面的直链没有开始下载：进入 [Releases 页面](https://github.com/playMTG/mtga-play-draw-stats/releases/latest)，展开 **Assets**，再点击名称中带 `windows.zip` 的文件。

> 下载的是完整项目压缩包，不是单独的 `.exe` 安装程序。以后更新时重新下载 ZIP 并解压即可；覆盖或删除旧文件夹前，请先保留其中的 `data` 目录和 `config.json`（如果存在），它们包含个人对局资料与本机设置。

[![Python](https://img.shields.io/badge/Python-3.11+-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green)](LICENSE)

## 功能

- **先后手胜率看板**：先手 / 后手胜率、样本量、Wilson 95% 置信区间，按赛事 / 套牌 / 时间细分，局数分布一目了然
- **近期分项观察**：近 7 天 / 30 天 / 全史首页只显示一两条重点摘要；先后手有效分母直接可见，详细分布、p 值、资料覆盖和统计限制可展开查看，不以综合分判定平台意图。
- **每日战报**：今天、昨天和指定日期的战绩、先后手与常遇主将；支持全部赛制。资料缺失只在确有影响时提示，完整覆盖率可展开查看。明细默认按日期分组，可按赛事、套牌或主将分组并翻页；直接显示我的套牌／主将，诊断字段收进展开详情。
- **分赛事历史变化**：日报按赛事和 BO 模式显示可比历史变化；30 天是查找窗口，不是等待期限。没有可靠基线时仍显示当天胜负事实，不解释成匹配原因。
- **BO 模式与逐局记录**：首页全部统计可统一筛选 BO1、BO3 或未知；对局明细可展开日志中实际保存的每局先后手与胜负。整场战绩与逐局结果分开显示，不用整场结果补猜缺失局。
- **套牌独立详情**：点击明细里的套牌，查看今天、昨天、近 20 场、近 7 天或全部记录；默认汇总这套牌的全部构筑版本，也可限定单一版本。套牌身份优先按 ID 与构筑指纹连接，改名可延续，同名无关套牌不会直接混在一起。
- **套牌 × 对手主将**：在套牌详情中查看常遇主将的出现占比、先后手局数、交手战绩和分先后手胜率；占比明确使用主将已知对局作分母，点选主将可回查当前范围内全部对应记录。
- **小样本亮点评价**：当天或套牌范围内从连续 3 把先手／后手开始给出带数字的评价；连续段越罕见，文字和显示越醒目。可展开查看 50% 独立参考模型、整段扫描概率与逐场依据，并明确不把它称为“被针对概率”。
- **对手主将档案**：每个对手主将的交手次数、总胜率、先后手拆分胜率，支持手动打标 + 先验自动映射
- **构筑对手类型**：明确的非主将构筑对局可逐场标注、修改或清除快攻、控制、组合技等类型；显示已标注覆盖率，未标注时不自动猜测。轮抽、现开和规则未知活动不进入分母。
- **调度（Mulligan）分析**：首页显示调度资料覆盖及有／无调度的整场胜率；逐次留牌、未知量、来源与 BO3 分母区别可展开查看
- **段位曲线**：构组 / 限绘双轨段位历史变化
- **实时监听**：面板运行时自动增量解析新对局，处理日志轮换与未写完的行
- **统一范围筛选**：赛制大类、赛事、BO 模式与套牌共同作用于首页统计，选项带样本量
- **CSV 导出**：对局明细 / 段位快照，Excel 直接打开不乱码
- **中文卡名**：对手主将与卡牌共用本地中英文目录；中文优先、英文可查，并显示译名来源；缺译名的牌面回落英文

## 快速开始

### 环境要求

- Windows 10/11
- [Python 3.11+](https://www.python.org/downloads/)（安装时勾选 **Add to PATH**）
- MTGA 客户端已在本机运行过（产生过日志）

### 客户端兼容性

- **官方客户端 / Steam 客户端均支持**：实时日志（Player.log）两客户端路径相同，自动读取；历史会话日志（UTC_Log-\*.log）自动探测官方客户端默认安装位置与 Steam 全部游戏库（多库安装也能找到）
- 安装在非默认位置？在项目根目录 `config.json`（首次运行后手动创建）里加：

  ```json
  { "log_paths": { "session_logs_extra": ["D:\\MyGames\\MTGA\\MTGA_Data\\Logs\\Logs"] } }
  ```

- **汉化 mod 兼容**：解析按 JSON 结构匹配，日志中的中文（卡名 / 玩家名等）完整无损，纯英文的原生日志同样支持

### 已下载并解压：双击运行

1. 双击 **`start.bat`** —— 首次运行会自动创建虚拟环境并安装依赖，然后自动打开浏览器进入面板
2. 停止：双击 `stop.bat`，或关闭最小化的 "MTGA Panel" 窗口
3. （可选）双击 **`register_task.bat`** 注册 Windows 计划任务：开机自启 + 崩溃自动重启

### 手动运行

```bash
pip install -r requirements.txt
python -m app.main
# 浏览器打开 http://127.0.0.1:8765
```

首次启动会自动回填全部历史日志并归档历史会话日志（防客户端清理丢失）。

## 隐私承诺

- **默认离线**：面板仅监听 `127.0.0.1`，对局保存在本地。可用 `python -m tools.import_card_names --source <快照目录>` 导入本地中英文牌库；`card_sync_enabled` 默认关闭，手动启用的在线补漏范围见隐私说明。
- **零采集**：所有数据只存在本机 SQLite，仓库本身不含任何真实对局数据
- **可验证**：`tools/check_privacy.py` 在提交前扫描整个仓库，拦截 userId、玩家名等敏感信息
- 日志路径等个性化配置全部走本机 `config.json`（已被 .gitignore 排除）

## 技术栈

Python 3.11+ · FastAPI · SQLite（WAL）· Chart.js（本地文件，零 CDN）

```
app/
  parser.py    日志行切分与 JSON 提取（跨行块合并、字节偏移 tail）
  events.py    事件分类器：日志行流 → 对局结构化记录
  watcher.py   增量监听：滚动检测 + 逻辑记录组装
  backfill.py  历史回填 CLI（Player.log / Player-prev.log / Steam 会话日志 / 归档）
  archive.py   会话日志归档防丢
  store.py     SQLite 持久化：幂等 upsert、子表合并、轻量迁移
  stats.py     统计口径唯一实现（Wilson 区间、卡方、二项检验）
  deck_detail.py 套牌身份连接、时间范围与构筑版本拆分
  targeting.py 被针对指数的零依赖统计原语
  main.py      FastAPI 入口：静态面板 + JSON API + 启动回填
web/           单页面板（原生 JS + Chart.js）
tests/         合成数据回归测试（合成日志 fixtures，不含真实数据）
```

## 开发

```bash
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest tests/ -q          # 运行测试
python tools/check_privacy.py       # 提交前隐私扫描
```

设计文档（日志字段实测依据、统计口径约定、功能清单）见 [docs/DESIGN.md](docs/DESIGN.md)。

## 免责声明

本项目是粉丝作品，与 Wizards of the Coast 无关。MTGA 及相关商标属 Wizards of the Coast LLC。本工具只读取本机日志，不修改游戏文件、不与游戏进程交互，属于被动观察工具。

## License

[MIT](LICENSE)
