"""Memory service - user profile & daily summary RAG for prompts
文件夹 E:\Trading\memory\，每日总结 + 用户画像

设计（2026-06-10 修订）：
- profile.md 是**精炼的长期画像**，≤ 300 行 / 8KB / 3000 tokens
- daily/YYYY-MM-DD.md 是**每日小观察**，≤ 30 行
- profile 由 consolidator 手动触发"覆盖式"重写，**不再追加**
- get_memory_context 硬性截断：profile ≤ 6000 字符，daily ≤ 2000 字符
"""
import os
import json
import time
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
from threading import Lock

import config

_write_lock = Lock()

MEMORY_DIR = "memory"
PROFILE_FILE = "profile.md"  # 总的画像文件（精炼版，≤ 300 行）
DAILY_DIR = "daily"           # 每日总结（≤ 30 行）

# === 硬性上限（防止 profile 再次膨胀）===
PROFILE_MAX_CHARS = 8000       # 约 8KB
PROFILE_MAX_LINES = 300
PROFILE_MAX_TOKENS = 3000      # 粗估：1 中文字符 ≈ 1.5 token
DAILY_MAX_CHARS_PER_FILE = 1500
DAILY_INJECT_DAYS = 1          # 进 RAG 的最近 N 天


def _ensure_dir():
    os.makedirs(MEMORY_DIR, exist_ok=True)
    os.makedirs(os.path.join(MEMORY_DIR, DAILY_DIR), exist_ok=True)


def _today_str():
    return datetime.now().strftime("%Y-%m-%d")


def _rough_token_count(text: str) -> int:
    """粗估 token 数：英文按 4 字符/token，中文按 1.5 字符/token"""
    if not text:
        return 0
    chinese = sum(1 for c in text if '一' <= c <= '鿿')
    other = len(text) - chinese
    return int(chinese / 1.5 + other / 4)


def get_profile() -> str:
    """读取用户画像（精炼版）"""
    _ensure_dir()
    p = os.path.join(MEMORY_DIR, PROFILE_FILE)
    if not os.path.isfile(p):
        return "(No user profile yet)"
    with open(p, "r", encoding="utf-8") as f:
        return f.read()


def get_profile_stats() -> Dict[str, Any]:
    """profile 健康检查：返回 行数/字符数/估算 tokens/是否超限"""
    text = get_profile()
    if text == "(No user profile yet)":
        return {"exists": False, "lines": 0, "chars": 0, "tokens": 0, "over_limit": False}
    p = os.path.join(MEMORY_DIR, PROFILE_FILE)
    line_count = 0
    if os.path.isfile(p):
        with open(p, "rb") as f:
            line_count = sum(1 for _ in f)
    chars = len(text)
    tokens = _rough_token_count(text)
    return {
        "exists": True,
        "lines": line_count,
        "chars": chars,
        "tokens": tokens,
        "over_limit": (line_count > PROFILE_MAX_LINES) or (chars > PROFILE_MAX_CHARS) or (tokens > PROFILE_MAX_TOKENS),
        "limits": {"max_lines": PROFILE_MAX_LINES, "max_chars": PROFILE_MAX_CHARS, "max_tokens": PROFILE_MAX_TOKENS},
    }


def get_recent_daily(days: int = DAILY_INJECT_DAYS) -> str:
    """读取最近 N 天的每日总结（每天 30 行内）"""
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
                content = fp.read()
                # 单文件硬截断
                if len(content) > DAILY_MAX_CHARS_PER_FILE:
                    content = content[:DAILY_MAX_CHARS_PER_FILE] + "\n\n[... 截断 ...]"
                parts.append(content)
    return "\n\n---\n\n".join(parts)


def save_daily_summary(summary: str, date_str: Optional[str] = None) -> Optional[str]:
    """保存每日总结到 memory/daily/YYYY-MM-DD.md（覆盖式，30 行内）"""
    with _write_lock:
        _ensure_dir()
        d = date_str or _today_str()
        path = os.path.join(MEMORY_DIR, DAILY_DIR, f"{d}.md")
        try:
            # 截断过长的 summary
            if summary and len(summary) > DAILY_MAX_CHARS_PER_FILE:
                summary = summary[:DAILY_MAX_CHARS_PER_FILE] + "\n\n[... 截断 ...]"
            with open(path, "w", encoding="utf-8") as f:
                f.write(f"# Memory - {d}\n\n")
                f.write(summary or "")
                f.write("\n")
            return path
        except Exception as e:
            print(f"[memory] save_daily error: {e}", flush=True)
            return None


def write_profile(content: str) -> Optional[str]:
    """覆盖式写入用户画像（consolidator 专用）

    警告：直接覆盖，不再追加。请确保 content 已经是合并/压缩后的精炼版本。
    自动截断到 PROFILE_MAX_CHARS 之内。
    """
    with _write_lock:
        _ensure_dir()
        p = os.path.join(MEMORY_DIR, PROFILE_FILE)
        try:
            if content and len(content) > PROFILE_MAX_CHARS:
                print(f"[memory] WARNING: profile content {len(content)} chars exceeds {PROFILE_MAX_CHARS}, truncating", flush=True)
                content = content[:PROFILE_MAX_CHARS] + "\n\n[... 截断到硬上限 ...]"
            with open(p, "w", encoding="utf-8") as f:
                f.write(content or "")
                f.write("\n")
            return p
        except Exception as e:
            print(f"[memory] write_profile error: {e}", flush=True)
            return None


# === 已废弃：保留以防旧代码误调，但打印警告 ===
def append_to_profile(content: str) -> Optional[str]:
    """[已废弃] 不再支持追加。请使用 consolidator 重写 profile。

    此函数仍存在以保持向后兼容，但已改为 no-op + 警告。
    """
    print(f"[memory] WARNING: append_to_profile() 已废弃，不再追加内容。"
          f"请改用 services.memory_consolidator.consolidate() 覆盖式重写 profile.md。", flush=True)
    return None


def get_memory_context(days: int = DAILY_INJECT_DAYS, max_chars: int = 3000) -> str:
    """汇总用户画像 + 最近 N 天总结，给 AI 当 RAG 上下文

    硬性保护：
    - profile 部分最多 6000 字符
    - daily 部分最多 2000 字符
    - 总输出不超过 max_chars
    """
    parts = []
    profile = get_profile()
    if profile and profile != "(No user profile yet)":
        # profile 单独硬截断
        profile_trimmed = profile[:6000]
        if len(profile) > 6000:
            profile_trimmed += "\n\n[... profile 已截断到 6000 字符 ...]"
        parts.append("## User Profile\n" + profile_trimmed)

    daily = get_recent_daily(days)
    if daily:
        # daily 单独硬截断
        daily_trimmed = daily[:2000]
        if len(daily) > 2000:
            daily_trimmed += "\n\n[... daily 已截断到 2000 字符 ...]"
        parts.append("## Recent Daily Memory (最近 1 天)\n" + daily_trimmed)

    text = "\n\n".join(parts)
    if len(text) > max_chars:
        text = text[:max_chars] + "\n\n[... 截断到总上限 ...]"
    return text


def summarize_day(date_str: str, chat_msgs: List[Dict[str, Any]] = None, brief_text: str = "") -> Optional[str]:
    """用 AI 总结当天记忆（写入 daily/，不写 profile）"""
    try:
        from services import ai_service_v2 as ai
    except Exception:
        try:
            from services import ai_service as ai
        except Exception:
            return None

    parts = []
    if brief_text:
        parts.append("## Today's AI Market Brief\n" + brief_text[:1000])
    if chat_msgs:
        chat_text = "\n".join(["[" + m.get("ts", "") + "] " + m.get("role", "") + ": " +
                               m.get("content", "") for m in chat_msgs[-20:]])
        parts.append("## Today's Chat\n" + chat_text[:1500])

    if not parts:
        return None

    full_input = "\n\n".join(parts)
    prompt = (
        "You are a memory summarizer. Based on the user's today activities (market brief + chat with AI), "
        "produce a concise daily memory summary in Markdown. Keep it under 300 Chinese characters, "
        "be factual and specific. Capture: 1) 新增的持仓/操作/关注点 2) 当日市场风格要点 3) 用户的情绪/态度变化。\n\n"
        "Today's data:\n" + full_input
    )

    def _do_call(client):
        return client.messages.create(
            model=config.ANTHROPIC_MODEL,
            max_tokens=1500,
            system="You are a concise daily memory summarizer. Output in Chinese, under 300 characters.",
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
