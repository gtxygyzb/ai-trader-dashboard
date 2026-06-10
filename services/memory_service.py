"""Memory service - user profile & daily summary RAG for prompts
文件夹 E:\Trading\memory\，每日总结 + 用户画像
"""
import os
import json
import time
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from threading import Lock

import config

_write_lock = Lock()

MEMORY_DIR = "memory"
PROFILE_FILE = "profile.md"  # 总的画像文件
DAILY_DIR = "daily"           # 每日总结


def _ensure_dir():
    os.makedirs(MEMORY_DIR, exist_ok=True)
    os.makedirs(os.path.join(MEMORY_DIR, DAILY_DIR), exist_ok=True)


def _today_str():
    return datetime.now().strftime("%Y-%m-%d")


def get_profile() -> str:
    """读取用户画像（总 markdown）"""
    _ensure_dir()
    p = os.path.join(MEMORY_DIR, PROFILE_FILE)
    if not os.path.isfile(p):
        return "(No user profile yet)"
    with open(p, "r", encoding="utf-8") as f:
        return f.read()


def get_recent_daily(days: int = 3) -> str:
    """读取最近 N 天的每日总结"""
    _ensure_dir()
    daily_dir = os.path.join(MEMORY_DIR, DAILY_DIR)
    if not os.path.isdir(daily_dir):
        return ""
    files = sorted(os.listdir(daily_dir), reverse=True)[:days]
    parts = []
    for fname in files:
        full = os.path.join(daily_dir, fname)
        if os.path.isfile(full):
            with open(full, "r", encoding="utf-8") as fp:
                parts.append(fp.read())
    return "\n\n---\n\n".join(parts)


def save_daily_summary(summary: str, date_str: Optional[str] = None) -> Optional[str]:
    """保存每日总结到 memory/daily/YYYY-MM-DD.md"""
    with _write_lock:
        _ensure_dir()
        d = date_str or _today_str()
        path = os.path.join(MEMORY_DIR, DAILY_DIR, f"{d}.md")
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(f"# Memory - {d}\n\n")
                f.write(summary)
                f.write("\n")
            return path
        except Exception as e:
            print(f"[memory] save_daily error: {e}", flush=True)
            return None


def append_to_profile(content: str) -> Optional[str]:
    """追加内容到用户画像 profile.md"""
    with _write_lock:
        _ensure_dir()
        p = os.path.join(MEMORY_DIR, PROFILE_FILE)
        try:
            with open(p, "a", encoding="utf-8") as f:
                f.write(content + "\n")
            return p
        except Exception as e:
            print(f"[memory] append_profile error: {e}", flush=True)
            return None


def get_memory_context(days: int = 3, max_chars: int = 3000) -> str:
    """汇总用户画像 + 最近 N 天总结，给 AI 当 RAG 上下文"""
    parts = []
    profile = get_profile()
    if profile and profile != "(No user profile yet)":
        parts.append("## User Profile\n" + profile[:1500])

    daily = get_recent_daily(days)
    if daily:
        parts.append("## Recent History\n" + daily)

    text = "\n\n".join(parts)
    return text[:max_chars] if text else ""


def summarize_day(date_str: str, chat_msgs: List[Dict[str, Any]] = None, brief_text: str = "") -> Optional[str]:
    """用 AI 总结当天记忆（用户画像 + 关注点）"""
    try:
        from services import ai_service_v2 as ai
    except Exception:
        try:
            from services import ai_service as ai
        except Exception:
            return None

    parts = []
    if brief_text:
        parts.append("## Today's AI Market Brief\n" + brief_text[:1500])
    if chat_msgs:
        chat_text = "\n".join(["[" + m.get("ts", "") + "] " + m.get("role", "") + ": " +
                               m.get("content", "") for m in chat_msgs[-30:]])
        parts.append("## Today's Chat\n" + chat_text[:2000])

    if not parts:
        return None

    full_input = "\n\n".join(parts)
    prompt = (
        "You are a memory summarizer. Based on the user's today activities (market brief + chat with AI), "
        "produce a concise memory summary in Markdown that captures:\n"
        "1. User's investment interests and focus areas (especially HK/LLM stocks)\n"
        "2. Specific stocks or companies mentioned\n"
        "3. User's investment style (conservative/aggressive/speculative)\n"
        "4. Any recurring topics or preferences\n"
        "5. Brief market context for the day\n\n"
        "Keep it under 500 Chinese characters, be factual and specific.\n\n"
        "Today's data:\n" + full_input
    )

    def _do_call(client):
        return client.messages.create(
            model=config.ANTHROPIC_MODEL,
            max_tokens=2000,
            system="You are a concise memory summarizer. Output in Chinese.",
            messages=[{"role": "user", "content": [{"type": "text", "text": prompt}]}],
        )
    try:
        message, _ = ai._call_with_fallback(_do_call)
        out = ""
        for block in message.content:
            if block.type == "text":
                out += block.text
        return out.strip() or None
    except Exception as e:
        print(f"[memory] summarize error: {e}", flush=True)
        return None
