# 🚀 AI 量化分析终端

一个基于 Python + Flask 的轻量级量化分析软件，结合**实时行情爬取**与**AI 大模型分析**。

适合个人本地运行的 A 股 / 港股 / 美股监控面板，重点跟踪 AI 产业链、港股大模型公司、机器人概念。

## ✨ 功能概览

- **顶栏指数走马灯**：A 股（主板 + 创业板）、港股、亚太（日经225、韩国综指）、美股、外汇（美元指数、USD/CNH、USD/JPY、USD/KRW），**支持横向滚动**
- **AI 综合简报**：每日 400 字市场综述，后台异步生成（首次约 30 秒）
- **港股大模型核心股**：腾讯、阿里、百度、商汤、小米、中芯、联想、智谱、minimax 等
- **行业 / 概念板块涨幅榜**：自动剔除涨停、连板、季报等事件类题材，只保留真实概念
- **市场状态徽章**：自动识别盘中 / 午休 / 已收盘 / 周末休市
- **个股 AI 速评**：点击任一港股 AI 股票卡片的 "AI 速评" 按钮，后台生成专业分析
- **AI 智能问答**：流式 SSE 输出，可选注入 RAG 实时市场背景，支持 memory 上下文
- **历史归档**：每日简报 / 新闻 / 行情 / 聊天自动写入 `history/`（本地私有，不上传）
- **双 API 兜底**：套餐 key 失败时自动回落按量 key
- **用户 memory 持久化**：profile.md 自动累积持仓 / 关注 / 操作记录，给 AI 做长期 RAG 上下文

## 🛠 启动

### 1. 准备环境
```bash
conda activate aiquant  # 或你已有的环境
pip install -r requirements.txt
```

### 2. 配置 API Key
```bash
cp .env.example .env
# 编辑 .env，填入你的 SUBSCRIPTION_KEY / PAY_AS_YOU_GO_KEY
```

> 两个 key 至少填一个。优先使用 SUBSCRIPTION_KEY，失败时自动回落。

### 3. 启动
```bash
python start_app.py
```

启动后自动打开浏览器：**http://127.0.0.1:4444**

> 黑色控制台窗口会持续显示日志，**关闭窗口 = 停止服务**。所有日志同时写入 `start.log`（被 `.gitignore` 排除）。

## 🖥 页面布局

```
┌────────────────────────────────────────────┬──────────────┐
│  🔥 行业板块      💡 概念板块               │              │
│                                            │              │
├────────────────────────────────────────────┤              │
│  🧠 港股大模型相关股票（重点）              │              │
│  腾讯·阿里·百度·商汤·小米·中芯·联想…      │  💬 AI 问答  │
├────────────────────────────────────────────┤  (流式+RAG)  │
│  🇨🇳 国内 AI 要闻    🌍 国际 AI 要闻        │              │
├────────────────────────────────────────────┤              │
│  🤖 AI 综合简报                            │              │
├────────────────────────────────────────────┤              │
│  📊 深度分析（7 天历史 + 实时）            │              │
└────────────────────────────────────────────┴──────────────┘
```

## 🔑 关键设计

- **API Key 管理**：所有 key 通过 `.env` 读取，`.env` 被 `.gitignore` 排除。代码用 `os.environ.get()` 取，**永远不会硬编码在仓库里**。
- **数据源**：行情来自东方财富（4 域名故障转移），外汇来自新浪财经 `hq.sinajs.cn`，新闻多源聚合。
- **缓存**：30 分钟简报缓存 + 5 分钟行情缓存 + 15 分钟新闻缓存，避免反复爬虫。
- **memory 服务**：用户的持仓、关注、操作记录会自动追加到 `memory/profile.md`，AI 聊天时自动注入 RAG 上下文。
- **聊天历史**：每次对话自动写入 `history/YYYY-MM-DD/chat.jsonl`，刷新页面可恢复。

## 📂 项目结构

```
.
├── app.py                  # Flask 主入口 + 所有 API 路由
├── config.py               # 配置（API key 从 .env 读）
├── start_app.py            # 一键启动（带日志、浏览器自动开、端口清理）
├── requirements.txt
├── .env.example            # API key 模板（复制为 .env 后填真实 key）
├── .gitignore              # 排除 .env、history/、memory/、start.log
├── services/
│   ├── stock_service.py    # 行情爬虫（东财 4 域名 + 新浪外汇）
│   ├── news_service.py     # 新闻聚合
│   ├── ai_service.py       # AI 简报 / 聊天 v1
│   ├── ai_service_v2.py    # AI 简报 / 聊天 v2（带 RAG）
│   ├── aggregator.py       # 并行数据聚合 + 多级缓存
│   ├── history_service.py  # 历史归档（chat.jsonl / daily_news 等）
│   ├── memory_service.py   # 用户画像 / memory RAG
│   └── market_status.py    # A股 / 港股交易状态判断
├── templates/
│   └── index.html
└── static/
    ├── style.css           # 浅色主题
    └── app.js              # 前端逻辑
```

## 🛡 隐私设计

| 文件/目录 | 是否上传 | 原因 |
|---|---|---|
| `app.py` / `services/` / `templates/` / `static/` | ✅ 上传 | 公开代码 |
| `config.py` | ✅ 上传（已脱敏） | key 全部从 `.env` 读，无明文 |
| `.env` | ❌ 上传 | 包含真实 API key |
| `.env.example` | ✅ 上传 | 占位符模板 |
| `history/` | ❌ 上传 | 你的聊天记录 + 持仓信息 |
| `memory/` | ❌ 上传 | 你的完整投资画像 |
| `start.log` | ❌ 上传 | 含 API 调用记录 |
| `__pycache__/` | ❌ 上传 | Python 缓存 |

## ⚠️ 风险提示

本项目完全由Claude Vibe Coding + Minimax-M3模型生成，仅供个人使用！

本软件仅供学习研究使用，**不构成任何投资建议**。投资有风险，入市需谨慎。

## 📄 License

MIT License

Copyright (c) 2026 gtxygyzb

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
