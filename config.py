"""项目配置文件 - AI API + 数据源配置

敏感信息（API key）通过 .env 文件管理：
1. 复制 .env.example 为 .env，填入真实 key
2. .env 已加入 .gitignore，不会被提交到 git
3. 代码通过 os.environ.get() 读取，缺 key 时给明显错误
"""
import os

def _load_env():
    """尝试从 .env 文件加载环境变量（不依赖 python-dotenv）"""
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if not os.path.isfile(env_path):
        return
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


_load_env()

# ============= AI API 配置 =============
# 套餐 key（优先使用，限额更稳定、单价更低）
SUBSCRIPTION_KEY = os.environ.get("SUBSCRIPTION_KEY", "")
# 按量 key（套餐失败时回落）
PAY_AS_YOU_GO_KEY = os.environ.get("PAY_AS_YOU_GO_KEY", "")
ANTHROPIC_BASE_URL = os.environ.get("ANTHROPIC_BASE_URL", "https://api.minimaxi.com/anthropic")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "MiniMax-M3")
API_TIMEOUT_MS = 3000000

# 默认环境变量（兼容旧代码）
os.environ.setdefault("ANTHROPIC_BASE_URL", ANTHROPIC_BASE_URL)
if SUBSCRIPTION_KEY:
    os.environ.setdefault("ANTHROPIC_API_KEY", SUBSCRIPTION_KEY)
    os.environ.setdefault("ANTHROPIC_AUTH_TOKEN", SUBSCRIPTION_KEY)

# ============= 服务配置 =============
SERVER_HOST = "127.0.0.1"
SERVER_PORT = 4444
DEBUG = False

# ============= 缓存配置 =============
CACHE_TTL_BRIEF = 30 * 60     # 简报缓存 30 分钟
CACHE_TTL_STOCKS = 5 * 60     # 股票数据缓存 5 分钟
CACHE_TTL_NEWS = 15 * 60      # 新闻缓存 15 分钟

# ============= 重点关注股票 =============
# 港股 AI / 科技股（README 中提到的：智谱、腾讯、小米、商汤、阿里、字节相关、中芯国际 等）
HK_FOCUS_STOCKS = {
    "00700": "腾讯控股",
    "01810": "小米集团-W",
    "09988": "阿里巴巴-W",
    "09618": "京东集团-SW",
    "03690": "美团-W",
    "01024": "快手-W",
    "09888": "百度集团-SW",
    "00981": "中芯国际",
    "01347": "华虹半导体",
    "00992": "联想集团",
    "01211": "比亚迪股份",
    "09866": "蔚来-SW",
    "09868": "小鹏汽车-W",
    "02015": "理想汽车-W",
    "03888": "金山软件",
    "00020": "商汤-W",
    "02013": "微盟集团",
    "06690": "海尔智家",
    "09992": "泡泡玛特",
    "01044": "恒安国际",
}

# A股 AI / 科技股
A_FOCUS_STOCKS = {
    "002230": "科大讯飞",
    "300750": "宁德时代",
    "688256": "寒武纪",
    "002415": "海康威视",
    "300059": "东方财富",
    "002594": "比亚迪",
    "300760": "迈瑞医疗",
    "000725": "京东方A",
    "002475": "立讯精密",
    "688981": "中芯国际",
    "688041": "海光信息",
    "300033": "同花顺",
    "601138": "工业富联",
    "603019": "中科曙光",
    "000977": "浪潮信息",
}

# 港股大模型核心股（README 提到的"智谱、minimax、腾讯、小米"中的港股）
# 注：智谱、minimax 暂未上市，列出关联 / 受益股
# ⚠️ 用户特别关注 HK0100：minimax-W（用户持仓 10万股 @810HKD，2026-06-01 买入）
HK_LLM_FOCUS = {
    "00700": "腾讯控股",     # 混元大模型 / 投资 Minimax
    "09988": "阿里巴巴-W",   # 通义千问
    "03690": "美团-W",       # 美团大模型
    "01024": "快手-W",       # 可灵大模型
    "09888": "百度集团-SW",  # 文心一言
    "00020": "商汤-W",       # 视觉大模型
    "01810": "小米集团-W",   # MiMo / 端侧大模型
    "00981": "中芯国际",     # AI 算力代工
    "00992": "联想集团",     # AI 服务器
    "09660": "地平线机器人-W",  # 智驾大模型芯片 + AI 算力
    "02513": "智谱",         # 智谱 AI（已申请港股 IPO）
    "00100": "minimax-W",    # 用户持仓：10万股 @810HKD
}

# 重点关注的 AI 相关关键词（用于新闻筛选）
AI_KEYWORDS = [
    "大模型", "AI", "人工智能", "算力", "GPT", "Claude", "Gemini",
    "智谱", "豆包", "通义千问", "DeepSeek", "Kimi", "OpenAI",
    "Anthropic", "英伟达", "NVIDIA", "GPU", "TPU", "ASIC",
    "GenAI", "生成式", "多模态", "Sora", "Llama", "Qwen",
    "Mistral", "推理", "训练", "Agent", "智能体", "MCP", "RAG",
    "MiniMax", "M1", "M2", "M3",
    "腾讯", "混元", "小米", "MiMo", "百度", "文心", "商汤",
    "字节", "阿里", "京东", "快手", "可灵",
    "中芯", "华虹", "海光", "寒武纪", "摩尔线程", "壁仞",
]

# ============= 历史目录 =============
HISTORY_DIR = "history"
