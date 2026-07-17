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
   - `NOTION_DATA_SOURCE_ID`: 你的“二档/三档订阅库”数据源 ID。请在 Notion 数据库的“管理数据源”菜单中使用“复制数据源 ID”；不要填写页面 URL 中的数据库 ID 或视图 ID。

3. 使用 Docker Compose 运行：
   ```bash
   docker compose up --build
   ```
   
> **提示**: 运行后会在终端看到同步日志，告诉你新增了几款游戏，移出了几款游戏。

脚本使用 Notion `2025-09-03` Data Sources API。同步前会校验订阅库的核心字段，避免误把一档会免库或其他数据库当作同步目标。`最后更新时间` 只在游戏新增、资料发生变化或出库时写入当前 UTC 时间；脚本不会自动回填历史数据。

## GitHub Actions 自动运行

仓库内置的 [`.github/workflows/sync.yml`](.github/workflows/sync.yml) 会在北京时间每月 11 日到 25 日的每天 23:00 自动同步，也可以在 GitHub 的 `Actions` 页面手动触发。

在仓库的 `Settings -> Secrets and variables -> Actions` 中配置以下 Repository secrets：

- `NOTION_API_KEY`
- `NOTION_DATA_SOURCE_ID`

工作流使用只读的 `GITHUB_TOKEN` 权限，先安装依赖并运行测试，再执行 `python sync.py`。同一时间只允许一个同步任务运行，避免重复写入。
