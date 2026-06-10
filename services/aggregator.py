"""数据聚合层 - 统一调用爬虫并缓存"""
import time
import threading
from typing import Dict, Any
import config
from services import stock_service, news_service, history_service
try:
    from services import ai_service_v2 as ai_service
except Exception:
    from services import ai_service

_cache: Dict[str, Dict[str, Any]] = {}
_lock = threading.Lock()


def _get_cached(key: str, ttl: int):
    """读缓存，过期返回 None"""
    with _lock:
        item = _cache.get(key)
        if item and (time.time() - item["ts"] < ttl):
            return item["value"]
    return None


def _set_cache(key: str, value):
    with _lock:
        _cache[key] = {"ts": time.time(), "value": value}


def clear_cache(key: str = None):
    with _lock:
        if key:
            _cache.pop(key, None)
        else:
            _cache.clear()


# ============ 行情聚合 ============

def get_market_snapshot(force_refresh: bool = False) -> Dict[str, Any]:
    """获取所有行情数据快照（并行抓取）"""
    key = "market_snapshot"
    if not force_refresh:
        cached = _get_cached(key, config.CACHE_TTL_STOCKS)
        if cached:
            return cached

    from concurrent.futures import ThreadPoolExecutor, as_completed

    tasks = {
        "indices":   stock_service.get_market_indices,
        "a_gainers": lambda: stock_service.get_a_top_gainers(10),
        "a_losers":  lambda: stock_service.get_a_top_losers(10),
        "hk_gainers": lambda: stock_service.get_hk_top_gainers(10),
        "hk_losers":  lambda: stock_service.get_hk_top_losers(10),
        "sectors":   stock_service.get_top_sectors,
        "concepts":  stock_service.get_top_concepts,
    }

    snapshot = {"ts": time.strftime("%Y-%m-%d %H:%M:%S")}
    with ThreadPoolExecutor(max_workers=6) as ex:
        future_map = {ex.submit(fn): name for name, fn in tasks.items()}
        for fut in as_completed(future_map, timeout=25):
            name = future_map[fut]
            try:
                snapshot[name] = fut.result(timeout=12)
            except Exception as e:
                print(f"[aggregator] {name} error: {e}")
                snapshot[name] = []
    # 字段兜底
    for k in tasks.keys():
        snapshot.setdefault(k, [])

    _set_cache(key, snapshot)
    # 历史归档（异步，不阻塞）
    threading.Thread(target=history_service.save_market_snapshot, args=(snapshot,), daemon=True).start()
    return snapshot


# ============ 新闻聚合 ============

def get_news_snapshot(force_refresh: bool = False) -> Dict[str, Any]:
    """获取所有新闻快照（并行抓取）"""
    key = "news_snapshot"
    if not force_refresh:
        cached = _get_cached(key, config.CACHE_TTL_NEWS)
        if cached:
            return cached

    from concurrent.futures import ThreadPoolExecutor, as_completed

    sources = {
        # 国内（快、必抓）
        "eastmoney":  lambda: news_service.get_eastmoney_flash(10),
        "kr36":       lambda: news_service.get_36kr_ai(10),
        "sina_finance": lambda: news_service.get_sina_finance(10),
        "sina_tech":  lambda: news_service.get_sina_tech(10),
        "wallstreetcn": lambda: news_service.get_wallstreetcn(10),
        # 国际/港美韩股（新浪全球财经、华尔街见闻全球）
        "sina_global": lambda: news_service.get_sina_global(10),
        "wsj_intl":    lambda: news_service.get_wallstreetcn_intl(10),
    }
    by_source = {}
    with ThreadPoolExecutor(max_workers=7) as ex:
        future_map = {ex.submit(fn): name for name, fn in sources.items()}
        for fut in as_completed(future_map, timeout=25):
            name = future_map[fut]
            try:
                by_source[name] = fut.result(timeout=10)
            except Exception as e:
                print(f"[aggregator] news {name} error: {e}")
                by_source[name] = []
    for k in sources.keys():
        by_source.setdefault(k, [])

    merged = []
    for src_news in by_source.values():
        merged.extend(src_news)
    merged.sort(key=lambda n: n.get("time", ""), reverse=True)

    ai_news = news_service.filter_ai_news(merged, config.AI_KEYWORDS)
    # 智能拆分：国内 2 条 + 国际 2 条，去重
    split_news = news_service.split_news_domestic_intl(ai_news, each_limit=2)
    # 其他财经新闻（去除已纳入 AI 的）
    ai_titles = {n["title"] for n in ai_news}
    other_news = [n for n in merged if n["title"] not in ai_titles]

    snapshot = {
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "by_source": by_source,
        "ai_news_cn": split_news["cn"],
        "ai_news_intl": split_news["intl"],
        "ai_news": ai_news[:20],          # 保留全量给 RAG/简报用
        "finance_news": other_news[:20],
        "all": merged[:40],
    }
    _set_cache(key, snapshot)
    threading.Thread(target=history_service.save_news_snapshot, args=(snapshot,), daemon=True).start()
    return snapshot


# ============ AI 简报 ============

def get_brief(force_refresh: bool = False) -> Dict[str, Any]:
    """获取 AI 综合简报（带缓存）"""
    key = "brief"
    if not force_refresh:
        cached = _get_cached(key, config.CACHE_TTL_BRIEF)
        if cached:
            return cached

    market = get_market_snapshot(force_refresh)
    news = get_news_snapshot(force_refresh)
    brief_data = {**market, **news}
    brief_text = ai_service.generate_brief(brief_data)
    result = {
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "brief": brief_text,
        "market_summary": {
            "indices_count": len(market.get("indices", [])),
            "a_gainers_count": len(market.get("a_gainers", [])),
            "hk_gainers_count": len(market.get("hk_gainers", [])),
            "ai_news_count": len(news.get("ai_news", [])),
        },
    }
    _set_cache(key, result)
    # 归档
    history_service.save_brief(result)
    return result


# ============ 聊天 RAG 上下文 ============

def get_chat_context() -> str:
    """为聊天构建 RAG 上下文（用最新缓存数据）"""
    market = get_market_snapshot()
    news = get_news_snapshot()
    data = {**market, **news}
    return ai_service.build_rag_context(data)
