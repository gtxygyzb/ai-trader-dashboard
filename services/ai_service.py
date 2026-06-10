"""AI 服务 - 使用 MiniMax (Anthropic 兼容) 完成综合分析与对话
双 API 策略：优先套餐 key，失败回落按量 key
"""
import json
import time
from typing import List, Dict, Any, Optional, Iterator
import anthropic

import config  # noqa: F401  ensure env vars set


# 套餐 / 按量 key 列表（按优先级）
_KEY_CHAIN = [
    ("subscription", config.SUBSCRIPTION_KEY),
    ("pay_as_you_go", config.PAY_AS_YOU_GO_KEY),
]

_clients: Dict[str, anthropic.Anthropic] = {}


def _get_client(key_label: str = "subscription") -> anthropic.Anthropic:
    """Get the anthropic client for the given key (lazy load)."""
    if key_label not in _clients:
        key = dict(_KEY_CHAIN)[key_label]
        _clients[key_label] = anthropic.Anthropic(
            auth_token=key,
            base_url=config.ANTHROPIC_BASE_URL,
            timeout=120.0,
        )
    return _clients[key_label]


def _is_retriable(err: Exception) -> bool:
    """Check if we should try the next key on auth/quota errors."""
    msg = str(err).lower()
    keys = ("auth", "401", "403", "quota", "rate", "limit", "credit", "余额", "欠费", "permission")
    return any(k in msg for k in keys)


def _call_with_fallback(call_fn, *args, **kwargs):
    """对 _call_fn(client, *args, **kwargs) 依次尝试 key，
    鉴权类错误自动 fallback 到下一个 key
    """
    last_err = None
    for i, (label, _) in enumerate(_KEY_CHAIN):
        try:
            client = _get_client(label)
            return call_fn(client, *args, **kwargs), label
        except Exception as e:
            last_err = e
            print(f"[ai_service] {label} key failed: {e}", flush=True)
            if not _is_retriable(e):
                # 非鉴权类错误直接抛
                raise
            if i < len(_KEY_CHAIN) - 1:
                print(f"[ai_service] falling back to next key...", flush=True)
    raise last_err  # type: ignore


def _format_indices(indices: List[Dict[str, Any]]) -> str:
    if not indices:
        return "(指数数据缺失)"
    lines = []
    for i in indices[:8]:  # 限 8 个
        sign = "▲" if i.get("change_pct", 0) >= 0 else "▼"
        lines.append(f"  {i['name']}: {i.get('price', 0)} {sign}{i.get('change_pct', 0)}%")
    return "\n".join(lines)


def _format_stocks(stocks: List[Dict[str, Any]], market_label: str = "", n: int = 5) -> str:
    if not stocks:
        return "(无)"
    lines = []
    for s in stocks[:n]:
        sign = "▲" if s.get("change_pct", 0) >= 0 else "▼"
        lines.append(f"  [{s.get('code', '')}] {s.get('name', '')}: "
                     f"{s.get('price', 0)} {sign}{s.get('change_pct', 0)}%")
    return "\n".join(lines)


def _format_sectors(sectors: List[Dict[str, Any]], n: int = 5) -> str:
    if not sectors:
        return "(无)"
    lines = []
    for s in sectors[:n]:
        sign = "▲" if s.get("change_pct", 0) >= 0 else "▼"
        leader = s.get("leader", "")
        lines.append(f"  {s['name']} {sign}{s.get('change_pct', 0)}% (领涨: {leader})")
    return "\n".join(lines)


def _format_news(news_list: List[Dict[str, Any]], limit: int = 6) -> str:
    """Format news with title+time only to save tokens."""
    if not news_list:
        return "(无新闻)"
    lines = []
    for n in news_list[:limit]:
        t = n.get("time", "")
        title = n.get("title", "")[:80]
        src = n.get("source", "")
        line = f"  [{src}]"
        if t:
            line += f" {t}"
        line += f" {title}"
        lines.append(line)
    return "\n".join(lines)


# ============ 综合简报 ============

def generate_brief(data: Dict[str, Any]) -> str:
    """Generate a market brief from market + news data (slimmed context, 60% faster)."""
    indices = data.get("indices", [])
    a_gainers = data.get("a_gainers", [])
    a_losers = data.get("a_losers", [])
    hk_gainers = data.get("hk_gainers", [])
    hk_losers = data.get("hk_losers", [])
    sectors = data.get("sectors", [])
    concepts = data.get("concepts", [])
    ai_news = data.get("ai_news", [])
    finance_news = data.get("finance_news", [])

    prompt = f"""你是一位资深的财经编辑，给 A 股 / 港股的散户投资者写今日复盘。
要求：**有专业分析的逻辑，但用普通人的语言讲**。不要小白到"隔壁大爷唠嗑"那种，但也不要堆砌专业黑话。

基于以下 {time.strftime('%Y-%m-%d %H:%M')} 实时数据，给出**不超过 450 字**的中文简报：

【行情速览】
核心指数: {_format_indices(indices)}
行业板块TOP: {_format_sectors(sectors, 5)}
概念板块TOP: {_format_sectors(concepts, 5)}
A股涨幅TOP5: {_format_stocks(a_gainers, 'A', 5)}
A股跌幅TOP5: {_format_stocks(a_losers, 'A', 5)}
港股涨幅TOP5: {_format_stocks(hk_gainers, 'HK', 5)}
港股跌幅TOP5: {_format_stocks(hk_losers, 'HK', 5)}

【AI/科技要闻】(6条)
{_format_news(ai_news, 6)}

【财经要闻】(4条)
{_format_news(finance_news, 4)}

---

## 输出格式（Markdown，4 段）

## 今天市场怎么看
（一段话点出大盘整体节奏、谁是主力、谁在拖累。**直白讲现象 + 给出你的判断**，比如"科创板跌 4% 拖累整体，科技股今天在消化上周的获利盘"。**不要讲"风险偏好""高低切"这些术语**。）

## 哪些板块在动
（点名 2-3 个具体板块，说明为什么动——是政策、业绩、消息面还是资金切换。结合领涨股和今日新闻佐证。）

## AI 和科技圈有什么动静
（挑 2-3 条重要新闻，简评影响。如果有港股大模型相关公司的动作，重点提。）

## 异动与风险
（点名 1-2 只异动股，说明原因。结尾给一句风险提示，比如"小盘题材股波动大、今天分化明显、追高谨慎"这类。）

---

**写作风格要求**：
✅ **可以用的词**：上涨/下跌/回调/突破/领涨/领跌/业绩兑现/资金切换/估值合理/补涨/放量/缩量
❌ **不要用**：风险偏好上行/下行、高低切、软切硬、跷跷板效应、资金主战场、一致预期、估值修复、结构性分化、做多情绪
✅ **数字 + 现象** 比空泛的形容词有说服力
✅ **句子可以短**，但每段都要有"为什么"和"意味着什么"
✅ **不重复罗列数据**，重点是分析判断

    def _do_call(client):
        return client.messages.create(
            model=config.ANTHROPIC_MODEL,
            max_tokens=1800,
            system="你是一位有水平的财经编辑，给散户讲今日市场复盘。专业分析的逻辑要有，但用普通人能听懂的语言。不堆砌专业黑话，也不刻意小白。",
            messages=[{"role": "user", "content": [{"type": "text", "text": prompt}]}],
        )
    try:
        message, used_key = _call_with_fallback(_do_call)
        out_text = ""
        for block in message.content:
            if block.type == "text":
                out_text += block.text
        return out_text.strip()
    except Exception as e:
        print(f"[ai_service] generate_brief error: {e}", flush=True)
        return f"⚠️ AI 简报生成失败: {e}"


# ============ 单只股票分析 ============

def analyze_stock(stock_info, extra_context=''):
    """Analyze a single stock briefly."""
    if not stock_info:
        return "未获取到该股票数据"
    prompt = f"""请对以下股票给出简要分析（200-400 字），包含:
1. 当前价格水平判断（高/低位/中位）
2. 短期趋势与异动可能原因
3. 关注点与风险提示

股票数据:
- 名称: {stock_info.get('name', '')}
- 代码: {stock_info.get('code', '')}
- 现价: {stock_info.get('price', '')}
- 涨跌幅: {stock_info.get('change_pct', '')}%
- 今日开盘: {stock_info.get('open', '')}
- 最高/最低: {stock_info.get('high', '')} / {stock_info.get('low', '')}
- 昨收: {stock_info.get('pre_close', '')}
- 52周高/低: {stock_info.get('high_52w', '')} / {stock_info.get('low_52w', '')}
- 市值: {stock_info.get('market_cap', '')}
- 市盈率(PE): {stock_info.get('pe', '')}
- 市净率(PB): {stock_info.get('pb', '')}

{extra_context}

请输出 Markdown 格式。
"""
    def _do_call(client):
        return client.messages.create(
            model=config.ANTHROPIC_MODEL,
            max_tokens=1500,
            system="你是一位严谨的量化分析师，客观分析股票，不构成投资建议。",
            messages=[{"role": "user", "content": [{"type": "text", "text": prompt}]}],
        )
    try:
        message, _ = _call_with_fallback(_do_call)
        out = ""
        for block in message.content:
            if block.type == "text":
                out += block.text
        return out.strip()
    except Exception as e:
        return f"⚠️ 分析失败: {e}"


# ============ 聊天对话（带 RAG 上下文） ============

def chat(messages: List[Dict[str, str]], rag_context: str = "") -> str:
    """对话接口（非流式）
    messages: [{"role": "user"|"assistant", "content": "..."}]
    rag_context: 可注入的实时市场/新闻摘要，用于 RAG 增强
    """
    system_prompt = """你是一位专业的量化交易助手与资深市场分析师，擅长 A股、港股、美股，特别精通 AI/算力/半导体/科技板块。

你的工作原则：
- 客观、严谨、专业，回答精炼有力
- 涉及股票判断时，会从基本面、技术面、消息面、估值水平多维度分析
- 不直接给出投资建议，但可以提供专业分析视角
- 优先使用提供的实时数据；若数据缺失，明确说明
- 对 AI 大模型、算力、芯片相关股票（如智谱、寒武纪、海光、英伟达、中芯国际、商汤、华为概念等）有深入了解
- 关注公司：腾讯、阿里、小米、字节、百度、京东、美团、快手、商汤、寒武纪、中芯国际、海光、科大讯飞、宁德时代、比亚迪、Anthropic、OpenAI、Google、Meta、NVIDIA、AMD、TSMC 等
- 用 Markdown 排版，简洁、信息量大

回答语言：中文（除非用户用英文提问）
"""
    if rag_context:
        system_prompt += f"\n\n---\n# 当前实时市场背景（RAG 注入，仅供参考）\n{rag_context}\n---\n"

    # 格式化 messages 给 Anthropic SDK
    anthropic_messages = []
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", "")
        if role not in ("user", "assistant") or not content:
            continue
        anthropic_messages.append({
            "role": role,
            "content": [{"type": "text", "text": content}],
        })

    if not anthropic_messages:
        return "请发送有效问题。"

    def _do_call(client):
        return client.messages.create(
            model=config.ANTHROPIC_MODEL,
            max_tokens=2500,
            system=system_prompt,
            messages=anthropic_messages,
        )
    try:
        message, _ = _call_with_fallback(_do_call)
        out = ""
        for block in message.content:
            if block.type == "text":
                out += block.text
        return out.strip() or "（模型未返回内容）"
    except Exception as e:
        print(f"[ai_service] chat error: {e}", flush=True)
        return f"⚠️ 对话失败: {e}"


def chat_stream(messages: List[Dict[str, str]], rag_context: str = "") -> Iterator[str]:
    """Stream chat output chunk by chunk."""
    system_prompt = """你是一位专业的量化交易助手与资深市场分析师，擅长 A股、港股、美股，特别精通 AI/算力/半导体/科技板块。

你的工作原则：
- 客观、严谨、专业，回答精炼有力
- 涉及股票判断时，会从基本面、技术面、消息面、估值水平多维度分析
- 不直接给出投资建议，但可以提供专业分析视角
- 优先使用提供的实时数据；若数据缺失，明确说明
- 用 Markdown 排版，简洁、信息量大
"""
    if rag_context:
        system_prompt += f"\n\n---\n# 当前实时市场背景\n{rag_context}\n---\n"

    anthropic_messages = []
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", "")
        if role not in ("user", "assistant") or not content:
            continue
        anthropic_messages.append({
            "role": role,
            "content": [{"type": "text", "text": content}],
        })
    if not anthropic_messages:
        yield "请发送有效问题。"
        return

    def _do_stream(client):
        return client.messages.stream(
            model=config.ANTHROPIC_MODEL,
            max_tokens=2500,
            system=system_prompt,
            messages=anthropic_messages,
        )

    # 先尝试订阅 key
    last_err = None
    for i, (label, _) in enumerate(_KEY_CHAIN):
        client = _get_client(label)
        try:
            with client.messages.stream(
                model=config.ANTHROPIC_MODEL,
                max_tokens=2500,
                system=system_prompt,
                messages=anthropic_messages,
            ) as stream:
                for text in stream.text_stream:
                    if text:
                        yield text
            return
        except Exception as e:
            last_err = e
            if not _is_retriable(e) or i == len(_KEY_CHAIN) - 1:
                yield f"\n\n⚠️ 对话失败: {e}"
                return
            print(f"[ai_service] stream {label} key failed: {e}, falling back...", flush=True)


def build_rag_context(data: Dict[str, Any]) -> str:
    """Build RAG context from market data (slim, length-controlled)."""
    parts = []
    parts.append(f"当前: {time.strftime('%Y-%m-%d %H:%M')}")
    if data.get("indices"):
        parts.append("指数: " + _format_indices(data["indices"][:6]))
    if data.get("sectors"):
        parts.append("行业板块TOP: " + _format_sectors(data["sectors"][:3], 3))
    if data.get("ai_news"):
        parts.append("AI要闻: " + _format_news(data["ai_news"][:5], 5))
    return "\n".join(parts)


def generate_deep_analysis(data: Dict[str, Any]) -> str:
    """Deep analysis combining history archive and real-time market data."""
    indices = data.get("indices", [])
    sectors = data.get("sectors", [])
    concepts = data.get("concepts", [])
    ai_news = data.get("ai_news", [])
    finance_news = data.get("finance_news", [])
    history = data.get("history", {})
    history_text = history.get("raw_text", "") if isinstance(history, dict) else ""

    prompt = f"""你是一位资深的量化分析师 + 投资顾问。
**任务**：基于今天的实时行情 + 过去 7 天的历史归档，给出一份**深度投资分析报告**。

## 一、当前实时数据
核心指数: {_format_indices(indices)}
行业板块TOP: {_format_sectors(sectors, 5)}
概念板块TOP: {_format_sectors(concepts, 5)}
A股涨幅TOP5: {_format_stocks(data.get('a_gainers', []), 'A', 5)}
A股跌幅TOP5: {_format_stocks(data.get('a_losers', []), 'A', 5)}
港股涨幅TOP5: {_format_stocks(data.get('hk_gainers', []), 'HK', 5)}
港股跌幅TOP5: {_format_stocks(data.get('hk_losers', []), 'HK', 5)}
AI要闻: {_format_news(ai_news, 5)}
财经要闻: {_format_news(finance_news, 4)}

## 二、历史归档（最近 7 天）
{history_text if history_text else '(无历史记录，本次为首次生成)'}

---

## 输出格式（Markdown，500-800 字）

### 一周走势回顾
（结合历史归档的指数变化，总结最近一周大盘节奏：涨/跌/震荡，哪几天是转折点）

### 当前定位
（用白话讲当下市场处于什么阶段：是反弹/回调/震荡/突破/破位？类似"现在大盘在 X 位置，类似历史上 Y 时刻"）

### 资金主线
（资金跑去哪了？为什么？哪几个板块/主题是本轮核心？结合 7 天新闻佐证）

### AI 板块判断
（结合 AI 板块的最近异动 + 港股大模型相关股票表现 + AI 新闻，给出对 AI 板块的判断）

### 操作建议
（白话讲，给 2-3 条具体建议：规避什么 / 关注什么 / 何时加仓等）

### 风险提示
（客观列 2-3 条风险）

**写作要求**：
- 用大白话，不要堆术语（不要"风险偏好""结构性分化"这些）
- 段间用 1-2 句话讲清楚逻辑
- 数字一定要准确
- 不要重复罗列数据
"""

    def _do_call(client):
        return client.messages.create(
            model=config.ANTHROPIC_MODEL,
            max_tokens=2500,
            system="一个会聊天的股友 + 量化分析师。专业但说人话。",
            messages=[{"role": "user", "content": [{"type": "text", "text": prompt}]}],
        )
    try:
        message, used_key = _call_with_fallback(_do_call)
        out = ""
        for block in message.content:
            if block.type == "text":
                out += block.text
        return out.strip()
    except Exception as e:
        print(f"[ai_service] deep_analysis error: {e}", flush=True)
        return f"⚠️ 深度分析生成失败: {e}"
