"""量化分析软件主入口 - Flask Web 服务"""
import os
import sys
import json
import time
import threading
from flask import Flask, render_template, jsonify, request, Response, stream_with_context
from flask_cors import CORS

import config
from services import stock_service, news_service, aggregator, history_service, market_status, memory_service
try:
    from services import ai_service_v2 as ai_service
    print("[startup] using ai_service_v2", flush=True)
except Exception as e:
    print(f"[startup] v2 import failed, fallback to v1: {e}", flush=True)
    from services import ai_service

app = Flask(__name__, static_folder="static", template_folder="templates")
CORS(app)


# ============ 页面 ============

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/health")
def health():
    return jsonify({"status": "ok", "ts": time.strftime("%Y-%m-%d %H:%M:%S")})


# ============ 行情 API ============

@app.route("/api/market")
def api_market():
    force = request.args.get("refresh") == "1"
    snapshot = aggregator.get_market_snapshot(force_refresh=force)
    snapshot["market_status"] = market_status.overall_status()
    return jsonify(snapshot)


@app.route("/api/indices")
def api_indices():
    return jsonify({
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "market_status": market_status.overall_status(),
        "indices": stock_service.get_market_indices(),
    })


@app.route("/api/market_status")
def api_market_status():
    """各市场交易状态"""
    return jsonify(market_status.overall_status())


@app.route("/api/a_gainers")
def api_a_gainers():
    limit = int(request.args.get("limit", 10))
    return jsonify(stock_service.get_a_top_gainers(limit))


@app.route("/api/a_losers")
def api_a_losers():
    limit = int(request.args.get("limit", 10))
    return jsonify(stock_service.get_a_top_losers(limit))


@app.route("/api/hk_gainers")
def api_hk_gainers():
    limit = int(request.args.get("limit", 10))
    return jsonify(stock_service.get_hk_top_gainers(limit))


@app.route("/api/hk_losers")
def api_hk_losers():
    limit = int(request.args.get("limit", 10))
    return jsonify(stock_service.get_hk_top_losers(limit))


@app.route("/api/sectors")
def api_sectors():
    return jsonify(stock_service.get_top_sectors(10))


@app.route("/api/concepts")
def api_concepts():
    return jsonify(stock_service.get_top_concepts(10))


@app.route("/api/stock/<code>")
def api_stock_detail(code):
    market_hint = request.args.get("market")
    detail = stock_service.get_stock_detail(code, market_hint=market_hint)
    return jsonify(detail or {})


# ============ 新闻 API ============

@app.route("/api/news")
def api_news():
    force = request.args.get("refresh") == "1"
    snapshot = aggregator.get_news_snapshot(force_refresh=force)
    return jsonify(snapshot)


@app.route("/api/news/ai")
def api_news_ai():
    snapshot = aggregator.get_news_snapshot()
    return jsonify(snapshot.get("ai_news", []))


# ============ AI 简报 ============

@app.route("/api/brief")
def api_brief():
    """AI brief API - background generation, with daily memory summary"""
    force = request.args.get("refresh") == "1"

    cached = aggregator._get_cached("brief", config.CACHE_TTL_BRIEF)
    if cached and not force:
        return jsonify(cached)

    import threading
    def _do_generate():
        # 1. Generate brief
        aggregator.get_brief(force_refresh=force)
        # 2. 读取当天 chat.jsonl + 简报，自动生成 memory summary 并写入 profile
        try:
            today = time.strftime("%Y-%m-%d")
            chat_msgs = history_service.read_chat_log(today)
            cached_brief = aggregator._get_cached("brief", config.CACHE_TTL_BRIEF) or {}
            brief_text = (cached_brief.get("brief", "") if isinstance(cached_brief, dict) else "")
            if chat_msgs or brief_text:
                summary = memory_service.summarize_day(today, chat_msgs=chat_msgs, brief_text=brief_text)
                if summary:
                    memory_service.save_daily_summary(summary, date_str=today)
                    memory_service.append_to_profile(f"\n## {today}\n{summary}\n")
                    print(f"[brief] memory saved for {today}", flush=True)
        except Exception as e:
            print(f"[brief] memory save error: {e}", flush=True)
        print("[brief] background generation done.", flush=True)
    threading.Thread(target=_do_generate, daemon=True).start()

    return jsonify({
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "brief": "⏳ AI 简报正在生成中，约需 30-60 秒……\n\n- 已开始抓取最新行情数据\n- 已开始聚合 5 源最新新闻\n- 已调用 AI 模型撰写简报\n\n请稍候片刻后点击「重新生成」或刷新本卡片即可查看。",
        "pending": True,
    })


@app.route("/api/deep_analysis")
def api_deep_analysis():
    """深度分析 - 综合今天 + 7 天内历史的 AI 分析报告
    把历史归档作为 RAG 上下文喂给 AI
    """
    import threading
    force = request.args.get("refresh") == "1"

    cache_key = "deep_analysis"
    if not force:
        cached = aggregator._get_cached(cache_key, 60 * 60)
        if cached:
            return jsonify(cached)

    def _do_generate():
        market = aggregator.get_market_snapshot(force_refresh=False)
        news = aggregator.get_news_snapshot(force_refresh=False)
        history = history_service.get_recent_context(days=7, max_chars=4000)
        data = {**market, **news, "history": history}
        try:
            from services import ai_service_v2 as ai_service
        except Exception:
            from services import ai_service
        text = ai_service.generate_deep_analysis(data)
        result = {
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "analysis": text,
            "history_used": history.get("summary", ""),
        }
        aggregator._set_cache(cache_key, result)
        history_service.save_brief({"ts": result["ts"], "brief": text})
        print("[deep_analysis] done", flush=True)

    threading.Thread(target=_do_generate, daemon=True).start()

    return jsonify({
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "analysis": "⏳ 正在生成深度分析（结合 7 天历史归档 + 实时行情）……\n\n首次约需 1-2 分钟，请稍候。",
        "pending": True,
    })


# ============ AI 股票分析 ============

@app.route("/api/analyze/<code>")
def api_analyze_stock(code):
    """个股 AI 分析 - 后台异步生成，避免阻塞"""
    import threading
    market_hint = request.args.get("market")
    force = request.args.get("refresh") == "1"

    # 用 cache key 区分股票 + 强制刷新
    cache_key = f"analyze:{code}:{market_hint or 'auto'}"
    ttl = 30 * 60  # 30 分钟缓存
    if not force:
        cached = aggregator._get_cached(cache_key, ttl)
        if cached:
            return jsonify(cached)

    # 启动后台生成
    def _do_analyze():
        try:
            detail = stock_service.get_stock_detail(code, market_hint=market_hint)
            if not detail:
                aggregator._set_cache(cache_key, {"error": "未找到该股票"})
                return
            analysis = ai_service.analyze_stock(detail)
            result = {"stock": detail, "analysis": analysis}
            aggregator._set_cache(cache_key, result)
            print(f"[analyze] {code} done", flush=True)
        except Exception as e:
            aggregator._set_cache(cache_key, {"error": f"分析失败: {e}"})
            print(f"[analyze] {code} error: {e}", flush=True)

    threading.Thread(target=_do_analyze, daemon=True).start()

    return jsonify({
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "pending": True,
        "message": f"⏳ 正在分析 {code}……AI 思考约需 10-30 秒，请稍候后点击重试或刷新弹窗查看。",
    })


@app.route("/api/analyze_status/<code>")
def api_analyze_status(code):
    """查询个股分析结果"""
    market_hint = request.args.get("market")
    cache_key = f"analyze:{code}:{market_hint or 'auto'}"
    cached = aggregator._get_cached(cache_key, 30 * 60)
    if cached:
        return jsonify(cached)
    return jsonify({"pending": True, "message": "分析中……"}), 202


# ============ AI 聊天 ============

@app.route("/api/chat", methods=["POST"])
def api_chat():
    payload = request.get_json(force=True, silent=True) or {}
    messages = payload.get("messages", [])
    use_rag = payload.get("use_rag", True)
    rag = aggregator.get_chat_context() if use_rag else ""
    # 注入 memory 上下文
    memory_ctx = memory_service.get_memory_context(days=3, max_chars=2500)
    if memory_ctx:
        rag = (memory_ctx + "\n\n" + rag) if rag else memory_ctx
    answer = ai_service.chat(messages, rag_context=rag)
    # 归档最近一轮对话
    if messages:
        last_user = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")
        if last_user:
            history_service.append_chat("user", last_user)
    if answer:
        history_service.append_chat("assistant", answer)
    return jsonify({"answer": answer, "ts": time.strftime("%H:%M:%S")})


@app.route("/api/chat/stream", methods=["POST"])
def api_chat_stream():
    payload = request.get_json(force=True, silent=True) or {}
    messages = payload.get("messages", [])
    use_rag = payload.get("use_rag", True)
    rag = aggregator.get_chat_context() if use_rag else ""
    # 注入 memory 上下文
    memory_ctx = memory_service.get_memory_context(days=3, max_chars=2500)
    if memory_ctx:
        rag = (memory_ctx + "\n\n" + rag) if rag else memory_ctx

    last_user = ""
    if messages:
        last_user = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")

    def gen():
        acc = ""
        if last_user:
            history_service.append_chat("user", last_user)
        try:
            for chunk in ai_service.chat_stream(messages, rag_context=rag):
                acc += chunk
                # SSE 格式
                yield f"data: {json.dumps({'chunk': chunk}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
        if acc:
            history_service.append_chat("assistant", acc)

    return Response(stream_with_context(gen()),
                    mimetype="text/event-stream",
                    headers={
                        "Cache-Control": "no-cache",
                        "X-Accel-Buffering": "no",
                    })


# ============ 强制刷新所有缓存 ============

@app.route("/api/refresh", methods=["POST", "GET"])
def api_refresh():
    aggregator.clear_cache()
    return jsonify({"status": "cache cleared"})


# ============ 历史归档 API ============

@app.route("/api/history/days")
def api_history_days():
    """列出所有历史日期"""
    return jsonify({"days": history_service.list_days()})


@app.route("/api/history/days_full")
def api_history_days_full():
    """一次性返回所有日期 + 各日文件清单（前端用这个避免串行）"""
    days = history_service.list_days()
    out = []
    for d in days:
        out.append({"day": d, "files": history_service.list_day_files(d)})
    return jsonify({"days": out})


@app.route("/api/history/<day>")
def api_history_day(day):
    """列出某天所有文件"""
    return jsonify({"day": day, "files": history_service.list_day_files(day)})


@app.route("/api/history/<day>/chat")
def api_history_chat(day):
    """读取当天聊天 jsonl"""
    return jsonify({"day": day, "messages": history_service.read_chat_log(day)})


@app.route("/api/history/<day>/file/<filename>")
def api_history_file(day, filename):
    """读取归档文件（防越界）"""
    if "/" in filename or "\\" in filename or ".." in filename:
        return jsonify({"error": "非法文件名"}), 400
    content = history_service.read_file(day, filename)
    if content is None:
        return jsonify({"error": "文件不存在"}), 404
    return jsonify({"content": content})


# ============ 关注列表 ============

@app.route("/api/focus")
def api_focus():
    """重点关注股票（基础信息，不带详情防止慢）"""
    return jsonify({
        "hk": [{"code": c, "name": n} for c, n in config.HK_FOCUS_STOCKS.items()],
        "a": [{"code": c, "name": n} for c, n in config.A_FOCUS_STOCKS.items()],
    })


@app.route("/api/llm_stocks")
def api_llm_stocks():
    """港股大模型相关股票实时行情（README 提到的智谱/腾讯/小米/商汤等）"""
    from services.stock_service import get_stocks_batch
    codes = list(config.HK_LLM_FOCUS.keys())
    name_map = config.HK_LLM_FOCUS
    results = get_stocks_batch([(c, "HK") for c in codes], name_map=name_map)
    return jsonify(results)


@app.route("/api/api_key")
def api_api_key():
    """告诉前端当前用的是哪个 key（不泄露 key 本身）"""
    return jsonify({
        "subscription_label": "CP",
        "pay_as_you_go_label": "API",
        "active": "subscription",
    })


@app.route("/api/cleanup_today", methods=["POST", "GET"])
def api_cleanup_today():
    """清理今天 history 目录里的所有文件（除了 chat.jsonl）"""
    import shutil
    from datetime import datetime
    today = datetime.now().strftime("%Y-%m-%d")
    day_dir = os.path.join(config.HISTORY_DIR, today)
    if not os.path.isdir(day_dir):
        return jsonify({"status": "no files", "removed": 0})
    removed = 0
    kept = []
    for f in os.listdir(day_dir):
        if f == "chat.jsonl":  # 聊天记录保留
            kept.append(f)
            continue
        full = os.path.join(day_dir, f)
        if os.path.isfile(full):
            os.remove(full)
            removed += 1
    # 清缓存
    aggregator.clear_cache()
    return jsonify({"status": "ok", "removed": removed, "kept": kept})


@app.route("/api/chat/history_today")
def api_chat_history_today():
    """读取今天 chat.jsonl 用于前端初始化恢复聊天记录"""
    from datetime import datetime
    today = datetime.now().strftime("%Y-%m-%d")
    items = history_service.read_chat_log(today)
    return jsonify({"day": today, "messages": items})


@app.route("/api/cleanup_all", methods=["POST", "GET"])
def api_cleanup_all():
    """清理所有历史（保留聊天）"""
    import shutil
    from datetime import datetime
    if not os.path.isdir(config.HISTORY_DIR):
        return jsonify({"status": "no history dir", "removed": 0})
    removed = 0
    for day in os.listdir(config.HISTORY_DIR):
        day_dir = os.path.join(config.HISTORY_DIR, day)
        if not os.path.isdir(day_dir):
            continue
        for f in os.listdir(day_dir):
            if f == "chat.jsonl":
                continue
            full = os.path.join(day_dir, f)
            if os.path.isfile(full):
                os.remove(full)
                removed += 1
    aggregator.clear_cache()
    return jsonify({"status": "ok", "removed": removed})


def _warm_up_background():
    """启动后台预热缓存（轻量预热行情；AI 简报懒加载）"""
    try:
        print("[warmup] preloading market snapshot (parallel)...", flush=True)
        aggregator.get_market_snapshot(force_refresh=True)
        print("[warmup] preloading news snapshot (parallel)...", flush=True)
        aggregator.get_news_snapshot(force_refresh=True)
        # 不预热 AI 简报，避免和用户首访问竞争
        print("[warmup] market + news ready. AI brief is lazy.", flush=True)
    except Exception as e:
        print(f"[warmup] error: {e}", flush=True)


if __name__ == "__main__":
    # 后台线程预热（不阻塞启动）
    threading.Thread(target=_warm_up_background, daemon=True).start()
    print(f"""
============================================================
  量化分析软件 - 启动中
  访问地址: http://{config.SERVER_HOST}:{config.SERVER_PORT}
============================================================
""")
    app.run(host=config.SERVER_HOST, port=config.SERVER_PORT, debug=config.DEBUG, threaded=True)
