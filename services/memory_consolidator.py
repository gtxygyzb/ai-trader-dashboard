"""Memory consolidator - 把 daily/ 一周内容 + 旧 profile 合并压缩，重写 profile.md

设计目标：
- 用户点击 "🧹 整理 memory" 按钮时触发
- 读 daily/ 最近 7 天 + 当前 profile.md → 调 AI → 输出新的精炼 profile
- 把处理过的 daily/ 移到 archive/ 备份
- 强制 profile.md ≤ 8000 字符 / 300 行 / 3000 tokens
"""
import os
import shutil
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Tuple

import config
from services import memory_service


CONSOLIDATOR_DIR = "archive"
WEEK_DAYS = 7
MAX_INPUT_CHARS = 18000   # 喂给 AI 的总上下文上限（profile + 7天 daily）


def _ensure_dirs():
    os.makedirs(memory_service.MEMORY_DIR, exist_ok=True)
    os.makedirs(os.path.join(memory_service.MEMORY_DIR, memory_service.DAILY_DIR), exist_ok=True)
    os.makedirs(os.path.join(memory_service.MEMORY_DIR, CONSOLIDATOR_DIR), exist_ok=True)


def _list_daily_files(days: int = WEEK_DAYS) -> List[str]:
    """列出最近 N 天的 daily 文件（按日期倒序）"""
    daily_dir = os.path.join(memory_service.MEMORY_DIR, memory_service.DAILY_DIR)
    if not os.path.isdir(daily_dir):
        return []
    all_files = [f for f in os.listdir(daily_dir) if f.endswith(".md")]
    all_files.sort(reverse=True)
    return all_files[:days]


def _archive_daily_files(files: List[str]) -> int:
    """把处理过的 daily 文件移到 archive/YYYY-MM-DD/"""
    _ensure_dirs()
    archive_root = os.path.join(memory_service.MEMORY_DIR, CONSOLIDATOR_DIR)
    moved = 0
    for fname in files:
        src = os.path.join(memory_service.MEMORY_DIR, memory_service.DAILY_DIR, fname)
        if not os.path.isfile(src):
            continue
        # 提取日期：YYYY-MM-DD.md
        date_str = fname.replace(".md", "")
        dst_dir = os.path.join(archive_root, date_str)
        os.makedirs(dst_dir, exist_ok=True)
        dst = os.path.join(dst_dir, "daily.md")
        try:
            shutil.move(src, dst)
            moved += 1
        except Exception as e:
            print(f"[consolidator] archive {fname} error: {e}", flush=True)
    return moved


def consolidate(force: bool = False) -> Dict[str, Any]:
    """手动触发的 memory 整理流程

    步骤：
    1. 读 profile.md（旧的精炼画像）
    2. 读 daily/ 最近 7 天（每日小观察）
    3. 拼成 prompt，调 AI 输出新的精炼 profile（≤ 6000 字符）
    4. 写到 profile.md（覆盖）
    5. 把处理过的 daily 移到 archive/

    Returns: dict { ok, new_chars, new_lines, new_tokens, archived_count, message }
    """
    _ensure_dirs()

    old_profile = memory_service.get_profile()
    if old_profile == "(No user profile yet)":
        old_profile = ""

    daily_files = _list_daily_files(WEEK_DAYS)
    daily_blobs = []
    for fname in daily_files:
        full = os.path.join(memory_service.MEMORY_DIR, memory_service.DAILY_DIR, fname)
        try:
            with open(full, "r", encoding="utf-8") as f:
                blob = f.read()
                if len(blob) > memory_service.DAILY_MAX_CHARS_PER_FILE:
                    blob = blob[:memory_service.DAILY_MAX_CHARS_PER_FILE] + "\n[... 截断 ...]"
                daily_blobs.append(f"### File: {fname}\n{blob}")
        except Exception as e:
            print(f"[consolidator] read {fname} error: {e}", flush=True)

    if not daily_blobs and not old_profile:
        return {
            "ok": False,
            "message": "没有可整理的内容（profile 为空，daily/ 也没文件）",
            "new_chars": 0, "new_lines": 0, "new_tokens": 0,
            "archived_count": 0,
        }

    if not daily_blobs and not force:
        # 没新内容，但也不强制
        stats = memory_service.get_profile_stats()
        return {
            "ok": True,
            "message": "daily/ 为空，跳过整合。profile 未变。",
            **stats,
            "archived_count": 0,
        }

    # 拼接 prompt
    daily_text = "\n\n---\n\n".join(daily_blobs)
    # 总输入截断
    if len(old_profile) + len(daily_text) > MAX_INPUT_CHARS:
        budget = MAX_INPUT_CHARS
        if len(old_profile) > budget // 2:
            old_profile_trim = old_profile[: budget // 2] + "\n[... 截断 ...]"
        else:
            old_profile_trim = old_profile
        remaining = budget - len(old_profile_trim)
        daily_text = daily_text[:remaining] + "\n[... 截断 ...]"
    else:
        old_profile_trim = old_profile

    prompt = f"""你是用户的"个人投资画像整理员"。我会给你：
1. **旧 profile.md**（用户当前的精炼画像）
2. **最近 {len(daily_blobs)} 天的 daily 记录**（用户近期的观察/操作/持仓变化/情绪）

请你把这两份内容**合并、压缩、去重**，输出一份**新的精炼 profile.md**。

# 硬性要求
- **总长度 ≤ 6000 中文字符**（含 markdown 标记）
- 结构必须包含：基本情况 / 实际持仓表 / 投资目标 / 关注方向 / 投资风格 / 沟通偏好 / 给后续对话的提示 / 元信息
- **持仓表绝对不能丢任何数据**——所有股票代码、股数、买入价、买入日必须保留
- **关注方向只保留主线 + 次线**（4-7 项），合并重复项
- 用户的"操作记录"和"市场观点"走 daily/ 和 history/，**不进 profile**
- 用中文输出

# 旧 profile.md
{old_profile_trim}

# 最近 {len(daily_blobs)} 天 daily 记录
{daily_text}

# 输出格式（严格遵守）
直接输出新的 profile.md 完整内容，**不要**加任何解释性文字、```markdown``` 围栏、"好的以下是..."等开场白。
"""

    # 调 AI
    try:
        from services import ai_service_v2 as ai
    except Exception:
        try:
            from services import ai_service as ai
        except Exception:
            return {"ok": False, "message": "AI 服务不可用", "new_chars": 0, "new_lines": 0, "new_tokens": 0, "archived_count": 0}

    def _do_call(client):
        return client.messages.create(
            model=config.ANTHROPIC_MODEL,
            max_tokens=4000,
            system="你是个人投资画像整理员。输出严格 ≤ 6000 中文字符的精炼 Markdown profile。",
            messages=[{"role": "user", "content": [{"type": "text", "text": prompt}]}],
        )

    try:
        message, _ = ai._call_with_fallback(_do_call)
        new_profile = ""
        for block in message.content:
            if block.type == "text":
                new_profile += block.text
        new_profile = new_profile.strip()
    except Exception as e:
        print(f"[consolidator] AI call error: {e}", flush=True)
        return {
            "ok": False,
            "message": f"AI 调用失败: {e}",
            "new_chars": 0, "new_lines": 0, "new_tokens": 0,
            "archived_count": 0,
        }

    if not new_profile:
        return {
            "ok": False,
            "message": "AI 返回空内容",
            "new_chars": 0, "new_lines": 0, "new_tokens": 0,
            "archived_count": 0,
        }

    # 写 profile（write_profile 内部会硬截断）
    memory_service.write_profile(new_profile)

    # 归档 daily
    archived = _archive_daily_files(daily_files)

    # 重新读 stats
    stats = memory_service.get_profile_stats()

    return {
        "ok": True,
        "message": f"已整合 {len(daily_blobs)} 天 daily，归档 {archived} 个文件，profile 重新生成。",
        "new_chars": stats["chars"],
        "new_lines": stats["lines"],
        "new_tokens": stats["tokens"],
        "over_limit": stats["over_limit"],
        "archived_count": archived,
        "consolidated_days": len(daily_blobs),
    }
