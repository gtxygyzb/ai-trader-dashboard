"""AI service v2 - Simplified version with all English docstrings to avoid encoding issues"""
import json
import time
from typing import List, Dict, Any, Optional, Iterator
import anthropic

import config

_KEY_CHAIN = [
    ("subscription", config.SUBSCRIPTION_KEY),
    ("pay_as_you_go", config.PAY_AS_YOU_GO_KEY),
]

_clients: Dict[str, anthropic.Anthropic] = {}


def _get_client(key_label: str = "subscription") -> anthropic.Anthropic:
    """Get client by key label."""
    if key_label not in _clients:
        key = dict(_KEY_CHAIN)[key_label]
        _clients[key_label] = anthropic.Anthropic(
            auth_token=key, base_url=config.ANTHROPIC_BASE_URL, timeout=120.0,
        )
    return _clients[key_label]


def _is_retriable(err: Exception) -> bool:
    """Check if error is auth/quota related (worth falling back)."""
    msg = str(err).lower()
    keys = ("auth", "401", "403", "quota", "rate", "limit", "credit")
    return any(k in msg for k in keys)


def _call_with_fallback(call_fn, *args, **kwargs):
    """Try each key in order; fall back on auth errors."""
    last_err = None
    for i, (label, _) in enumerate(_KEY_CHAIN):
        try:
            client = _get_client(label)
            return call_fn(client, *args, **kwargs), label
        except Exception as e:
            last_err = e
            print(f"[ai_service] {label} key failed: {e}", flush=True)
            if not _is_retriable(e):
                raise
            if i < len(_KEY_CHAIN) - 1:
                print(f"[ai_service] falling back...", flush=True)
    raise last_err


def _format_indices(indices, n=8):
    if not indices:
        return "(no data)"
    lines = []
    for i in indices[:n]:
        sign = "+" if i.get("change_pct", 0) >= 0 else ""
        lines.append("  %s: %s %s%.2f%%" % (i.get("name", ""), i.get("price", 0), sign, i.get("change_pct", 0)))
    return "\n".join(lines)


def _format_stocks(stocks, market_label="", n=5):
    if not stocks:
        return "(none)"
    lines = []
    for s in stocks[:n]:
        sign = "+" if s.get("change_pct", 0) >= 0 else ""
        lines.append("  [%s] %s: %s %s%.2f%%" % (
            s.get("code", ""), s.get("name", ""),
            s.get("price", 0), sign, s.get("change_pct", 0)))
    return "\n".join(lines)


def _format_sectors(sectors, n=5):
    if not sectors:
        return "(none)"
    lines = []
    for s in sectors[:n]:
        sign = "+" if s.get("change_pct", 0) >= 0 else ""
        leader = s.get("leader", "")
        lines.append("  %s %s%.2f%% (%s)" % (s.get("name", ""), sign, s.get("change_pct", 0), leader))
    return "\n".join(lines)


def _format_news(news_list, limit=6):
    if not news_list:
        return "(no news)"
    lines = []
    for n_ in news_list[:limit]:
        t = n_.get("time", "")
        title = n_.get("title", "")[:80]
        src = n_.get("source", "")
        line = "  [%s]" % src
        if t:
            line += " " + t
        line += " " + title
        lines.append(line)
    return "\n".join(lines)


def generate_brief(data):
    """Generate a market brief from market + news data."""
    indices = data.get("indices", [])
    a_gainers = data.get("a_gainers", [])
    a_losers = data.get("a_losers", [])
    hk_gainers = data.get("hk_gainers", [])
    hk_losers = data.get("hk_losers", [])
    sectors = data.get("sectors", [])
    concepts = data.get("concepts", [])
    ai_news = data.get("ai_news", [])
    finance_news = data.get("finance_news", [])

    prompt = (
        "You are a financial editor writing a daily market recap for retail A-share / HK-stock investors.\n"
        "Requirement: have the logic of professional analysis, but use language ordinary people can understand. "
        "Don't be so dumbed-down that it sounds like a neighborhood uncle chatting, but don't pile up jargon either.\n\n"
        "Based on the following real-time data at " + time.strftime("%Y-%m-%d %H:%M") + ", give a Chinese brief within 450 characters:\n\n"
        "[Market Snapshot]\n"
        "Core Indices: " + _format_indices(indices) + "\n"
        "Industry Sectors Top 5: " + _format_sectors(sectors, 5) + "\n"
        "Concept Sectors Top 5: " + _format_sectors(concepts, 5) + "\n"
        "A-share Gainers Top 5: " + _format_stocks(a_gainers, "A", 5) + "\n"
        "A-share Losers Top 5: " + _format_stocks(a_losers, "A", 5) + "\n"
        "HK-stock Gainers Top 5: " + _format_stocks(hk_gainers, "HK", 5) + "\n"
        "HK-stock Losers Top 5: " + _format_stocks(hk_losers, "HK", 5) + "\n\n"
        "[AI/Tech News] (6 items)\n" + _format_news(ai_news, 6) + "\n\n"
        "[Other Finance News] (4 items)\n" + _format_news(finance_news, 4) + "\n\n"
        "---\n\n"
        "Output format (Markdown, 4 sections):\n\n"
        "## Today's market view\n"
        "(A paragraph pointing out the overall market rhythm, who is leading, who is dragging. "
        "Be direct about the phenomenon and give your judgment, e.g. 'STAR 50 dropped 4% dragging the index, "
        "tech stocks are digesting last week's profit-taking'. DO NOT use terms like 'risk appetite' or 'style rotation'.)\n\n"
        "## Which sectors are moving\n"
        "(Name 2-3 specific sectors, explain why. Reference leaders and today's news.)\n\n"
        "## AI and tech circle news\n"
        "(Pick 2-3 important news, brief comment on impact. If any HK-stock LLM-related company has moves, highlight.)\n\n"
        "## Anomalies and risks\n"
        "(Name 1-2 anomalous stocks, explain reason. End with one risk tip.)\n\n"
        "---\n\n"
        "Writing style: OK to use rose/fell/pullback/breakout/leading/lagging. "
        "DO NOT use: risk appetite, high-low switch, structural differentiation, consensus expectation, valuation repair. "
        "Numbers + phenomena > vague adjectives. Sentences can be short, every section needs 'why' and 'what it means'."
    )

    def _do_call(client):
        return client.messages.create(
            model=config.ANTHROPIC_MODEL,
            max_tokens=4000,
            system="You are a competent financial editor. Write a daily market recap for retail investors. "
                   "Have the logic of professional analysis but use language ordinary people can understand. "
                   "Don't pile up jargon, don't be dumbed-down either.",
            messages=[{"role": "user", "content": [{"type": "text", "text": prompt}]}],
        )

    try:
        result = _call_with_fallback(_do_call)
        message, used_key = result
        out = ""
        for block in message.content:
            if block.type == "text":
                out += block.text
        if not out.strip():
            return "[简报生成失败] AI 返回为空，请稍后重试"
        return out.strip()
    except Exception as e:
        print("[ai_service] generate_brief error: %s" % e, flush=True)
        return "Error: AI brief generation failed: %s" % e


def analyze_stock(stock_info, extra_context=""):
    """Brief analysis of a single stock."""
    if not stock_info:
        return "No stock data"
    prompt = (
        "Briefly analyze this stock (200-400 Chinese characters), including:\n"
        "1. Current price level (high/low/mid)\n"
        "2. Short-term trend and possible reasons for moves\n"
        "3. Key points and risks\n\n"
        "Stock data:\n"
        "Name: %s\n"
        "Code: %s\n"
        "Price: %s\n"
        "Change%%: %s\n"
        "Open: %s\n"
        "High/Low: %s / %s\n"
        "Prev close: %s\n"
        "52w high/low: %s / %s\n"
        "Market cap: %s\n"
        "PE: %s\n"
        "PB: %s\n\n"
        "%s\n\n"
        "Output in Markdown."
    ) % (
        stock_info.get("name", ""), stock_info.get("code", ""),
        stock_info.get("price", ""), stock_info.get("change_pct", ""),
        stock_info.get("open", ""), stock_info.get("high", ""),
        stock_info.get("low", ""), stock_info.get("pre_close", ""),
        stock_info.get("high_52w", ""), stock_info.get("low_52w", ""),
        stock_info.get("market_cap", ""), stock_info.get("pe", ""),
        stock_info.get("pb", ""), extra_context,
    )

    def _do_call(client):
        return client.messages.create(
            model=config.ANTHROPIC_MODEL,
            max_tokens=1500,
            system="You are a rigorous quantitative analyst. Objectively analyze stocks, no investment advice.",
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
        return "Analysis failed: %s" % e


def chat(messages, rag_context=""):
    """Chat interface (non-streaming)."""
    system_prompt = (
        "You are a professional quantitative trading assistant and senior market analyst. "
        "You are good at A-shares, HK-stocks, US-stocks, especially AI/compute/semiconductor/tech sectors.\n\n"
        "Your principles:\n"
        "- Objective, rigorous, professional; concise and powerful answers\n"
        "- When judging stocks, analyze from fundamentals, technicals, news, valuation\n"
        "- Don't give direct investment advice, but provide professional perspective\n"
        "- Prioritize provided real-time data; if data missing, state it clearly\n"
        "- Have deep knowledge of AI LLM/compute/chip-related stocks (e.g. Zhipu, Tsinghua-related, "
        "Cambricon, Hygon, NVIDIA, TSMC, SMIC, Hua Hong, SenseTime, Tencent HunYuan, Xiaomi MiMo, etc.)\n"
        "- Markdown formatting, concise, high information density\n\n"
        "Reply in Chinese (unless user asks in English)"
    )
    if rag_context:
        system_prompt += "\n\n---\n# Real-time market background (RAG injected)\n%s\n---\n" % rag_context

    anthropic_messages = []
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", "")
        if role not in ("user", "assistant") or not content:
            continue
        anthropic_messages.append({"role": role, "content": [{"type": "text", "text": content}]})

    if not anthropic_messages:
        return "Please send a valid question."

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
        return out.strip() or "(No content returned)"
    except Exception as e:
        print("[ai_service] chat error: %s" % e, flush=True)
        return "Chat failed: %s" % e


def chat_stream(messages, rag_context=""):
    """Stream chat output chunk by chunk."""
    system_prompt = (
        "You are a professional quantitative trading assistant. "
        "Good at A-shares/HK-stocks/US-stocks, especially AI/compute/semiconductor/tech.\n"
        "Objective, rigorous, concise. Markdown formatting."
    )
    if rag_context:
        system_prompt += "\n\n---\n# Real-time market background\n%s\n---\n" % rag_context

    anthropic_messages = []
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", "")
        if role not in ("user", "assistant") or not content:
            continue
        anthropic_messages.append({"role": role, "content": [{"type": "text", "text": content}]})
    if not anthropic_messages:
        yield "Please send a valid question."
        return

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
                yield "\n\nChat failed: %s" % e
                return
            print("[ai_service] stream %s key failed: %s, falling back..." % (label, e), flush=True)


def build_rag_context(data):
    """Build RAG context from market data (slim, length-controlled)."""
    parts = ["Current: %s" % time.strftime("%Y-%m-%d %H:%M")]
    if data.get("indices"):
        parts.append("Indices: " + _format_indices(data["indices"][:6]))
    if data.get("sectors"):
        parts.append("Industry Sectors Top 3: " + _format_sectors(data["sectors"][:3], 3))
    if data.get("ai_news"):
        parts.append("AI News: " + _format_news(data["ai_news"][:5], 5))
    return "\n".join(parts)


def generate_deep_analysis(data):
    """Deep analysis combining history archive and real-time market data."""
    indices = data.get("indices", [])
    sectors = data.get("sectors", [])
    concepts = data.get("concepts", [])
    ai_news = data.get("ai_news", [])
    finance_news = data.get("finance_news", [])
    history = data.get("history", {})
    history_text = history.get("raw_text", "") if isinstance(history, dict) else ""

    prompt = (
        "You are a senior quant analyst + investment advisor.\n"
        "Task: based on today's real-time market + the past 7 days of history archive, "
        "give a deep investment analysis report.\n\n"
        "Part 1: Real-time Data\n"
        "Core Indices: " + _format_indices(indices) + "\n"
        "Industry Sectors Top 5: " + _format_sectors(sectors, 5) + "\n"
        "Concept Sectors Top 5: " + _format_sectors(concepts, 5) + "\n"
        "A-share Gainers Top 5: " + _format_stocks(data.get("a_gainers", []), "A", 5) + "\n"
        "A-share Losers Top 5: " + _format_stocks(data.get("a_losers", []), "A", 5) + "\n"
        "HK-stock Gainers Top 5: " + _format_stocks(data.get("hk_gainers", []), "HK", 5) + "\n"
        "HK-stock Losers Top 5: " + _format_stocks(data.get("hk_losers", []), "HK", 5) + "\n"
        "AI News: " + _format_news(ai_news, 5) + "\n"
        "Finance News: " + _format_news(finance_news, 4) + "\n\n"
        "Part 2: History Archive (last 7 days)\n"
        + (history_text if history_text else "(No history, first generation)") + "\n\n"
        "---\n\n"
        "Output format (Markdown, 500-800 characters):\n\n"
        "### Weekly trend review\n"
        "(Combine history index changes, summarize last week's market rhythm)\n\n"
        "### Current positioning\n"
        "(Talk about what stage the market is in)\n\n"
        "### Capital main line\n"
        "(Where has money gone? Why? Which sectors/themes are the core?)\n\n"
        "### AI sector judgment\n"
        "(Combine AI sector recent moves + HK-stock LLM-related stock performance + AI news)\n\n"
        "### Operation suggestions\n"
        "(2-3 specific suggestions)\n\n"
        "### Risk warnings\n"
        "(List 2-3 risks objectively)\n\n"
        "Writing requirements: Use plain Chinese, don't pile jargon. "
        "Every section needs 1-2 sentences. Numbers accurate. Don't repeat data."
    )

    def _do_call(client):
        return client.messages.create(
            model=config.ANTHROPIC_MODEL,
            max_tokens=2500,
            system="A friendly quant analyst. Professional but speak human.",
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
        print("[ai_service] deep_analysis error: %s" % e, flush=True)
        return "Deep analysis failed: %s" % e
