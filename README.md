# PS Plus Notion Sync

自动获取 PlayStation 官方的二档（升级）和三档（高级）游戏目录，并同步到你的 Notion 数据库中。

## 功能

1. **自动入库**: 发现新的二档/三档游戏时，自动在 Notion 中创建新行，并填入游戏名称、英文名称、支持平台、档位，并将状态设置为“在库”。
2. **自动出库**: 如果数据库中已存在某款游戏且状态为“在库”，但在最新的官方游戏目录中找不到该游戏，脚本会自动将其状态更新为“已出库”。

## 本地运行指南 (使用 Docker)

1. 克隆或下载本项目。
2. 复制 `.env` 模板文件并填入你的 Notion 配置：
   ```bash
   cp config.example .env
   ```
   编辑 `.env` 文件：
   - `NOTION_API_KEY`: 你的 Notion Integration 密钥 (格式如 `ntn_...`)。
   - `NOTION_DATABASE_ID`: 你的“二档/三档订阅库”数据库 ID。可以在浏览器打开该库，复制 URL 中 `?v=` 前的 32 位字符。

3. 使用 Docker Compose 运行：
   ```bash
   docker-compose up --build
   ```
   
> **提示**: 运行后会在终端看到同步日志，告诉你新增了几款游戏，移出了几款游戏。

## GitHub Actions 自动运行 (可选)

如果你希望完全自动化（例如每个月 20 号自动同步一次），你可以将这个代码仓库推送到你的私人 GitHub 仓库，并在 `Settings -> Secrets and variables -> Actions` 中配置以下环境变量：
- `NOTION_API_KEY`
- `NOTION_DATABASE_ID`

然后创建一个 `.github/workflows/sync.yml` 文件来定期触发 `python sync.py`。
