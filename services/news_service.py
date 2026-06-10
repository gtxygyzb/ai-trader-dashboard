"""新闻爬虫服务 - AI/科技/财经新闻聚合"""
import requests
import re
import time
import feedparser
from typing import List, Dict, Any
from datetime import datetime
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def _clean_text(s: str) -> str:
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


# ============ 东方财富 7x24 财经快讯 ============

def get_eastmoney_flash(limit: int = 20) -> List[Dict[str, Any]]:
    """东方财富 7x24 财经快讯（fastNewsList 接口）"""
    url = "https://np-listapi.eastmoney.com/comm/web/getFastNewsList"
    params = {
        "client": "web",
        "biz": "web_724",
        "fastColumn": "102",
        "sortEnd": "",
        "pageSize": str(limit),
        "req_trace": str(int(time.time() * 1000)),
    }
    try:
        r = requests.get(url, params=params,
                         headers={**HEADERS, "Referer": "https://kuaixun.eastmoney.com/"},
                         timeout=10)
        data = r.json()
        items = ((data.get("data") or {}).get("fastNewsList") or [])
        results = []
        for it in items[:limit]:
            results.append({
                "source": "东方财富7x24",
                "title": _clean_text(it.get("title", "")),
                "summary": _clean_text(it.get("summary", "")),
                "url": f"https://kuaixun.eastmoney.com/{it.get('code', '')}.html",
                "time": it.get("showTime", ""),
            })
        return [r_ for r_ in results if r_["title"]]
    except Exception as e:
        print(f"[news_service] eastmoney_flash error: {e}")
        return []


# ============ 财联社快讯（页面动态加载，留作占位/未来扩展） ============

def get_cls_flash(limit: int = 20) -> List[Dict[str, Any]]:
    """财联社电报 — 当前接口需要签名，留作占位返回空列表
    后续可通过 selenium/playwright 渲染获取。"""
    return []


# ============ 36氪 AI 频道 ============

def get_36kr_ai(limit: int = 15) -> List[Dict[str, Any]]:
    """36氪 AI 资讯"""
    url = "https://36kr.com/information/AI"
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        r.encoding = "utf-8"
        soup = BeautifulSoup(r.text, "lxml")
        # 提取嵌入的初始 state
        scripts = soup.find_all("script")
        results = []
        # 优先解析卡片
        for card in soup.select("a.article-item-title, a.title")[:limit]:
            title = _clean_text(card.get_text())
            href = card.get("href") or ""
            if href and not href.startswith("http"):
                href = "https://36kr.com" + href
            if title and href:
                results.append({
                    "source": "36氪AI",
                    "title": title,
                    "summary": "",
                    "url": href,
                    "time": "",
                })
        # 备用：直接抓所有文章链接
        if not results:
            for a in soup.select('a[href*="/p/"]')[:limit * 2]:
                title = _clean_text(a.get_text())
                href = a.get("href", "")
                if not title or len(title) < 8:
                    continue
                if href and not href.startswith("http"):
                    href = "https://36kr.com" + href
                results.append({
                    "source": "36氪",
                    "title": title,
                    "summary": "",
                    "url": href,
                    "time": "",
                })
                if len(results) >= limit:
                    break
        # 去重
        seen = set()
        uniq = []
        for r_ in results:
            if r_["title"] in seen:
                continue
            seen.add(r_["title"])
            uniq.append(r_)
        return uniq[:limit]
    except Exception as e:
        print(f"[news_service] 36kr_ai error: {e}")
        return []


# ============ 新浪财经滚动 ============

def get_sina_finance(limit: int = 15) -> List[Dict[str, Any]]:
    """新浪财经滚动新闻 - 公司类（lid=2509 公司滚动）"""
    url = "https://feed.mix.sina.com.cn/api/roll/get"
    params = {
        "pageid": "153", "lid": "2509", "k": "", "num": str(limit), "page": "1",
        "callback": "feedCardJsonpCallback",
        "_": str(int(time.time() * 1000)),
    }
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=10)
        text = r.text
        m = re.search(r"\((\{.*\})\)", text, re.S)
        raw = m.group(1) if m else text
        import json as _json
        data = _json.loads(raw)
        items = (data.get("result") or {}).get("data", []) or []
        results = []
        for it in items[:limit]:
            ctime = int(it.get("ctime", 0))
            time_str = datetime.fromtimestamp(ctime).strftime("%Y-%m-%d %H:%M") if ctime else ""
            results.append({
                "source": "新浪财经",
                "title": _clean_text(it.get("title", "")),
                "summary": _clean_text(it.get("intro", "")),
                "url": it.get("url", ""),
                "time": time_str,
            })
        return results
    except Exception as e:
        print(f"[news_service] sina_finance error: {e}")
        return []


def get_sina_tech(limit: int = 15) -> List[Dict[str, Any]]:
    """新浪科技 - lid=2515 互联网/科技"""
    url = "https://feed.mix.sina.com.cn/api/roll/get"
    params = {
        "pageid": "153", "lid": "2515", "k": "", "num": str(limit), "page": "1",
        "callback": "feedCardJsonpCallback",
        "_": str(int(time.time() * 1000)),
    }
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=10)
        text = r.text
        m = re.search(r"\((\{.*\})\)", text, re.S)
        raw = m.group(1) if m else text
        import json as _json
        data = _json.loads(raw)
        items = (data.get("result") or {}).get("data", []) or []
        results = []
        for it in items[:limit]:
            ctime = int(it.get("ctime", 0))
            time_str = datetime.fromtimestamp(ctime).strftime("%Y-%m-%d %H:%M") if ctime else ""
            results.append({
                "source": "新浪科技",
                "title": _clean_text(it.get("title", "")),
                "summary": _clean_text(it.get("intro", "")),
                "url": it.get("url", ""),
                "time": time_str,
            })
        return results
    except Exception as e:
        print(f"[news_service] sina_tech error: {e}")
        return []


# ============ 华尔街见闻 ============

def get_wallstreetcn(limit: int = 15) -> List[Dict[str, Any]]:
    """华尔街见闻全球资讯快讯"""
    url = "https://api-one-wscn.awtmt.com/apiv1/content/lives"
    params = {
        "channel": "global-channel",
        "client": "pc",
        "limit": str(limit),
        "accept": "live,A,B",
    }
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=10)
        data = r.json()
        items = ((data.get("data") or {}).get("items") or [])
        results = []
        for it in items[:limit]:
            ctime = it.get("display_time", 0)
            time_str = datetime.fromtimestamp(ctime).strftime("%Y-%m-%d %H:%M") if ctime else ""
            results.append({
                "source": "华尔街见闻",
                "title": _clean_text(it.get("title") or it.get("content_text") or "")[:80],
                "summary": _clean_text(it.get("content_text", ""))[:300],
                "url": it.get("uri") or "",
                "time": time_str,
            })
        return [r_ for r_ in results if r_["title"]]
    except Exception as e:
        print(f"[news_service] wallstreetcn error: {e}")
        return []


# 哪些来源是"国内"，哪些是"国际"
# 注：华尔街见闻虽然是国际名字，但内容以国内财经为主，归国内
DOMESTIC_SOURCES = {"东方财富7x24", "新浪财经", "新浪科技", "36氪AI", "财联社"}
INTERNATIONAL_SOURCES = {"新浪全球财经", "新浪港股", "华尔街见闻·全球"}

# 仅当 source 在 INTERNATIONAL_SOURCES 时走国际，
# 其他（含"华尔街见闻"）默认国内；split 函数再按 URL/关键词二次过滤

def filter_ai_news(news_list: List[Dict[str, Any]], keywords: List[str]) -> List[Dict[str, Any]]:
    """筛选含 AI 关键词的新闻"""
    if not keywords:
        return news_list
    kw_lower = [k.lower() for k in keywords]
    result = []
    for n in news_list:
        text = (n.get("title", "") + " " + n.get("summary", "")).lower()
        if any(k in text for k in kw_lower):
            result.append(n)
    return result


# ============ 综合获取 ============

def get_all_news(limit_per_source: int = 15) -> Dict[str, List[Dict[str, Any]]]:
    """获取所有来源新闻（国内 + 国际/港美韩股）"""
    return {
        # 国内
        "eastmoney":   get_eastmoney_flash(limit_per_source),
        "kr36":        get_36kr_ai(limit_per_source),
        "sina_finance": get_sina_finance(limit_per_source),
        "sina_tech":   get_sina_tech(limit_per_source),
        "wallstreetcn": get_wallstreetcn(limit_per_source),
        # 国际/港美韩股
        "sina_global": get_sina_global(limit_per_source),
        "wsj_intl":    get_wallstreetcn_intl(limit_per_source),
    }


def get_ai_focused_news(ai_keywords: List[str], limit: int = 30) -> List[Dict[str, Any]]:
    """聚合 AI 相关新闻"""
    all_news = []
    for src_news in get_all_news(20).values():
        all_news.extend(src_news)
    ai_news = filter_ai_news(all_news, ai_keywords)
    # 不足时补充 36氪 AI 频道全部
    if len(ai_news) < limit:
        kr_ai = get_36kr_ai(15)
        seen = {n["title"] for n in ai_news}
        for n in kr_ai:
            if n["title"] not in seen:
                ai_news.append(n)
                seen.add(n["title"])
    return ai_news[:limit]


def split_news_domestic_intl(news_list: List[Dict[str, Any]], each_limit: int = 2) -> Dict[str, List[Dict[str, Any]]]:
    """将新闻按"国内/国际"分类 + 智能去重（相似标题只保留一条）"""
    import re

    def normalize_title(t: str) -> str:
        """提取关键词指纹，用于去重"""
        if not t:
            return ""
        t = re.sub(r"[【】\[\]（）()（）。，,。；;:：、\s\-—_]+", "", t)
        return t[:20]  # 取前 20 字作为指纹

    seen_fingerprints = set()
    cn_list, intl_list = [], []

    # 国际/港美韩股关键词（标题/摘要/URL 任一含 → 算国际）
    intl_keywords = [
        "美股", "纳指", "纳斯达克", "标普", "道指", "道琼斯",
        "韩股", "韩国", "kospi", "韩元",
        "港股", "恒生", "hang seng",
        "欧股", "日股", "日经", "nikkei",
        "nasdaq", "s&p", "dow", "nikkei",
        "spacex", "nvidia", "英伟达",
        "美联储", "fed", "鲍威尔",
        "比特币", "btc", "eth",
    ]

    for n in news_list:
        fp = normalize_title(n.get("title", ""))
        if not fp or fp in seen_fingerprints:
            continue
        seen_fingerprints.add(fp)

        source = n.get("source", "")
        text = (n.get("title", "") + " " + n.get("summary", "") + " " + n.get("url", "")).lower()

        # 新浪全球/港股直接归国际
        if source in {"新浪全球财经", "新浪港股", "华尔街见闻·全球"}:
            target = intl_list
        # 内容含港美韩股关键词 → 国际
        elif any(k.lower() in text for k in intl_keywords):
            target = intl_list
        # 其他全部国内
        else:
            target = cn_list

        if len(target) < each_limit:
            target.append(n)

        if len(cn_list) >= each_limit and len(intl_list) >= each_limit:
            break

    return {"cn": cn_list, "intl": intl_list}


if __name__ == "__main__":
    print("=== 财联社 ===")
    for n in get_cls_flash(5):
        print("-", n["title"][:60], "|", n["time"])
    print("\n=== 东方财富 7x24 ===")
    for n in get_eastmoney_flash(5):
        print("-", n["title"][:60], "|", n["time"])
    print("\n=== 新浪财经 ===")
    for n in get_sina_finance(5):
        print("-", n["title"][:60], "|", n["time"])
    print("\n=== 36氪AI ===")
    for n in get_36kr_ai(5):
        print("-", n["title"][:60])


# ============ 国际/港股/美股/韩股 财经新闻（新浪全球财经） ============

def get_sina_global(limit: int = 15) -> List[Dict[str, Any]]:
    """新浪全球财经快讯（美股/欧股/港股/韩股等）"""
    # lid=2513 全球财经, 2509 港股
    sources = [
        ("新浪全球财经", "https://feed.mix.sina.com.cn/api/roll/get", 2513, "世界"),
        ("新浪港股",     "https://feed.mix.sina.com.cn/api/roll/get", 2509, "HK"),
    ]
    results = []
    for source_name, url, lid, tag in sources:
        try:
            params = {
                "pageid": "153", "lid": str(lid), "k": "", "num": str(limit),
                "page": "1", "callback": "feedCardJsonpCallback",
                "_": str(int(time.time() * 1000)),
            }
            r = requests.get(url, params=params, headers=HEADERS, timeout=8)
            text = r.text
            m = re.search(r"\((\{.*\})\)", text, re.S)
            raw = m.group(1) if m else text
            import json as _json
            data = _json.loads(raw)
            for it in (data.get("result") or {}).get("data", []) or []:
                ctime = int(it.get("ctime", 0))
                time_str = datetime.fromtimestamp(ctime).strftime("%Y-%m-%d %H:%M") if ctime else ""
                results.append({
                    "source": source_name,
                    "title": _clean_text(it.get("title", "")),
                    "summary": _clean_text(it.get("intro", "")),
                    "url": it.get("url", ""),
                    "time": time_str,
                })
        except Exception as e:
            print(f"[news_service] sina {source_name} error: {e}")
    return results


# ============ 华尔街见闻（已有，但归为国际） ============

def get_wallstreetcn_intl(limit: int = 10) -> List[Dict[str, Any]]:
    """华尔街见闻 - 全球市场快讯（美股/欧股/商品等）"""
    url = "https://api-one-wscn.awtmt.com/apiv1/content/lives"
    params = {
        "channel": "global-channel",
        "client": "pc",
        "limit": str(limit),
        "accept": "live,A,B",
    }
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=8)
        data = r.json()
        items = ((data.get("data") or {}).get("items") or [])
        results = []
        for it in items:
            ctime = it.get("display_time", 0)
            time_str = datetime.fromtimestamp(ctime).strftime("%Y-%m-%d %H:%M") if ctime else ""
            content = _clean_text(it.get("content_text", ""))[:300]
            # 看是否含美股/韩股/港股关键词
            text_lower = (it.get("title", "") + " " + content).lower()
            if not any(k in text_lower for k in ["美股", "纳指", "标普", "道指", "韩股", "韩国",
                                                  "港股", "恒生", "hang seng", "kospi",
                                                  "nasdaq", "s&p", "dow"]):
                continue
            results.append({
                "source": "华尔街见闻·全球",
                "title": _clean_text(it.get("title") or it.get("content_text", "")[:80])[:80],
                "summary": content,
                "url": it.get("uri") or "",
                "time": time_str,
            })
        return results[:limit]
    except Exception as e:
        print(f"[news_service] wallstreetcn_intl error: {e}")
        return []
