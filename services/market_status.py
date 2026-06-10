"""市场状态判断：A 股 / 港股 交易时段 + 休市判断"""
from datetime import datetime, time, timedelta
from typing import Dict, Any

# 2026 年 A 股节假日（按官方放假安排手动维护，可后续接 sse/szse）
# 简单起见用通用规则 + 几个硬编码节假日
A_HOLIDAYS_2026 = {
    "2026-01-01",  # 元旦
    "2026-02-09", "2026-02-10", "2026-02-11", "2026-02-12", "2026-02-13",  # 春节
    "2026-04-06",  # 清明
    "2026-05-01", "2026-05-04", "2026-05-05",  # 劳动节
    "2026-06-19",  # 端午
    "2026-09-25", "2026-09-26", "2026-09-27",  # 中秋+国庆
    "2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04", "2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08",  # 国庆
}

# 港股节假日（简版）
HK_HOLIDAYS_2026 = {
    "2026-01-01",
    "2026-02-16", "2026-02-17", "2026-02-18", "2026-02-19", "2026-02-20",  # 春节港股
    "2026-04-03", "2026-04-06",  # 复活节+清明
    "2026-05-01",
    "2026-05-25",  # 佛诞
    "2026-07-01",
    "2026-10-01",
    "2026-10-19",  # 重阳
    "2026-12-25", "2026-12-26",
}

# A 股时段
A_PRE_OPEN  = (time(9, 15),  time(9, 30))    # 集合竞价
A_MORNING   = (time(9, 30),  time(11, 30))
A_NOON      = (time(11, 30), time(13, 0))
A_AFTERNOON = (time(13, 0),  time(15, 0))

# 港股时段
HK_MORNING   = (time(9, 30), time(12, 0))
HK_AFTERNOON = (time(13, 0), time(16, 0))

# 美股（夏令时约 3-11 月）— 转换为北京时段
US_PRE   = (time(16, 0),  time(21, 30))
US_REG   = (time(21, 30), time(4, 0))   # 次日


def _is_weekend(d: datetime) -> bool:
    return d.weekday() >= 5  # 周六周日


def _fmt_clock(t: time) -> str:
    return t.strftime("%H:%M")


def _in_range(now_t: time, rng) -> bool:
    s, e = rng
    if s <= e:
        return s <= now_t < e
    # 跨天（如美股 21:30-04:00）
    return now_t >= s or now_t < e


def a_share_status(now: datetime = None) -> Dict[str, Any]:
    """A 股市场状态"""
    now = now or datetime.now()
    today = now.strftime("%Y-%m-%d")
    weekday = now.weekday()

    if today in A_HOLIDAYS_2026 or weekday >= 5:
        return {
            "status": "closed",
            "label": "休市",
            "reason": "节假日" if today in A_HOLIDAYS_2026 else "周末",
            "next_open": None,  # 可后续算
        }

    now_t = now.time()
    if _in_range(now_t, A_MORNING):
        return {"status": "open", "label": "盘中", "session": "上午",
                "until": _fmt_clock(A_MORNING[1])}
    if _in_range(now_t, A_AFTERNOON):
        return {"status": "open", "label": "盘中", "session": "下午",
                "until": _fmt_clock(A_AFTERNOON[1])}
    if _in_range(now_t, A_NOON):
        return {"status": "break", "label": "午间休市",
                "next_session": "下午 13:00"}
    if _in_range(now_t, A_PRE_OPEN):
        return {"status": "pre", "label": "集合竞价",
                "until": _fmt_clock(A_PRE_OPEN[1])}
    # 盘后
    if now_t >= time(15, 0):
        return {"status": "closed", "label": "已收盘",
                "next_open": "下一个交易日 09:30"}
    if now_t < time(9, 15):
        return {"status": "closed", "label": "盘前",
                "next_open": "今日 09:15"}
    return {"status": "closed", "label": "盘后"}


def hk_status(now: datetime = None) -> Dict[str, Any]:
    """港股状态"""
    now = now or datetime.now()
    today = now.strftime("%Y-%m-%d")
    weekday = now.weekday()

    if today in HK_HOLIDAYS_2026 or weekday >= 5:
        return {
            "status": "closed", "label": "港股休市",
            "reason": "节假日" if today in HK_HOLIDAYS_2026 else "周末",
        }

    now_t = now.time()
    if _in_range(now_t, HK_MORNING):
        return {"status": "open", "label": "港股盘中", "session": "上午",
                "until": _fmt_clock(HK_MORNING[1])}
    if _in_range(now_t, HK_AFTERNOON):
        return {"status": "open", "label": "港股盘中", "session": "下午",
                "until": _fmt_clock(HK_AFTERNOON[1])}
    if time(12, 0) <= now_t < time(13, 0):
        return {"status": "break", "label": "港股午间休市",
                "next_session": "13:00"}
    if now_t < time(9, 30):
        return {"status": "pre", "label": "港股盘前", "next_open": "今日 09:30"}
    if now_t >= time(16, 0):
        return {"status": "closed", "label": "港股已收盘"}
    return {"status": "closed", "label": "港股盘后"}


def us_status(now: datetime = None) -> Dict[str, Any]:
    """美股（北京时间）状态"""
    now = now or datetime.now()
    now_t = now.time()
    if _in_range(now_t, US_REG):
        return {"status": "open", "label": "美股盘中", "until": "次日 04:00"}
    if _in_range(now_t, US_PRE):
        return {"status": "pre", "label": "美股盘前"}
    if now_t >= time(4, 0) and now_t < time(9, 0):
        return {"status": "closed", "label": "美股盘后-隔夜"}
    return {"status": "closed", "label": "美股盘后"}


def overall_status() -> Dict[str, Any]:
    """总览：所有市场状态"""
    return {
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "a_share": a_share_status(),
        "hk": hk_status(),
        "us": us_status(),
    }


def news_freshness(news_time_str: str, now: datetime = None) -> str:
    """根据新闻时间字符串（YYYY-MM-DD HH:MM 或 HH:MM）计算新鲜度"""
    if not news_time_str:
        return "未知"
    now = now or datetime.now()
    # 解析
    try:
        if len(news_time_str) == 5 and ":" in news_time_str:  # HH:MM
            today = now.strftime("%Y-%m-%d")
            t = datetime.strptime(f"{today} {news_time_str}", "%Y-%m-%d %H:%M")
        else:
            t = datetime.strptime(news_time_str, "%Y-%m-%d %H:%M")
    except Exception:
        return news_time_str
    delta = (now - t).total_seconds() / 60  # 分钟
    if delta < 0:
        delta += 24 * 60
    if delta < 60:
        return f"{int(delta)}分钟前"
    if delta < 24 * 60:
        return f"{int(delta // 60)}小时前"
    return f"{int(delta // (24 * 60))}天前"


if __name__ == "__main__":
    print("=== A 股 ===", a_share_status())
    print("=== 港股 ===", hk_status())
    print("=== 美股 ===", us_status())
    print("=== 新闻 ===", news_freshness("2026-06-06 14:30"))
    print("=== 新闻 ===", news_freshness("14:30"))
    print("=== 新闻 ===", news_freshness("2026-06-05 09:00"))
