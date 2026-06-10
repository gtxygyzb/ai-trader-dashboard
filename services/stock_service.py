"""股票数据服务 - 使用东方财富/新浪公开接口"""
import requests
import json
import time
import random
from typing import List, Dict, Any, Optional
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://quote.eastmoney.com/",
    "Origin": "https://quote.eastmoney.com",
    "Accept": "*/*",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Connection": "keep-alive",
}

# 东方财富域名故障转移列表（按优先级），push2.eastmoney.com 在本机被屏蔽，因此优先使用 delay
EM_HOSTS = [
    "push2delay.eastmoney.com",
    "82.push2.eastmoney.com",
    "44.push2.eastmoney.com",
    "push2.eastmoney.com",
]


def _build_session() -> requests.Session:
    """带重试的全局 session（连接复用 + 自动重试）"""
    s = requests.Session()
    retry = Retry(
        total=2,
        backoff_factor=0.6,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=20)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    s.headers.update(HEADERS)
    return s


_session = _build_session()


def _safe_get(url: str, params: dict = None, timeout: int = 10, max_tries: int = 2) -> Optional[requests.Response]:
    """带退避的安全 GET"""
    last_err = None
    for attempt in range(max_tries):
        try:
            r = _session.get(url, params=params, timeout=timeout)
            if r.status_code == 200:
                return r
            last_err = f"HTTP {r.status_code}"
        except Exception as e:
            last_err = str(e)
        time.sleep(0.4 + attempt * 0.6 + random.random() * 0.2)
    print(f"[stock_service] _safe_get failed url={url[:80]}... err={last_err}")
    return None


def _em_get(path: str, params: dict, timeout: int = 10) -> Optional[dict]:
    """对所有东财域名做故障转移；返回解析后的 JSON 或 None"""
    last_err = None
    for host in EM_HOSTS:
        url = f"https://{host}{path}"
        try:
            r = _session.get(url, params=params, timeout=timeout)
            if r.status_code == 200 and r.text and r.text[0] in "{[":
                try:
                    return r.json()
                except Exception as e:
                    last_err = f"json-parse: {e}"
                    continue
            last_err = f"HTTP {r.status_code}"
        except Exception as e:
            last_err = str(e)
            # 该 host 不行就立即切下一个，不退避
            continue
    print(f"[stock_service] _em_get all hosts failed path={path} err={last_err}")
    return None


def _fetch_eastmoney(params: Dict[str, Any]) -> List[Dict[str, Any]]:
    """通过东方财富 clist 接口获取股票列表数据（带域名故障转移）"""
    data = _em_get("/api/qt/clist/get", params, timeout=10)
    if not data or "data" not in data or not data["data"]:
        return []
    return data["data"].get("diff", []) or []


def _fetch_sina_forex() -> List[Dict[str, Any]]:
    """从新浪财经拉主要货币对实时行情（USD/CNH、USD/JPY、USD/KRW）

    新浪字段顺序：时间,今开,昨收,最新价,数量,买价,卖价,最高,最低,名称,涨跌额,涨跌幅,...
    返回 [{"name": "USD/CNH", "price": 6.778, "change_pct": -0.04, "change": -0.003, "category": "forex"}, ...]
    """
    pairs = [
        ("fx_susdcnh", "USD/CNH"),
        ("fx_susdjpy", "USD/JPY"),
        ("fx_susdkrw", "USD/KRW"),
    ]
    url = "https://hq.sinajs.cn/list=" + ",".join(p[0] for p in pairs)
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://finance.sina.com.cn/",
    }
    out = []
    try:
        r = requests.get(url, headers=headers, timeout=8)
        if r.status_code != 200:
            return out
        for line in r.text.split("\n"):
            if "=" not in line or '"' not in line:
                continue
            # 解析 var hq_str_xxx="...";
            try:
                key = line.split('var ')[1].split('=')[0]
                payload = line.split('"')[1]
                if not payload:
                    continue
                # 找对应的中文名
                name_cn = ""
                for code, name in pairs:
                    if code in key:
                        name_cn = name
                        break
                if not name_cn:
                    continue
                fields = payload.split(",")
                # 字段：0=时间,1=今开,2=昨收,3=最新价,8=最高,9=名称,10=涨跌额,11=涨跌幅
                price = float(fields[3]) if fields[3] else 0
                change = float(fields[10]) if len(fields) > 10 and fields[10] else 0
                change_pct = float(fields[11]) if len(fields) > 11 and fields[11] else 0
                out.append({
                    "name": name_cn,
                    "price": round(price, 4),
                    "change": round(change, 4),
                    "change_pct": round(change_pct, 3),
                    "category": "forex",
                })
            except (IndexError, ValueError, AttributeError) as e:
                print(f"[forex] parse line error: {e}")
                continue
    except Exception as e:
        print(f"[forex] sina fetch error: {e}")
    return out


def _format_stock(item: Dict[str, Any], market: str = "A") -> Dict[str, Any]:
    """东方财富原始字段格式化"""
    def _v(key, default=None, divide=1):
        val = item.get(key)
        if val in (None, "-", "", "—"):
            return default
        try:
            return float(val) / divide if divide != 1 else val
        except (ValueError, TypeError):
            return default

    code = item.get("f12", "")
    name = item.get("f14", "")
    price = _v("f2", 0)
    change_pct = _v("f3", 0)  # 涨跌幅 %
    change = _v("f4", 0)      # 涨跌额
    volume = _v("f5", 0)
    turnover = _v("f6", 0)
    market_cap = _v("f20", 0)  # 总市值
    pe = _v("f9", 0)

    return {
        "code": code,
        "name": name,
        "market": market,
        "price": round(price, 3) if price else 0,
        "change_pct": round(change_pct, 2) if change_pct else 0,
        "change": round(change, 3) if change else 0,
        "volume": volume,
        "turnover": turnover,
        "market_cap": market_cap,
        "pe": pe,
    }


# ============ A股 ============

def get_a_top_gainers(limit: int = 10) -> List[Dict[str, Any]]:
    """A 股涨幅榜"""
    params = {
        "pn": 1, "pz": limit, "po": 1, "np": 1,
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": 2, "invt": 2, "fid": "f3",
        "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048",
        "fields": "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f13,f14,f15,f16,f17,f18,f20,f21,f23,f24,f25,f22",
    }
    data = _fetch_eastmoney(params)
    return [_format_stock(item, "A") for item in data]


def get_a_top_losers(limit: int = 10) -> List[Dict[str, Any]]:
    """A 股跌幅榜"""
    params = {
        "pn": 1, "pz": limit, "po": 0, "np": 1,
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": 2, "invt": 2, "fid": "f3",
        "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048",
        "fields": "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f13,f14,f15,f16,f17,f18,f20,f21,f23,f24,f25,f22",
    }
    data = _fetch_eastmoney(params)
    return [_format_stock(item, "A") for item in data]


# ============ 港股 ============

def get_hk_top_gainers(limit: int = 10) -> List[Dict[str, Any]]:
    """港股主板涨幅榜"""
    params = {
        "pn": 1, "pz": limit, "po": 1, "np": 1,
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": 2, "invt": 2, "fid": "f3",
        "fs": "m:128+t:3,m:128+t:4,m:128+t:1,m:128+t:2",
        "fields": "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f13,f14,f15,f16,f17,f18,f20,f21,f23,f24,f25,f22",
    }
    data = _fetch_eastmoney(params)
    return [_format_stock(item, "HK") for item in data]


def get_hk_top_losers(limit: int = 10) -> List[Dict[str, Any]]:
    """港股主板跌幅榜"""
    params = {
        "pn": 1, "pz": limit, "po": 0, "np": 1,
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": 2, "invt": 2, "fid": "f3",
        "fs": "m:128+t:3,m:128+t:4,m:128+t:1,m:128+t:2",
        "fields": "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f13,f14,f15,f16,f17,f18,f20,f21,f23,f24,f25,f22",
    }
    data = _fetch_eastmoney(params)
    return [_format_stock(item, "HK") for item in data]


# ============ 板块 ============

def get_top_sectors(limit: int = 10) -> List[Dict[str, Any]]:
    """A 股行业板块涨幅榜"""
    params = {
        "pn": 1, "pz": limit, "po": 1, "np": 1,
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": 2, "invt": 2, "fid": "f3",
        "fs": "m:90+t:2+f:!50",
        "fields": "f2,f3,f4,f8,f12,f14,f15,f16,f17,f18,f20,f21,f24,f25,f22,f33,f11,f62,f128,f136,f115,f152,f124,f107,f104,f105,f140,f141,f207,f208,f209,f222",
    }
    data = _fetch_eastmoney(params)
    return [{
        "name": it.get("f14", ""),
        "code": it.get("f12", ""),
        "change_pct": round(float(it.get("f3", 0)), 2),
        "price": round(float(it.get("f2", 0)), 2) if it.get("f2") else 0,
        "leader": it.get("f128", ""),  # 领涨股
        "leader_change_pct": round(float(it.get("f136", 0)), 2) if it.get("f136") not in (None, "-", "") else 0,
        "amount": float(it.get("f20", 0)) if it.get("f20") not in (None, "-", "") else 0,
    } for it in data]


def get_top_concepts(limit: int = 10) -> List[Dict[str, Any]]:
    """概念板块涨幅榜（过滤掉涨停/异动/季报/热股等非概念分类）

    东方财富的"概念板块"接口（m:90+t:3）实际混入了多类非真实概念：
    - 事件/异动类：涨停、连板、首板、昨日、异动、历史新高、近期新低/新高、破发
    - 财务/业绩类：三季报、年报、中报、一季报、扭亏、预增、预减、分红、送转
    - 人气/榜单类：热股、人气、东方财富、关注度
    - 股本/股东类：高质押、次新、回购、增持、减持、摘帽、ST
    这些不是真正的概念板块，统统剔除。
    """
    params = {
        "pn": 1, "pz": 200, "po": 1, "np": 1,  # 一次性拉 200 条，剔完再截断到 limit
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": 2, "invt": 2, "fid": "f3",
        "fs": "m:90+t:3+f:!50",
        "fields": "f2,f3,f4,f8,f12,f14,f15,f16,f17,f18,f20,f21,f24,f25,f22,f33,f11,f62,f128,f136,f115,f152,f124,f107,f104,f105,f140,f141,f207,f208,f209,f222",
    }
    data = _fetch_eastmoney(params)
    excluded_keywords = (
        # 事件/异动类
        "昨日", "涨停", "异动", "首板", "连板", "历史新高", "曾涨停",
        "近期新高", "近期新低", "新低", "破发",
        # 财务/业绩类
        "三季报", "年报", "中报", "一季报", "扭亏", "预增", "预减",
        "分红", "送转", "摘帽", "ST", "业绩",
        # 人气/榜单类
        "热股", "人气", "东方财富", "关注度", "热门",
        # 股本/股东类
        "高质押", "次新", "回购", "增持", "减持",
    )
    items = []
    for it in data:
        name = (it.get("f14") or "").strip()
        if not name:
            continue
        if any(k in name for k in excluded_keywords):
            continue
        items.append({
            "name": name,
            "code": it.get("f12", ""),
            "change_pct": round(float(it.get("f3", 0)), 2),
            "leader": it.get("f128", ""),
            "leader_change_pct": round(float(it.get("f136", 0)), 2) if it.get("f136") not in (None, "-", "") else 0,
        })
        if len(items) >= limit:
            break
    return items


# ============ 大盘指数 ============

def get_market_indices() -> List[Dict[str, Any]]:
    """A 股、港股、美股、亚太、外汇核心指数实时行情

    加入日经 225、美元指数、韩国综指用于：
    - 日经/韩国综指 = 亚太科技股情绪 → 传导 A 股科创 50 / 创业板 / 恒生科技
    - 美元指数 = 资金回流美国压力 → A 股 / 港股流动性
    - 韩国综指也是全球半导体周期的领先指标
    """
    secids = [
        # A 股核心（精简到 2 个：主板代表 + 成长代表）
        ("1.000001", "上证指数"),
        ("0.399006", "创业板指"),
        # 港股核心
        ("100.HSI", "恒生指数"),
        ("100.HSTECH", "恒生科技"),
        ("100.HSCEI", "恒生国企"),
        # 亚太（影响 A 股科技股情绪）
        ("100.N225", "日经225"),
        ("100.KS11", "韩国综指"),
        # 美股
        ("100.NDX", "纳斯达克100"),
        ("100.DJIA", "道琼斯"),
        ("100.SPX", "标普500"),
        ("100.IXIC", "纳斯达克综指"),
        # 外汇（影响新兴市场资金面）
        ("100.UDI", "美元指数"),
    ]
    secids_str = ",".join([s[0] for s in secids])
    name_map = dict(secids)
    params = {
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": 2, "invt": 2,
        "fields": "f1,f2,f3,f4,f12,f13,f14",
        "secids": secids_str,
    }
    d = _em_get("/api/qt/ulist.np/get", params, timeout=10)
    if not d:
        return []
    results = []
    try:
        items = (d.get("data") or {}).get("diff", []) or []
        for it in items:
            code = it.get("f12", "")
            market_id = it.get("f13", "")
            secid = f"{market_id}.{code}"
            display_name = name_map.get(secid) or it.get("f14") or code
            results.append({
                "name": display_name,
                "code": code,
                "price": round(float(it.get("f2", 0)), 2) if it.get("f2") not in (None, "-", "") else 0,
                "change_pct": round(float(it.get("f3", 0)), 2) if it.get("f3") not in (None, "-", "") else 0,
                "change": round(float(it.get("f4", 0)), 2) if it.get("f4") not in (None, "-", "") else 0,
            })
        name_order = {name: i for i, (_, name) in enumerate(secids)}
        results.sort(key=lambda x: name_order.get(x["name"], 999))
    except Exception as e:
        print(f"[stock_service] get_market_indices error: {e}")

    # 追加货币对（新浪接口，失败也不影响主指数）
    try:
        forex_list = _fetch_sina_forex()
        for fx in forex_list:
            results.append({
                "name": fx["name"],
                "code": fx["name"],
                "price": fx["price"],
                "change_pct": fx["change_pct"],
                "change": fx["change"],
                "category": "forex",
            })
    except Exception as e:
        print(f"[stock_service] forex append error: {e}")

    return results


def get_stocks_batch(codes_with_market: List[tuple], name_map: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
    """批量获取多只股票详情（一次 ulist.np/get 请求，比逐只快 10 倍）
    codes_with_market: [(code, market), ...]  market: 'A'|'HK'|'US'
    """
    secids = []
    for code, market in codes_with_market:
        code = str(code).strip()
        if market == "HK" or (code.isdigit() and len(code) == 5):
            secids.append(f"116.{code.zfill(5)}")
        elif market == "A" or (code.isdigit() and len(code) == 6):
            if code.startswith(("60", "68", "9")):
                secids.append(f"1.{code}")
            elif code.startswith(("00", "30", "20")):
                secids.append(f"0.{code}")
            else:
                secids.append(f"1.{code}")
        else:
            secids.append(f"105.{code}")  # 默认美股

    if not secids:
        return []

    url = "https://push2.eastmoney.com/api/qt/ulist.np/get"
    fields = ("f12,f14,f2,f3,f4,f5,f6,f9,f43,f44,f45,f46,f47,f48,f60,f116,f162,f167,f170,f171,f184,f185,f186")
    params = {
        "ut": "fa5fd1943c7b386f172d6893dbfba10b",
        "fltt": 2, "invt": 2,
        "fields": fields,
        "secids": ",".join(secids),
    }
    d = _em_get("/api/qt/ulist.np/get", params, timeout=10)
    if not d:
        return []
    items = (d.get("data") or {}).get("diff", []) or []
    out = []
    for it in items:
        code = it.get("f12", "")
        out.append({
            "code": code,
            "name": it.get("f14", ""),
            "price": _fmt_num(it.get("f2")),
            "open": _fmt_num(it.get("f46")),
            "high": _fmt_num(it.get("f44")),
            "low": _fmt_num(it.get("f45")),
            "pre_close": _fmt_num(it.get("f60")),
            "change": _fmt_num(it.get("f170")),
            "change_pct": _fmt_num(it.get("f3") or it.get("f170")),
            "volume": _fmt_num(it.get("f47")),
            "turnover": _fmt_num(it.get("f48")),
            "pe": it.get("f162"),
            "pb": it.get("f167"),
            "amplitude": _fmt_num(it.get("f171")),
            "market_cap": _fmt_num(it.get("f116")),
            "high_52w": _fmt_num(it.get("f184")),
            "low_52w": _fmt_num(it.get("f185")),
        })
    if name_map:
        for item in out:
            item["display_name"] = name_map.get(item["code"], item.get("name", ""))
    # 按 secids 顺序排
    order = {s.split(".")[-1]: i for i, s in enumerate(secids)}
    out.sort(key=lambda x: order.get(x.get("code", ""), 999))
    return out


def _fmt_num(v):
    if v in (None, "-", "", "—"):
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return v


# 保留旧的单只接口（给其他场景用）
def get_stock_detail(code: str, market_hint: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """根据股票代码获取详情（自动识别 A/HK/US）"""
    code_clean = str(code).strip()
    candidates = []
    if market_hint == "HK" or (code_clean.isdigit() and len(code_clean) == 5):
        candidates.append(f"116.{code_clean.zfill(5)}")
    if market_hint == "A" or (code_clean.isdigit() and len(code_clean) == 6):
        if code_clean.startswith(("60", "68", "9")):
            candidates.append(f"1.{code_clean}")
        elif code_clean.startswith(("00", "30", "20")):
            candidates.append(f"0.{code_clean}")
        else:
            candidates.append(f"1.{code_clean}")
            candidates.append(f"0.{code_clean}")
    if market_hint == "US" or (not code_clean.isdigit()):
        candidates.append(f"105.{code_clean}")
        candidates.append(f"106.{code_clean}")
        candidates.append(f"107.{code_clean}")
    # 尝试候选 secid
    candidates = []
    code_clean = code.strip().upper()
    if market_hint == "HK" or (code_clean.isdigit() and len(code_clean) == 5):
        candidates.append(f"116.{code_clean.zfill(5)}")
    if market_hint == "A" or (code_clean.isdigit() and len(code_clean) == 6):
        # 上交所 1.6xxxxx/9xxxxx, 深交所 0.0xxxxx/3xxxxx
        if code_clean.startswith(("60", "68", "9")):
            candidates.append(f"1.{code_clean}")
        elif code_clean.startswith(("00", "30", "20")):
            candidates.append(f"0.{code_clean}")
        else:
            candidates.append(f"1.{code_clean}")
            candidates.append(f"0.{code_clean}")
    if market_hint == "US" or (not code_clean.isdigit()):
        candidates.append(f"105.{code_clean}")  # NASDAQ
        candidates.append(f"106.{code_clean}")  # NYSE
        candidates.append(f"107.{code_clean}")  # AMEX

    fields = ("f43,f44,f45,f46,f47,f48,f50,f51,f52,f55,f57,f58,f59,f60,f62,f71,"
              "f84,f85,f86,f92,f107,f111,f116,f117,f152,f161,f162,f164,f167,f168,f169,f170,f171,f191,f192")
    for secid in candidates:
        params = {
            "ut": "fa5fd1943c7b386f172d6893dbfba10b",
            "fltt": 2, "invt": 2,
            "fields": fields,
            "secid": secid,
        }
        d = _em_get("/api/qt/stock/get", params, timeout=8)
        if not d:
            continue
        try:
            data = (d or {}).get("data") or {}
            if data and data.get("f58"):
                return {
                    "code": code_clean,
                    "secid": secid,
                    "name": data.get("f58"),
                    "price": data.get("f43"),
                    "change_pct": data.get("f170"),
                    "change": data.get("f169"),
                    "open": data.get("f46"),
                    "high": data.get("f44"),
                    "low": data.get("f45"),
                    "pre_close": data.get("f60"),
                    "volume": data.get("f47"),
                    "turnover": data.get("f48"),
                    "market_cap": data.get("f116"),
                    "pe": data.get("f162"),
                    "pb": data.get("f167"),
                    "amplitude": data.get("f171"),
                    "high_52w": data.get("f174"),
                    "low_52w": data.get("f175"),
                }
        except Exception as e:
            print(f"[stock_service] get_stock_detail({secid}) parse error: {e}")
            continue
    return None


# ============ 关注股票（批量） ============

def get_focus_stocks(stocks_map: Dict[str, str], market: str) -> List[Dict[str, Any]]:
    """批量获取关注股票实时行情"""
    results = []
    for code, name in stocks_map.items():
        detail = get_stock_detail(code, market_hint=market)
        if detail:
            detail["display_name"] = name
            results.append(detail)
        time.sleep(0.05)  # 避免请求过密
    return results


if __name__ == "__main__":
    # 简单自测
    print("== 大盘指数 ==")
    for x in get_market_indices()[:6]:
        print(x)
    print("\n== A股涨幅榜 ==")
    for x in get_a_top_gainers(5):
        print(x)
    print("\n== 港股涨幅榜 ==")
    for x in get_hk_top_gainers(5):
        print(x)
    print("\n== 行业板块 ==")
    for x in get_top_sectors(5):
        print(x)
