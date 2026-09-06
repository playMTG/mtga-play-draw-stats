# MTGA 先后手统计面板

> MTGA（万智牌：竞技场）本地对局统计工具：从客户端日志解析每一场对局，回答一个问题——**你先手赢多还是后手赢多？对手是不是在针对你？**

[![Python](https://img.shields.io/badge/Python-3.11+-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green)](LICENSE)

## 功能

- **先后手胜率看板**：先手 / 后手胜率、样本量、Wilson 95% 置信区间，按赛事 / 套牌 / 时间细分，局数分布一目了然
- **「你被针对了吗」指数**：四维度运气审计（先后手运 / 对手运 / 起手调度运 / 连败运）合成 0-100 分，统计检验给出"正常 / 可疑 / 被针对"结论，附克星对手预警
- **对手主将档案**：每个对手主将的交手次数、总胜率、先后手拆分胜率，支持手动打标 + 先验自动映射
- **调度（Mulligan）分析**：调度次数与胜负关联、留牌分布
- **段位曲线**：构组 / 限绘双轨段位历史变化
- **实时监听**：面板运行时自动增量解析新对局，MTGA 重启无遗漏
- **三级级联筛选**：赛制大类 → 赛事 → 套牌，选项带样本量
- **CSV 导出**：对局明细 / 段位快照，Excel 直接打开不乱码
- **中文卡名**：对手主将显示简中卡名（无简中印刷时回落英文）

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

### 双击运行（推荐）

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

- **零外联**：面板仅监听 `127.0.0.1`，不访问任何网络、不上传任何数据
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
  store.py     SQLite 持久化：幂等 upsert、子表重写、轻量迁移
  stats.py     统计口径唯一实现（Wilson 区间、卡方、二项检验）
  targeting.py 被针对指数的零依赖统计原语
  main.py      FastAPI 入口：静态面板 + JSON API + 启动回填
web/           单页面板（原生 JS + Chart.js）
tests/         56 个单元测试（合成日志 fixtures，不含真实数据）
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
