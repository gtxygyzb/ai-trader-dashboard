// AI 量化分析终端 - 完整前端（v2 重写）
'use strict';

// ============ 工具函数 ============
function $(id) { return document.getElementById(id); }

function fmtChg(pct) {
  if (pct === null || pct === undefined || isNaN(pct)) return '--';
  var p = Number(pct);
  var sign = p > 0 ? '+' : '';
  return sign + p.toFixed(2) + '%';
}

function chgClass(pct) {
  if (pct === null || pct === undefined || isNaN(pct)) return 'chg-flat';
  var p = Number(pct);
  if (p > 0) return 'chg-up';
  if (p < 0) return 'chg-down';
  return 'chg-flat';
}

function escHtml(s) {
  if (s === null || s === undefined) return '';
  return String(s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function renderMarkdown(text) {
  if (!text) return '';
  // marked 库（CDN 加载）可能还没好——等到就绪再渲染，否则显示原文
  if (typeof marked === 'undefined') {
    // 50ms 后重试一次（最多 10 次 = 500ms），避免页面打开早期 CDN 还没拉到
    setTimeout(function() {
      var pending = document.querySelectorAll('.llm-ai-content[data-pending="1"]');
      for (var i = 0; i < pending.length; i++) {
        var el = pending[i];
        var raw = el.getAttribute('data-raw');
        if (raw) el.innerHTML = renderMarkdown(raw);
      }
    }, 100);
    return escHtml(text);
  }
  try {
    return DOMPurify.sanitize(marked.parse(text));
  } catch (e) {
    return escHtml(text);
  }
}

function nowTs() {
  return new Date().toLocaleTimeString('zh-CN', { hour12: false });
}

function fmtNum(v, digits) {
  if (digits === undefined) digits = 2;
  if (v === null || v === undefined || v === '') return '--';
  var n = Number(v);
  if (isNaN(n)) return v;
  return n.toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: digits });
}

function fmtMarketCap(v) {
  if (!v) return '--';
  var n = Number(v);
  if (isNaN(n)) return '--';
  if (n >= 1e12) return (n / 1e12).toFixed(2) + '万亿';
  if (n >= 1e8) return (n / 1e8).toFixed(0) + '亿';
  if (n >= 1e4) return (n / 1e4).toFixed(0) + '万';
  return String(n);
}

function freshnessFromTs(timeStr, now) {
  if (!timeStr) return '';
  try {
    var t;
    if (timeStr.length <= 5) {
      t = new Date(now.toDateString() + ' ' + timeStr);
    } else {
      t = new Date(timeStr.replace(' ', 'T'));
    }
    if (isNaN(t.getTime())) return '';
    var mins = Math.round((now - t) / 60000);
    if (mins < 0) mins += 24 * 60;
    if (mins < 1) return '刚刚';
    if (mins < 60) return mins + '分钟前';
    if (mins < 24 * 60) return Math.round(mins / 60) + '小时前';
    return Math.round(mins / 1440) + '天前';
  } catch (e) { return ''; }
}

// ============ API 调用 ============
async function fetchJson(url, opts) {
  var ctrl = new AbortController();
  var t = setTimeout(function() { ctrl.abort(); }, 20000);
  try {
    var r = await fetch(url, Object.assign({ signal: ctrl.signal }, opts || {}));
    if (!r.ok) throw new Error('HTTP ' + r.status);
    return await r.json();
  } finally {
    clearTimeout(t);
  }
}

// ============ 顶栏：指数 + 市场状态 ============
async function loadIndices() {
  try {
    var d = await fetchJson('/api/indices');
    var list = d.indices || [];
    if (list.length === 0) {
      $('indicesTicker').innerHTML = '<span class="ticker-loading">指数加载失败</span>';
      return;
    }
    var s = d.market_status || {};
    var aS = s.a_share || {};
    var hkS = s.hk || {};
    var html = '<span class="market-status ' + (aS.status || 'closed') + '">A股 · ' + (aS.label || '?') + '</span>'
             + '<span class="market-status ' + (hkS.status || 'closed') + '">港股 · ' + (hkS.label || '?') + '</span>'
             + '<span class="ticker-sep">|</span>';
    for (var i = 0; i < list.length; i++) {
      var it = list[i];
      var cls = chgClass(it.change_pct);
      html += '<div class="ticker-item">'
            +    '<span class="ticker-name">' + escHtml(it.name) + '</span>'
            +    '<span class="ticker-price">' + fmtNum(it.price) + '</span>'
            +    '<span class="ticker-chg ' + cls + '">' + fmtChg(it.change_pct) + '</span>'
            +  '</div>';
    }
    $('indicesTicker').innerHTML = html;
    $('ts').textContent = (d.ts || '') + '  ' + (aS.reason || aS.label || '');
  } catch (e) {
    console.error('loadIndices err', e);
    $('indicesTicker').innerHTML = '<span class="ticker-loading">指数加载失败</span>';
  }
}

// ============ 行业/概念板块 ============
function renderSectors(targetId, list) {
  if (!list || list.length === 0) {
    $(targetId).innerHTML = '<div class="loading">暂无数据</div>';
    return;
  }
  var html = '';
  for (var i = 0; i < Math.min(5, list.length); i++) {
    var s = list[i];
    var cls = chgClass(s.change_pct);
    html += '<div class="sector-row">'
          +    '<div class="sector-name">' + escHtml(s.name) + '</div>'
          +    '<div class="row-chg ' + cls + '">' + fmtChg(s.change_pct) + '</div>'
          +    '<div class="sector-leader">' + escHtml(s.leader || '--')
          +      '<span class="ld-up">' + fmtChg(s.leader_change_pct) + '</span></div>'
          +  '</div>';
  }
  $(targetId).innerHTML = html;
}

async function loadSectors() {
  try {
    var results = await Promise.all([
      fetchJson('/api/sectors'),
      fetchJson('/api/concepts'),
    ]);
    renderSectors('sectorsBody', results[0]);
    renderSectors('conceptsBody', results[1]);
    var t = nowTs().slice(0, 5);
    $('sectorsTs').textContent = '更新 ' + t;
    $('conceptsTs').textContent = '更新 ' + t;
  } catch (e) {
    console.error('loadSectors err', e);
  }
}

// ============ 港股大模型相关股票（每只带 AI 速评展开）============
async function loadLlmStocks() {
  var target = $('llmBody');
  try {
    var data = await fetchJson('/api/llm_stocks');
    if (!data || data.length === 0) {
      target.innerHTML = '<div class="loading">暂无数据</div>';
      return;
    }
    var html = '<div class="llm-grid">';
    for (var i = 0; i < data.length; i++) {
      var s = data[i];
      var cls = chgClass(s.change_pct);
      var meta = [];
      if (s.market_cap) meta.push('市值 ' + fmtMarketCap(s.market_cap));
      if (s.pe && s.pe !== '-') meta.push('PE ' + s.pe);
      html += '<div class="llm-stock" data-code="' + escHtml(s.code) + '" data-market="HK">'
            +    '<div class="llm-row1">'
            +      '<div class="llm-name">' + escHtml(s.display_name || s.name) + '</div>'
            +      '<div class="llm-code">' + escHtml(s.code) + '</div>'
            +    '</div>'
            +    '<div class="llm-row2">'
            +      '<div class="llm-price">' + fmtNum(s.price) + '</div>'
            +      '<div class="llm-chg ' + cls + '">' + fmtChg(s.change_pct) + '</div>'
            +    '</div>'
            +    '<div class="llm-meta">' + (meta.join(' · ') || '--') + '</div>'
            +    '<div class="llm-ai" data-code="' + escHtml(s.code) + '">'
            +      '<button class="llm-ai-btn">📊 AI 速评</button>'
            +      '<div class="llm-ai-content" style="display:none"></div>'
            +    '</div>'
            +  '</div>';
    }
    html += '</div>';
    target.innerHTML = html;
    // 单独拉市场状态更新徽章
    try {
      var ss = await fetchJson('/api/market_status');
      var hkS = (ss || {}).hk || {};
      $('llmTs').textContent = hkS.label || '实时';
      $('llmTs').className = 'badge ' + (hkS.status || '');
    } catch (e) {}
  } catch (e) {
    console.error('loadLlmStocks err', e);
    target.innerHTML = '<div class="error">港股数据加载失败: ' + escHtml(e.message) + '</div>';
  }
}

// 切换 AI 速评展开
async function toggleLlmAi(code, container) {
  var content = container.querySelector('.llm-ai-content');
  if (content.style.display !== 'none') {
    content.style.display = 'none';
    return;
  }
  content.style.display = 'block';
  content.innerHTML = '<div class="spinner" style="width:20px;height:20px;border-width:2px;margin:0 auto"></div>';
  content.classList.add('loading-inline');
  // 触发后台生成
  fetch('/api/analyze/' + encodeURIComponent(code) + '?market=HK').catch(function(){});
  // 轮询
  var startTime = Date.now();
  function poll() {
    fetchJson('/api/analyze_status/' + encodeURIComponent(code) + '?market=HK')
      .then(function(d) {
        if (d.error && !d.stock) {
          content.innerHTML = '<div style="color:#dc2626;font-size:12px">' + escHtml(d.error) + '</div>';
          content.classList.remove('loading-inline');
          return;
        }
        if (d.pending || !d.analysis) {
          var elapsed = Math.round((Date.now() - startTime) / 1000);
          content.innerHTML = '<div class="spinner" style="width:18px;height:18px;border-width:2px;margin:0 auto 6px"></div>'
            + '<p style="font-size:12px;color:var(--text-dim);text-align:center;margin:0">'
            + 'AI 思考中… ' + elapsed + ' 秒</p>';
          setTimeout(poll, 3000);
          return;
        }
        if (d.analysis) {
          content.setAttribute('data-raw', d.analysis);
          content.setAttribute('data-pending', '1');
          content.innerHTML = renderMarkdown(d.analysis);
          // 渲染完后清掉 pending 标记（renderMarkdown 内部 setTimeout 会扫剩下的 pending）
          if (typeof marked !== 'undefined') {
            content.removeAttribute('data-pending');
          }
          content.classList.remove('loading-inline');
        }
      })
      .catch(function(e) {
        content.innerHTML = '<div style="color:#dc2626;font-size:12px">' + escHtml(e.message) + '</div>';
        content.classList.remove('loading-inline');
      });
  }
  poll();
}

// ============ AI 简报 ============
var _briefPollTimer = null;

async function loadBrief(force) {
  if (_briefPollTimer) { clearTimeout(_briefPollTimer); _briefPollTimer = null; }
  var url = force ? '/api/brief?refresh=1' : '/api/brief';
  $('briefBody').innerHTML = '<div class="loading">'
    + '<div class="spinner"></div>'
    + '<p>' + (force ? 'AI 正在重新生成简报…' : '正在生成简报，首次约 30-60 秒') + '</p>'
    + '</div>';
  try {
    var data = await fetchJson(url);
    if (data.brief && data.pending) {
      $('briefBody').innerHTML = '<div class="loading">'
        + '<div class="spinner"></div>'
        + '<p>' + escHtml(data.brief) + '</p>'
        + '<p><small>2 秒后自动检查…</small></p>'
        + '</div>';
      _briefPollTimer = setTimeout(function() { loadBrief(false); }, 2500);
      return;
    }
    if (data.brief) {
      $('briefBody').innerHTML = renderMarkdown(data.brief);
      $('briefTs').textContent = (data.ts || '').slice(11, 16);
      return;
    }
    $('briefBody').innerHTML = '<div class="error">简报生成失败</div>';
  } catch (e) {
    console.error('loadBrief err', e);
    $('briefBody').innerHTML = '<div class="error">加载失败: ' + escHtml(e.message) + '</div>';
  }
}

// ============ 新闻（国内/国际） ============
function renderNews(targetId, list, limit) {
  if (!list || list.length === 0) {
    $(targetId).innerHTML = '<div class="loading">暂无新闻</div>';
    return;
  }
  var now = new Date();
  var html = '';
  var n = Math.min(limit || 2, list.length);
  for (var i = 0; i < n; i++) {
    var x = list[i];
    var u = (x.url || '#').replace(/'/g, '%27').replace(/"/g, '%22');
    html += '<div class="news-item" onclick="window.open(\'' + u + '\',\'_blank\',\'noopener\')">'
          +    '<div class="news-meta">'
          +      '<span class="news-source">' + escHtml(x.source) + '</span>'
          +      '<span class="news-time">' + escHtml(x.time || '') + '</span>'
          +      '<span class="news-fresh">' + freshnessFromTs(x.time || '', now) + '</span>'
          +    '</div>'
          +    '<div class="news-title">' + escHtml(x.title) + '</div>'
          +  '</div>';
  }
  $(targetId).innerHTML = html;
}

async function loadNews() {
  try {
    var data = await fetchJson('/api/news');
    renderNews('aiNewsCnBody', data.ai_news_cn || [], 2);
    renderNews('aiNewsIntlBody', data.ai_news_intl || [], 2);
    $('newsTs').textContent = '更新 ' + (data.ts || '').slice(11, 16);
  } catch (e) {
    console.error('loadNews err', e);
  }
}

// ============ 个股分析弹窗（拆分：stock 实时数据快返回 + AI 后台）============

function closeModal() { $('modalMask').hidden = true; }
window.closeModal = closeModal;

// ============ 聊天 ============
var chatHistory = [];

function addMessage(role, content, isStream) {
  var wrap = document.createElement('div');
  wrap.className = 'msg ' + role;
  var avatar = role === 'user' ? '🧑' : '🤖';
  wrap.innerHTML = '<div class="msg-avatar">' + avatar + '</div><div class="msg-bubble"></div>';
  var bubble = wrap.querySelector('.msg-bubble');
  if (isStream) {
    bubble.innerHTML = '<span class="typing-cursor"></span>';
  } else {
    bubble.innerHTML = renderMarkdown(content);
  }
  $('chatMessages').appendChild(wrap);
  $('chatMessages').scrollTop = $('chatMessages').scrollHeight;
  return bubble;
}

async function sendChat() {
  var text = $('chatInput').value.trim();
  if (!text) return;
  $('chatInput').value = '';
  $('sendBtn').disabled = true;
  addMessage('user', text);
  chatHistory.push({ role: 'user', content: text });
  var bubble = addMessage('assistant', '', true);
  var acc = '';
  try {
    var useRag = $('useRag').checked;
    var resp = await fetch('/api/chat/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ messages: chatHistory, use_rag: useRag }),
    });
    if (!resp.ok || !resp.body) throw new Error('HTTP ' + resp.status);
    var reader = resp.body.getReader();
    var decoder = new TextDecoder();
    var buf = '';
    while (true) {
      var rd = await reader.read();
      if (rd.done) break;
      buf += decoder.decode(rd.value, { stream: true });
      var lines = buf.split('\n');
      buf = lines.pop() || '';
      for (var i = 0; i < lines.length; i++) {
        var line = lines[i];
        if (!line.startsWith('data: ')) continue;
        var payload = line.slice(6).trim();
        if (payload === '[DONE]') continue;
        try {
          var obj = JSON.parse(payload);
          if (obj.chunk) {
            acc += obj.chunk;
            bubble.innerHTML = renderMarkdown(acc) + '<span class="typing-cursor"></span>';
            $('chatMessages').scrollTop = $('chatMessages').scrollHeight;
          } else if (obj.error) {
            acc += '\n\n⚠️ ' + obj.error;
          }
        } catch (e) {}
      }
    }
    bubble.innerHTML = renderMarkdown(acc) || '(无回复)';
    chatHistory.push({ role: 'assistant', content: acc });
  } catch (e) {
    bubble.innerHTML = '<div class="error">对话失败: ' + escHtml(e.message) + '</div>';
  } finally {
    $('sendBtn').disabled = false;
  }
}

// ============ 深度分析（基于历史 + 实时）============
var _deepPollTimer = null;

async function openDeepAnalysis() {
  var card = $('deepCard');
  if (card) {
    card.style.display = 'block';
    card.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
  var body = $('deepBody');
  if (!body) return;
  if (_deepPollTimer) { clearTimeout(_deepPollTimer); _deepPollTimer = null; }

  body.innerHTML = '<div class="loading">'
    + '<div class="spinner"></div>'
    + '<p>正在生成深度分析（结合 7 天历史 + 实时行情）……首次约 1-2 分钟</p>'
    + '</div>';

  // 兜底轮询
  function poll() {
    fetchJson('/api/deep_analysis').then(function(d) {
      if (d.analysis && d.pending) {
        body.innerHTML = '<div class="loading">'
          + '<div class="spinner"></div>'
          + '<p>' + escHtml(d.analysis) + '</p>'
          + '<p><small>5 秒后自动检查…</small></p>'
          + '</div>';
        _deepPollTimer = setTimeout(poll, 5000);
      } else if (d.analysis) {
        body.innerHTML = renderMarkdown(d.analysis);
        $('deepTs').textContent = '生成: ' + (d.ts || '').slice(11, 16);
        if (_deepPollTimer) { clearTimeout(_deepPollTimer); _deepPollTimer = null; }
      } else {
        body.innerHTML = '<div class="error">生成失败</div>';
      }
    }).catch(function(e) {
      body.innerHTML = '<div class="error">生成失败: ' + escHtml(e.message) + '</div>';
    });
  }
  poll();
}

function closeDeepAnalysis() {
  var card = $('deepCard');
  if (card) card.style.display = 'none';
  if (_deepPollTimer) { clearTimeout(_deepPollTimer); _deepPollTimer = null; }
}

// ============ 事件绑定（用 onproperty，绝不依赖 addEventListener） ============
function bindEvents() {
  try {
    $('sendBtn').onclick = sendChat;
    $('chatInput').onkeydown = function(e) {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendChat(); }
    };
    $('clearChatBtn').onclick = function() {
      chatHistory.length = 0;
      $('chatMessages').innerHTML = '';
      addMessage('assistant', '会话已清空。请继续提问～');
    };
    $('regenBriefBtn').onclick = function() { loadBrief(true); };
    $('refreshAllBtn').onclick = function() {
      var old = $('refreshAllBtn').innerHTML;
      $('refreshAllBtn').disabled = true;
      $('refreshAllBtn').innerHTML = '⟳ 刷新中…';
      fetch('/api/refresh').then(function() {
        return Promise.all([loadIndices(), loadSectors(), loadLlmStocks(), loadNews()]);
      }).then(function() {
        return loadBrief(true);
      }).finally(function() {
        $('refreshAllBtn').disabled = false;
        $('refreshAllBtn').innerHTML = old;
      });
    };
    $('historyBtn').onclick = openDeepAnalysis;
    var closeDeep = $('closeDeepBtn');
    if (closeDeep) closeDeep.onclick = closeDeepAnalysis;

    var modal = $('modalMask');
    if (modal) {
      modal.onmousedown = function(e) { if (e.target === modal) modal.hidden = true; };
    }

    document.onkeydown = function(e) {
      if (e.key === 'Escape') {
        var m1 = $('modalMask'); if (m1 && !m1.hidden) m1.hidden = true;
      }
    };

    var body = $('deepBody');
    if (body) {
      body.onclick = function(e) {
        try {
          var row = e.target.closest ? e.target.closest('.deep-file') : null;
          if (row) {
            // 预留：点击文件展开
          }
        } catch (err) { console.error('deep click err', err); }
      };
    }

    // 港股 LLM 卡片：点击"📊 AI 速评"按钮 → 展开/收起 AI 分析
    var llmBody = $('llmBody');
    if (llmBody) {
      llmBody.onclick = function(e) {
        try {
          var btn = e.target.closest('.llm-ai-btn');
          if (btn) {
            e.stopPropagation();
            var aiContainer = btn.closest('.llm-ai');
            var code = aiContainer.getAttribute('data-code');
            toggleLlmAi(code, aiContainer);
          }
        } catch (err) { console.error('llm-ai click err', err); }
      };
    }
  } catch (err) {
    console.error('bindEvents fatal', err);
  }
}

// ============ API Key 徽章 ============
async function loadApiKeyBadge() {
  try {
    var d = await fetchJson('/api/api_key');
    var lbl = d.active === 'subscription' ? d.subscription_label : d.pay_as_you_go_label;
    $('apiKeyBadge').textContent = '🔑 ' + lbl;
    $('apiKeyBadge').title = '当前: ' + lbl + ' (' + d.active + ')\n优先: ' + d.subscription_label + '  备用: ' + d.pay_as_you_go_label;
  } catch (e) {
    $('apiKeyBadge').textContent = '🔑 ?';
  }
}

// ============ 加载历史聊天（启动时）============
async function loadChatHistory() {
  try {
    var d = await fetchJson('/api/chat/history_today');
    var msgs = d.messages || [];
    // 清空初始欢迎消息，准备重新渲染
    $('chatMessages').innerHTML = '';
    if (msgs.length === 0) {
      // 没有任何历史时显示欢迎消息
      $('chatMessages').innerHTML =
        '<div class="msg assistant">' +
        '  <div class="msg-avatar">🤖</div>' +
        '  <div class="msg-bubble">' +
        '    <p>你好！我是你的 <b>AI 量化分析助手</b>。</p>' +
        '    <p>我可以帮你分析港股大模型龙头、解读行业板块、跟踪 AI 板块异动。</p>' +
        '    <p>试试问我：</p>' +
        '    <ul>' +
        '      <li>「今天港股 AI 股表现怎么样？」</li>' +
        '      <li>「腾讯 00700 现在估值贵不贵？」</li>' +
        '      <li>「小米最近在 AI 上有什么动作？」</li>' +
        '      <li>「商汤、中芯、联想这三只怎么选？」</li>' +
        '    </ul>' +
        '  </div>' +
        '</div>';
      return;
    }
    // 渲染历史消息
    for (var i = 0; i < msgs.length; i++) {
      var m = msgs[i];
      if (m.role === 'user' || m.role === 'assistant') {
        chatHistory.push(m);
        addMessage(m.role, m.content, false);
      }
    }
  } catch (e) {
    console.log('No chat history:', e);
  }
}

// ============ 初始化 ============
async function init() {
  bindEvents();
  loadIndices();
  loadSectors();
  loadLlmStocks();
  loadNews();
  loadBrief(false);
  loadApiKeyBadge();
  loadChatHistory();  // 恢复今日聊天记录

  setInterval(loadIndices, 60000);
  setInterval(function() { loadSectors(); loadLlmStocks(); }, 180000);
  setInterval(loadNews, 300000);
}

// 把 init 暴露到 window 保证执行
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}
