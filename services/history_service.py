"""历史归档服务 - 每天只保留 1 个最新文件（按类）
设计：避免频繁刷新导致文件狂涨
"""
import os
import json
import time
import hashlib
from datetime import datetime
from typing import Dict, Any, List, Optional
from threading import Lock

import config

_write_lock = Lock()

# 每类每天最多保留多少个历史快照（避免文件暴增）
# 简报：每 30 分钟一次，一天 48 份足够（开盘 4h * 2 + 收盘评估 1-2 份）= 10 份
# 行情：每 5 分钟一次，开盘 4h * 12 = 48 份 + 1 个最新
# 新闻：每 15 分钟一次，开盘 4h * 4 = 16 份
MAX_FILES_PER_TYPE_PER_DAY = {
    "brief": 12,     # 简报每天最多 12 份
    "market": 48,    # 行情每天最多 48 份
    "news": 16,      # 新闻每天最多 16 份
    "chat": 0,       # 聊天只增不删（jsonl append）
}


def _today_dir() -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    path = os.path.join(config.HISTORY_DIR, today)
    os.makedirs(path, exist_ok=True)
    return path


def _hash_content(content: str) -> str:
    return hashlib.md5(content.encode("utf-8", errors="ignore")).hexdigest()[:8]


def _cleanup_old_files(day_dir: str, file_type: str, keep: int) -> None:
    """超过 keep 数量的旧文件按时间从早到晚删除"""
    if keep <= 0:
        return
    files = []
    for f in os.listdir(day_dir):
        if f.startswith(file_type + "_") and (f.endswith(".json") or f.endswith(".md") or f.endswith(".jsonl")):
            full = os.path.join(day_dir, f)
            files.append((os.path.getmtime(full), full))
    files.sort()  # 从早到晚
    while len(files) > keep:
        _, oldest = files.pop(0)
        try:
            os.remove(oldest)
        except OSError:
            pass


def save_brief(brief: Dict[str, Any]) -> Optional[str]:
    """保存简报 - 每天只保留 1 份 latest_brief.md（覆盖式）
    除非 force_new=True 才会创建带时间戳的历史版本
    """
    with _write_lock:
        day_dir = _today_dir()
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        md_path = os.path.join(day_dir, "latest_brief.md")
        json_path = os.path.join(day_dir, "latest_brief.json")

        try:
            # 1. 始终覆盖 latest 文件（如果当天有变化）
            brief_with_ts = dict(brief)
            brief_with_ts["ts"] = ts  # 强制更新为最新时间
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(f"# AI 综合简报 - {ts}\n\n")
                f.write(brief.get("brief", ""))
                f.write("\n")
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(brief_with_ts, f, ensure_ascii=False, indent=2)
            return md_path
        except Exception as e:
            print(f"[history] save_brief error: {e}", flush=True)
            return None


def save_news_snapshot(news: Dict[str, Any]) -> Optional[str]:
    """保存新闻快照 - 同一天覆盖到 daily_news.json（去重后只保留增量）"""
    with _write_lock:
        day_dir = _today_dir()
        today_file = os.path.join(day_dir, "daily_news.json")

        # 读已有
        existing_titles = set()
        existing_list = []
        if os.path.isfile(today_file):
            try:
                with open(today_file, "r", encoding="utf-8") as f:
                    old = json.load(f)
                existing_list = old.get("all", [])
                existing_titles = {n.get("title") for n in existing_list}
            except Exception:
                pass

        # 合并新增
        new_all = news.get("all", [])
        added = 0
        for n in new_all:
            if n.get("title") not in existing_titles:
                existing_list.append(n)
                existing_titles.add(n.get("title"))
                added += 1

        merged_news = {
            "ts": news.get("ts"),
            "added_count": added,
            "total_count": len(existing_list),
            "ai_news_cn": news.get("ai_news_cn", []),
            "ai_news_intl": news.get("ai_news_intl", []),
            "all": existing_list,
        }

        # 写文件
        try:
            with open(today_file, "w", encoding="utf-8") as f:
                json.dump(merged_news, f, ensure_ascii=False, indent=2)
            return today_file
        except Exception as e:
            print(f"[history] save_news error: {e}", flush=True)
            return None


def save_market_snapshot(market: Dict[str, Any]) -> Optional[str]:
    """保存行情快照 - 同一天覆盖到 daily_market.json（只保留时间戳和指数）"""
    with _write_lock:
        day_dir = _today_dir()
        today_file = os.path.join(day_dir, "daily_market.json")

        existing_records = []
        if os.path.isfile(today_file):
            try:
                with open(today_file, "r", encoding="utf-8") as f:
                    old = json.load(f)
                existing_records = old.get("records", [])
            except Exception:
                pass

        # 简单去重：和最近一条对比，如果所有指数都一样就跳过
        snapshot = {
            "ts": market.get("ts"),
            "indices": market.get("indices", []),
            "sectors": market.get("sectors", [])[:5],
            "concepts": market.get("concepts", [])[:5],
        }
        if existing_records and _records_equal(existing_records[-1], snapshot):
            return today_file  # 没变化，不新增

        existing_records.append(snapshot)
        # 限制每天最多 N 条
        max_keep = MAX_FILES_PER_TYPE_PER_DAY["market"]
        if len(existing_records) > max_keep:
            existing_records = existing_records[-max_keep:]

        try:
            with open(today_file, "w", encoding="utf-8") as f:
                json.dump({"ts": market.get("ts"), "records": existing_records}, f, ensure_ascii=False, indent=2)
            return today_file
        except Exception as e:
            print(f"[history] save_market error: {e}", flush=True)
            return None


def _records_equal(a, b) -> bool:
    """两个市场快照是否相同（只看指数和板块涨跌）"""
    if not a or not b:
        return False
    a_idx = a.get("indices", [])
    b_idx = b.get("indices", [])
    if len(a_idx) != len(b_idx):
        return False
    for x, y in zip(a_idx, b_idx):
        if x.get("name") != y.get("name") or x.get("price") != y.get("price"):
            return False
    return True


def append_chat(role: str, content: str, extra: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """追加聊天到当天 chat.jsonl（只增不删）"""
    with _write_lock:
        day_dir = _today_dir()
        path = os.path.join(day_dir, "chat.jsonl")
        try:
            record = {
                "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "role": role,
                "content": content,
            }
            if extra:
                record["meta"] = extra
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
            return path
        except Exception as e:
            print(f"[history] append_chat error: {e}", flush=True)
            return None


def list_days() -> List[str]:
    """列出所有历史日期目录"""
    if not os.path.isdir(config.HISTORY_DIR):
        return []
    days = []
    for d in sorted(os.listdir(config.HISTORY_DIR), reverse=True):
        full = os.path.join(config.HISTORY_DIR, d)
        if os.path.isdir(full):
            days.append(d)
    return days


def list_day_files(day: str) -> List[Dict[str, Any]]:
    """列出某天所有归档文件 + 大小 + mtime"""
    day_dir = os.path.join(config.HISTORY_DIR, day)
    if not os.path.isdir(day_dir):
        return []
    files = []
    for f in sorted(os.listdir(day_dir)):
        full = os.path.join(day_dir, f)
        if not os.path.isfile(full):
            continue
        st = os.stat(full)
        files.append({
            "name": f,
            "size": st.st_size,
            "mtime": datetime.fromtimestamp(st.st_mtime).strftime("%H:%M:%S"),
        })
    return files


def read_file(day: str, filename: str) -> Optional[str]:
    """读取归档文件内容"""
    path = os.path.join(config.HISTORY_DIR, day, filename)
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def read_chat_log(day: str) -> List[Dict[str, Any]]:
    """读取当天聊天 jsonl 记录"""
    path = os.path.join(config.HISTORY_DIR, day, "chat.jsonl")
    if not os.path.isfile(path):
        return []
    items = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                items.append(json.loads(line))
            except Exception:
                continue
    return items


def get_recent_context(days: int = 7, max_chars: int = 4000) -> Dict[str, Any]:
    """汇总最近 N 天的历史归档，返回给 AI 做 RAG 上下文用

    返回：
    {
      "summary": "简要文字汇总（给用户看）",
      "briefs": [{day, ts, brief}, ...],          # 最近简报
      "indices_trend": [{day, indices}, ...],     # 指数走势
      "news_aggregated": [...],                   # 去重新闻
      "raw_text": "...",                          # 喂给 AI 的扁平文本
    }
    """
    from datetime import datetime, timedelta
    briefs = []
    indices_trend = []
    news_set = {}

    days_list = list_days()[:days]
    for day in days_list:
        day_dir = os.path.join(config.HISTORY_DIR, day)
        # 简报
        brief_json = os.path.join(day_dir, "latest_brief.json")
        if os.path.isfile(brief_json):
            try:
                with open(brief_json, "r", encoding="utf-8") as f:
                    d = json.load(f)
                briefs.append({"day": day, "ts": d.get("ts"), "brief": d.get("brief", "")[:500]})
            except Exception:
                pass
        # 行情
        market_json = os.path.join(day_dir, "daily_market.json")
        if os.path.isfile(market_json):
            try:
                with open(market_json, "r", encoding="utf-8") as f:
                    d = json.load(f)
                records = d.get("records", [])
                if records:
                    last = records[-1]
                    indices_trend.append({
                        "day": day,
                        "ts": last.get("ts"),
                        "indices": [(i["name"], i.get("change_pct", 0)) for i in last.get("indices", [])[:6]],
                    })
            except Exception:
                pass
        # 新闻
        news_json = os.path.join(day_dir, "daily_news.json")
        if os.path.isfile(news_json):
            try:
                with open(news_json, "r", encoding="utf-8") as f:
                    d = json.load(f)
                for n in d.get("all", []) or []:
                    title = n.get("title", "")
                    if title and title not in news_set:
                        news_set[title] = {"day": day, **n}
            except Exception:
                pass

    news_aggregated = sorted(news_set.values(), key=lambda x: x.get("time", ""), reverse=True)[:20]

    # 拼成扁平文本（喂给 AI）
    parts = []
    summary_parts = []
    if briefs:
        parts.append("## 最近简报")
        for b in briefs[:5]:
            parts.append(f"[{b['day']}] {b['brief']}")
        summary_parts.append(f"简报 {len(briefs)} 份")
    if indices_trend:
        parts.append("\n## 指数变化（按天）")
        for it in indices_trend:
            parts.append(f"[{it['day']}] " + ", ".join(f"{n}{'+' if p>=0 else ''}{p:.2f}%" for n, p in it["indices"]))
        summary_parts.append(f"指数 {len(indices_trend)} 天")
    if news_aggregated:
        parts.append("\n## 近期重要新闻")
        for n in news_aggregated[:10]:
            parts.append(f"[{n.get('day','')}] {n.get('title','')[:80]}")
        summary_parts.append(f"新闻 {len(news_aggregated)} 条")

    raw_text = "\n".join(parts)[:max_chars]
    summary = " | ".join(summary_parts) or "无历史"

    return {
        "summary": summary,
        "briefs": briefs,
        "indices_trend": indices_trend,
        "news_aggregated": news_aggregated,
        "raw_text": raw_text,
    }
