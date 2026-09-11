# 隐私说明 / Privacy

**一句话版本：这个插件默认离线运行，所有数据只存在你自己的电脑上；本仓库不包含任何人的对局数据。**

## 插件运行时

- 解析对象是你本机的 MTGA 日志文件（`Player.log` 等），只读，不修改
- 所有统计数据存入本地 SQLite（`data/mtga_stats.db`），不上传任何服务器
- Web 面板只绑定 `127.0.0.1`，**零 CDN、零外联**——断网也能用
- 对手名字、你的账号 ID 等仅用于本地展示，不会被插件发送到任何地方

## 本仓库

- `data/`（对局库、日志归档、示例抓取数据）与 `config.json` 均在 `.gitignore` 中，不会自动进入版本库
- 公开文档不应包含个人战绩；个人核对报告保存在被忽略的 data/ 下
- `tools/check_privacy.py` 在每次提交前扫描暂存区：命中 UUID / 用户 ID 模式 / 本机用户路径 / 数据库文件即拒绝提交
- 如你在 issue 或 PR 中贴出自己的日志，请先自行脱敏

## 可选的 Untapped 导入（默认关闭）

`config.json` 中的 `untapped_import` 段留空时完全不启用。填写后仅在**你主动运行**导入脚本时，从 Untapped 公开 API（untapped.gg，第三方服务）读取你自己的公开档案数据——这是你主动发起的外联，日常面板不自动抓取 Untapped。

## 卡名：默认离线读取本机客户端

`card_offline_seed` 默认开启。面板会**只读**打开你本机已安装的 MTGA 客户端数据文件
`MTGA_Data/Downloads/Raw/Raw_CardDatabase_*.mtga`，取出英文卡名写进本机缓存
`data/mtga_cards.db`。该文件实际是 SQLite 数据库，读取过程：

- 不联网、不发起任何请求；
- 只读打开（`mode=ro`），不修改客户端目录中的任何文件；
- 只读取卡牌编号与卡名，不读取、也不上传任何对局或个人数据。

关掉 `card_offline_seed` 即完全不触碰客户端数据目录。也可以用它替代：
`python -m tools.update_cards`（离线补英文名）或 `python -m tools.update_cards --online`（联网补英文与中文）。

## 可选卡名同步

`python -m tools.import_card_names --source <快照目录>` 只读取指定的本地中英文牌库与本插件的本地卡名库，生成被忽略的 `data/card_names.catalog.json`；不会联网，也不会改写对局。

`card_sync_enabled` 默认关闭。主动设置为 true 后，后台会查询 Scryfall 公开卡名与本地缓存；请求含卡牌标识，不含玩家名或对局记录。`tools.sync_card_names` 也是显式联网补漏工具。断网不影响已有统计和本地牌名目录。
