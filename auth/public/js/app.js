// ===== 字数统计（WPS口径） =====
// totalCount = 汉字数 + 英文/数字连续串数 + 中文全角标点数
function countWords(text) {
    if (!text) return 0;
    let count = 0;
    // 1. 汉字：每个算1
    const cjk = text.match(/[\u4e00-\u9fff\u3400-\u4dbf\u{20000}-\u{2a6df}\u{2a700}-\u{2b73f}\u{2b740}-\u{2b81f}\u{2b820}-\u{2ceaf}\u{2ceb0}-\u{2ebef}\u{30000}-\u{3134f}\uf900-\ufaff]/gu) || [];
    count += cjk.length;
    // 2. 中文全角标点：每个算1
    const fullPunct = text.match(/[\uff01-\uff0f\uff1a-\uff20\uff3b-\uff40\uff5b-\uff65\u3000-\u303f\u2018-\u201f\u2026\u2014\u2013\u00b7]/g) || [];
    count += fullPunct.length;
    // 3. 英文/数字连续串：每串算1（内部允许半角标点不拆断）
    const stripped = text.replace(/[\u4e00-\u9fff\u3400-\u4dbf\u{20000}-\u{2a6df}\u{2a700}-\u{2b73f}\u{2b740}-\u{2b81f}\u{2b820}-\u{2ceaf}\u{2ceb0}-\u{2ebef}\u{30000}-\u{3134f}\uf900-\ufaff\uff01-\uff65\u3000-\u303f\u2018-\u201f\u2026\u2014\u2013\u00b7]/gu, ' ');
    const words = stripped.match(/[a-zA-Z0-9](?:[a-zA-Z0-9'_.,:/@%\-]*[a-zA-Z0-9])?/g) || [];
    count += words.length;
    return count;
}

// ===== 全局状态 =====
let currentCard = null;
let authToken = localStorage.getItem('auth_token');
let isProcessing = false;
let currentSessionId = localStorage.getItem('current_session_id') || null;
let currentMode = 'polish'; // 'polish' | 'imitate'
let enhancedMode = false;
let referenceUnlocked = false;
let polishStyle = 'default'; // 'default' | 'preserve' | 'emotional'
let imitateStyle = 'default'; // 'default' | 'preserve' | 'emotional'
let bypassMode = false;
let imitateBypassMode = false;
let styleRefEnabled = false;
let feedbackType = 'suggestion';

// 当前输出状态
let outputSegments = {};
let currentChunk = { index: -1, stage: '', text: '' };
let sseController = null;   // AbortController，用于暂停处理
let layoutText = '';        // 全文合并后的最终文本
let sseWatchdogTimer = null;
let lastSseEventAt = 0;

// ===== 打字机状态 =====
// twShownText：已显示在屏幕上的文字（只追加，绝不修改已显示内容，防止跳变）
// twBuffer：后端最新的完整合并文本（随 partial_layout / layout_done 更新）
// twPos：已从 twBuffer 中取走的字符数（twBuffer 更新后此位置仍有效）
let twShownText = '';
let twBuffer    = '';
let twPos       = 0;
let twTimer     = null;
let twFastMode  = false;
let twOnFinish  = null;

const TW_TICK        = 50;   // ms，固定心跳间隔
const TW_FAST_CHARS  = 25;   // 快速模式：25字/次 → 500字/秒

function twReset() {
    if (twTimer) { clearTimeout(twTimer); twTimer = null; }
    twShownText = ''; twBuffer = ''; twPos = 0;
    twFastMode = false; twOnFinish = null;
}

// 更新缓冲区（只允许增长）
function twUpdateBuffer(newText) {
    if (!newText || newText.length <= twBuffer.length) return;
    twBuffer = newText;
    if (!twTimer && twPos < twBuffer.length) twSchedule();
}

function twSchedule() {
    twTimer = setTimeout(twStep, TW_TICK);
}

function twStep() {
    twTimer = null;
    if (twPos >= twBuffer.length) {
        // 缓冲已全部取完
        document.getElementById('output-text').value = twShownText;
        if (twOnFinish) { const cb = twOnFinish; twOnFinish = null; cb(); }
        return;
    }
    // 指数加速：每秒显示已打出字数的 20%（每 50ms 取 1%）
    // 快速模式固定 25 字/次
    const chars = twFastMode
        ? TW_FAST_CHARS
        : Math.max(2, Math.round(twPos * 0.01));  // 约 20%/秒，最少 2 字

    const newChars = twBuffer.slice(twPos, twPos + chars);
    twPos       += newChars.length;
    twShownText += newChars;  // 只追加，已显示内容永不改变

    const outputEl = document.getElementById('output-text');
    if (twPos < twBuffer.length) {
        outputEl.value = twShownText + '▌';
        twSchedule();
    } else {
        outputEl.value = twShownText;
        if (twOnFinish) { const cb = twOnFinish; twOnFinish = null; cb(); }
    }
}

// 切换快速冲刺模式，并在打完后执行回调
function twGoFast(onFinish) {
    twFastMode = true;
    twOnFinish = onFinish;
    if (!twTimer && twPos < twBuffer.length) twSchedule();
    else if (twPos >= twBuffer.length && onFinish) onFinish();
}

// ===== Cooking 指示器 =====
let cookingTimer = null;
const cookingTexts = ['cooking...', '制作中...'];
let cookingIdx = 0;

function startCooking() {
    const el = document.getElementById('cooking-indicator');
    if (!el) return;
    cookingIdx = 0;
    el.textContent = cookingTexts[0];
    el.style.display = '';
    cookingTimer = setInterval(() => {
        cookingIdx = (cookingIdx + 1) % cookingTexts.length;
        el.textContent = cookingTexts[cookingIdx];
        // 触发淡入动画（重新挂载 class）
        el.classList.remove('cooking-indicator');
        void el.offsetWidth; // reflow
        el.classList.add('cooking-indicator');
    }, 2000);
}

function stopCooking() {
    if (cookingTimer) { clearInterval(cookingTimer); cookingTimer = null; }
    const el = document.getElementById('cooking-indicator');
    if (el) el.style.display = 'none';
}

// ===== 怀旧稳定版跳转 =====
function goToStableVersion() {
    const token = localStorage.getItem('auth_token') || '';
    const url = 'http://119.29.150.211:9700' + (token ? '?token=' + encodeURIComponent(token) : '');
    window.open(url, '_blank');
}

// ===== JWT 工具 =====
function parseJwt(token) {
    try {
        // JWT 用 base64url 编码（无 = 号，+ 换成 -，/ 换成 _），atob 要求标准 base64
        let b64 = token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
        b64 += '='.repeat((4 - b64.length % 4) % 4);
        return JSON.parse(atob(b64));
    } catch { return {}; }
}
function isUserJwt(token) { const p = parseJwt(token); return p && p.type === 'user'; }
// 卡密 JWT：payload 含 card_id（无 type 字段）
function isCardJwt(token) { const p = parseJwt(token); return p && !!p.card_id; }
function isValidToken(token) { return token && (isUserJwt(token) || isCardJwt(token)); }

// ===== 初始化 =====
document.addEventListener('DOMContentLoaded', async () => {
    removeImitateTargetCharControls();
    // 未登录 → 跳登录页
    if (!isValidToken(authToken)) {
        window.location.href = '/login';
        return;
    }

    loadUserInfo();
    tryResumeSession();
    document.getElementById('feedback-modal')?.addEventListener('click', e => {
        if (e.target === e.currentTarget) closeFeedbackModal();
    });
});

// ===== Toast =====
function showToast(msg, type = '') {
    const toast = document.getElementById('toast');
    toast.textContent = msg;
    toast.className = 'toast ' + type;
    toast.style.display = 'block';
    clearTimeout(toast._timer);
    toast._timer = setTimeout(() => { toast.style.display = 'none'; }, 5000);
}

function showToastPersistent(msg, type = '') {
    const toast = document.getElementById('toast');
    toast.textContent = msg;
    toast.className = 'toast ' + type;
    toast.style.display = 'block';
    clearTimeout(toast._timer);
    toast._timer = null; // 不自动隐藏
}

function hideToast() {
    const toast = document.getElementById('toast');
    clearTimeout(toast._timer);
    toast.style.display = 'none';
}

function showFeedbackModal() {
    if (!authToken) { showCardAuthOverlay(); return; }
    document.getElementById('feedback-modal').style.display = 'flex';
    document.getElementById('feedback-input').value = '';
    document.getElementById('feedback-error').textContent = '';
    setFeedbackType('suggestion');
    setTimeout(() => document.getElementById('feedback-input').focus(), 100);
}
function closeFeedbackModal() {
    document.getElementById('feedback-modal').style.display = 'none';
}

function setFeedbackType(type) {
    feedbackType = type === 'article_feedback' ? 'article_feedback' : 'suggestion';
    const isSuggestion = feedbackType === 'suggestion';
    document.getElementById('feedback-type-suggestion')?.classList.toggle('active', isSuggestion);
    document.getElementById('feedback-type-article')?.classList.toggle('active', !isSuggestion);
    const descEl = document.getElementById('feedback-desc');
    const labelEl = document.getElementById('feedback-input-label');
    const inputEl = document.getElementById('feedback-input');
    if (descEl) {
        descEl.textContent = isSuggestion
            ? '填写你的建议内容即可，这类记录会直接进入管理员后台。'
            : '填写你遇到的文章问题，系统会自动附带当前润色输入框内的文章原文，一起同步到管理员后台。';
    }
    if (labelEl) labelEl.textContent = isSuggestion ? '建议内容' : '反馈内容';
    if (inputEl) {
        inputEl.placeholder = isSuggestion
            ? '例如：建议增加某个功能，或者把某个按钮放到更显眼的位置。'
            : '例如：这篇文章降不下来、输出太长、语气不对，或者这里的流式输出不正常。';
    }
}

function getFeedbackOriginalText() {
    return document.getElementById('input-text')?.value?.trim() || '';
}

async function submitFeedback() {
    const issue = document.getElementById('feedback-input').value.trim();
    const originalText = feedbackType === 'article_feedback' ? getFeedbackOriginalText() : '';
    const errorEl = document.getElementById('feedback-error');
    const btn = document.getElementById('feedback-submit');

    if (!issue) {
        errorEl.textContent = feedbackType === 'suggestion' ? '请输入你的建议内容' : '请输入你遇到的问题';
        return;
    }
    if (feedbackType === 'article_feedback' && !originalText) { errorEl.textContent = '当前润色输入框里没有可附带的文章原文'; return; }

    btn.disabled = true;
    btn.textContent = '提交中...';
    errorEl.textContent = '';

    try {
        const resp = await fetch('/api/feedback', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + authToken },
            body: JSON.stringify({
                report_type: feedbackType,
                issue_text: issue,
                original_text: originalText,
                mode: enhancedMode ? 'enhanced_imitate' : currentMode,
                session_id: currentSessionId || ''
            })
        });
        const data = await resp.json();
        if (!resp.ok) { errorEl.textContent = data.error || '反馈提交失败'; return; }

        closeFeedbackModal();
        showFeedbackThanksModal();
    } catch (e) {
        errorEl.textContent = '网络错误，请稍后重试';
    } finally {
        btn.disabled = false;
        btn.textContent = '提交反馈';
    }
}

function showFeedbackThanksModal() {
    const modal = document.getElementById('refusal-prompt-modal');
    modal.innerHTML = `
      <div style="background:#1e293b;border:1px solid #334155;border-radius:16px;padding:28px 32px;max-width:380px;width:90%;text-align:center;box-shadow:0 24px 48px rgba(0,0,0,.5)">
        <div style="font-size:36px;margin-bottom:14px">🙏</div>
        <div style="font-size:16px;font-weight:700;color:#f1f5f9;margin-bottom:8px">感谢你的反馈</div>
        <div style="font-size:13px;color:#94a3b8;line-height:1.7;margin-bottom:24px">感谢你的反馈，我们会在你的帮助下变得越来越好。</div>
        <button onclick="onRefusalNo()" style="width:100%;padding:11px;border-radius:8px;border:none;background:#6366f1;color:#fff;font-size:14px;font-weight:600;cursor:pointer">好的</button>
      </div>`;
    modal.style.display = 'flex';
}

// ===== 用户信息 =====
async function loadUserInfo() {
    if (!authToken) { window.location.href = '/login'; return; }
    try {
        const resp = await fetch('/api/user/info', { headers: { 'Authorization': 'Bearer ' + authToken } });
        if (!resp.ok) {
            authToken = null;
            localStorage.removeItem('auth_token');
            window.location.href = '/login';
            return;
        }
        currentCard = await resp.json();
        updateUserUI();
    } catch (e) { window.location.href = '/login'; }
}

function formatCredit(card) {
    if (!card) return '';
    if (card.card_type === 'chars') {
        const wan = Math.floor((card.remaining_chars || 0) / 10000);
        const rem = (card.remaining_chars || 0) % 10000;
        return wan > 0 ? `剩余字数: ${wan}万${rem > 0 ? rem : ''}字` : `剩余字数: ${card.remaining_chars || 0}字`;
    }
    return `剩余次数: ${card.remaining_uses}`;
}

function updateUserUI() {
    const userArea = document.getElementById('user-area');
    const infoBar = document.getElementById('user-info-bar');
    // 邮箱账号模式
    const email = (currentCard && currentCard.email) || localStorage.getItem('user_email') || '';
    const displayEmail = email.length > 24 ? email.substring(0, 21) + '...' : email;
    userArea.style.display = '';
    userArea.innerHTML = `
        ${displayEmail ? `<span style="color:var(--text-2);font-size:13px;margin-right:8px;">${displayEmail}</span>` : ''}
        <button class="nav-btn" onclick="logout()">退出登录</button>
    `;
    // 信息栏：邮箱用户免费阶段隐藏余额
    if (currentCard && !currentCard.userMode) {
        infoBar.style.display = 'flex';
        document.getElementById('user-card-code').textContent = '';
        document.getElementById('user-remaining').textContent = formatCredit(currentCard);
    } else {
        infoBar.style.display = 'none';
    }
}

function logout() {
    authToken = null; currentCard = null;
    localStorage.removeItem('auth_token');
    localStorage.removeItem('user_email');
    window.location.href = '/login';
}

// 兼容旧引用（防止其他地方调用报错）
function showCardAuthOverlay() { window.location.href = '/login'; }

// ===== 输入 =====
function updateCharCount() {
    const text = document.getElementById('input-text').value;
    const len = countWords(text);
    document.getElementById('char-count').textContent = len;
    document.getElementById('char-count').style.color = len > 3500 ? '#ef4444' : '';
}
function updateImitateCount() {
    const text = document.getElementById('imitate-news').value;
    const n = countWords(text);
    document.getElementById('char-count').textContent = n;
    document.getElementById('char-count').style.color = n > 3500 ? '#ef4444' : '';
    const hint = document.getElementById('imitate-chars-hint');
    if (hint) hint.textContent = `原文：${n} 字`;
}
function clearInput() {
    if (currentMode === 'imitate') {
        document.getElementById('imitate-news').value = '';
        document.getElementById('imitate-reference').value = '';
        updateImitateCount();
    } else {
        document.getElementById('input-text').value = '';
        document.getElementById('char-count').textContent = '0';
    }
}

// ===== 复制 =====
function copyOutput() {
    const el = document.getElementById('output-text');
    const text = el.value;
    if (!text || text.trim() === '处理结果将显示在这里...') {
        showToast('没有可复制的内容', 'warning'); return;
    }
    const doCopy = () => {
        const ta = document.createElement('textarea');
        ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0';
        document.body.appendChild(ta); ta.focus(); ta.select();
        try { document.execCommand('copy'); showToast('已复制到剪贴板', 'success'); }
        catch (e) { showToast('复制失败，请手动复制', 'error'); }
        document.body.removeChild(ta);
    };
    if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(text).then(() => showToast('已复制到剪贴板', 'success')).catch(doCopy);
    } else { doCopy(); }
}

// ===== 朱雀质检 =====
function openZhuqueDetect() {
    const el = document.getElementById('output-text');
    const text = el.value;
    if (!text || text.trim() === '处理结果将显示在这里...') {
        showToast('请先处理文章再检测', 'warning'); return;
    }
    const doOpen = () => {
        window.open('https://matrix.tencent.com/ai-detect/', '_blank');
        showToast('结果已复制，在朱雀质检页面粘贴即可', 'success');
    };
    if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(text).then(doOpen).catch(() => {
            const ta = document.createElement('textarea');
            ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0';
            document.body.appendChild(ta); ta.focus(); ta.select();
            try { document.execCommand('copy'); } catch(e) {}
            document.body.removeChild(ta);
            doOpen();
        });
    } else {
        const ta = document.createElement('textarea');
        ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0';
        document.body.appendChild(ta); ta.focus(); ta.select();
        try { document.execCommand('copy'); } catch(e) {}
        document.body.removeChild(ta);
        doOpen();
    }
}

// ===== 清空输出 =====
function clearOutput() {
    if (isProcessing) { showToast('处理中，请先暂停', 'warning'); return; }
    twReset();
    outputSegments = {};
    layoutText = '';
    currentChunk = { index: -1, stage: '', text: '' };
    document.getElementById('output-text').value = '';
    document.getElementById('output-text').placeholder = '处理结果将显示在这里...';
    document.getElementById('output-info').textContent = '';
    document.getElementById('progress-wrap').style.display = 'none';
    document.getElementById('stage-indicator').style.display = 'none';
    document.getElementById('retry-btn').style.display = 'none';
}

// ===== 两两合并段落 + 字数修正（前端备用）=====
function countChinese(text) {
    return countWords(text);
}
function mergeAdjacentParagraphs(text) {
    const sep = '\n\n';
    let paras = text.split(sep).map(p => p.trim()).filter(p => p);
    if (paras.length <= 1) return text;

    // 第一步：两两合并
    const merged = [];
    for (let i = 0; i < paras.length; i += 2) {
        merged.push(i + 1 < paras.length ? paras[i] + paras[i + 1] : paras[i]);
    }
    paras = merged;

    // 第二步：循环检测低于250字的段落，并入相邻较短段
    let changed = true;
    while (changed) {
        changed = false;
        for (let i = 0; i < paras.length; i++) {
            if (countChinese(paras[i]) < 250 && paras.length > 1) {
                const prevLen = i > 0 ? countChinese(paras[i - 1]) : Infinity;
                const nextLen = i < paras.length - 1 ? countChinese(paras[i + 1]) : Infinity;
                if (prevLen <= nextLen && i > 0) {
                    paras[i - 1] = paras[i - 1].replace(/[，,]$/, '') + '。' + paras[i];
                    paras.splice(i, 1);
                } else if (i < paras.length - 1) {
                    paras[i] = paras[i].replace(/[，,]$/, '') + '。' + paras[i + 1];
                    paras.splice(i + 1, 1);
                }
                changed = true;
                break;
            }
        }
    }
    return paras.join(sep);
}

// ===== 清理仿写自定义字数控件 =====
function removeImitateTargetCharControls() {
    const keepBtn = document.getElementById('wc-btn-keep');
    const input = document.getElementById('target-chars-input');
    const hint = document.getElementById('imitate-chars-hint');
    const row = keepBtn?.parentElement || input?.parentElement || hint?.parentElement;

    keepBtn?.remove();
    input?.remove();

    if (hint) {
        hint.style.marginLeft = '0';
    }

    const label = row?.querySelector('span:not(#imitate-chars-hint)');
    label?.remove();
}

// ===== 参考风格解锁 =====
function toggleReferenceLock() {
    const refEl = document.getElementById('imitate-reference');
    const btn = document.getElementById('btn-unlock-ref');
    referenceUnlocked = !referenceUnlocked;
    if (referenceUnlocked) {
        refEl.readOnly = false;
        refEl.style.color = '';
        refEl.style.cursor = '';
        refEl.value = '';
        refEl.placeholder = '请粘贴想要模仿的风格文章...';
        btn.textContent = '🔓 已解锁';
        btn.style.borderColor = '#10b981';
        btn.style.color = '#10b981';
    } else {
        refEl.readOnly = true;
        refEl.style.color = '#475569';
        refEl.style.cursor = 'default';
        refEl.value = '';
        refEl.placeholder = '（使用内置参考风格）';
        btn.textContent = '🔒 解锁自定义';
        btn.style.borderColor = '';
        btn.style.color = '';
    }
}

// ===== 模式切换 =====
function switchMode(mode, keepEnhanced) {
    if (isProcessing) { showToast('处理中，无法切换模式', 'warning'); return; }
    // 切换模式时，把当前输入框的内容带到目标输入框
    const polishEl = document.getElementById('input-text');
    const imitateEl = document.getElementById('imitate-news');
    if (mode === 'imitate' && polishEl.value.trim() && !imitateEl.value.trim()) {
        imitateEl.value = polishEl.value;
        updateImitateCount();
    } else if (mode === 'polish' && imitateEl.value.trim() && !polishEl.value.trim()) {
        polishEl.value = imitateEl.value;
        updateCharCount();
    }
    if (!keepEnhanced) enhancedMode = false;
    currentMode = mode;
    document.getElementById('mode-btn-polish').classList.toggle('active', mode === 'polish');
    document.getElementById('mode-btn-imitate').classList.toggle('active', mode === 'imitate');
    document.getElementById('polish-inputs').style.display = mode === 'polish' ? 'flex' : 'none';
    document.getElementById('imitate-inputs').style.display = mode === 'imitate' ? 'flex' : 'none';
    document.getElementById('btn-polish').style.display = mode === 'polish' ? '' : 'none';
    document.getElementById('btn-imitate').style.display = mode === 'imitate' ? '' : 'none';
    document.getElementById('input-panel-title').textContent = mode === 'imitate' ? '需要处理的文章' : '需要处理的文章';
    document.getElementById('max-chars').textContent = mode === 'imitate' ? '3500' : '3500';
    const cantReduceBtn = document.getElementById('btn-cant-reduce');
    if (cantReduceBtn) cantReduceBtn.style.display = 'none';
    document.getElementById('enhance-nudge')?.classList.remove('show');
    clearOutput();
}

// ===== 降不下来 → 跳转增强仿写 =====
function goToEnhancedImitate() {
    const text = document.getElementById('input-text').value;
    if (!text || text.trim() === '') { showToast('原稿为空，请先输入文章', 'warning'); return; }
    enhancedMode = true;
    switchMode('imitate', true);
    const newsEl = document.getElementById('imitate-news');
    newsEl.value = text.trim();
    newsEl.readOnly = false;
    newsEl.style.background = '';
    newsEl.style.color = '';
    updateImitateCount();
    const badge = document.getElementById('enhanced-mode-badge');
    if (badge) badge.style.display = '';
    showToast('已填入原稿，请粘贴参考风格文章后提交', 'info');
}

// ===== AI 输出过短提示 =====
function checkShortOutput(text) {
    if ((text || '').replace(/\s/g, '').length < 200) {
        const modal = document.getElementById('refusal-prompt-modal');
        modal.innerHTML = `
          <div style="background:#1e293b;border:1px solid #334155;border-radius:16px;padding:28px 32px;max-width:360px;width:90%;text-align:center;box-shadow:0 24px 48px rgba(0,0,0,.5)">
            <div style="font-size:36px;margin-bottom:14px">🤔</div>
            <div style="font-size:16px;font-weight:700;color:#f1f5f9;margin-bottom:8px">AI 好像被拒绝了？</div>
            <div style="font-size:13px;color:#94a3b8;line-height:1.6;margin-bottom:24px">输出字数偏少，可能触发了限制<br>要帮你切换设置，再试一次吗？</div>
            <div style="display:flex;gap:12px">
              <button onclick="onRefusalNo()" style="flex:1;padding:10px;border-radius:8px;border:1px solid #334155;background:#0f172a;color:#94a3b8;font-size:14px;cursor:pointer">没有，继续</button>
              <button onclick="onRefusalYes()" style="flex:1;padding:10px;border-radius:8px;border:none;background:#6366f1;color:#fff;font-size:14px;font-weight:600;cursor:pointer">是的，帮我调整</button>
            </div>
          </div>`;
        modal.style.display = 'flex';
    }
}
function showRepeatRefundModal(chars) {
    const modal = document.getElementById('refusal-prompt-modal');
    modal.innerHTML = `
      <div style="background:#1e293b;border:1px solid #334155;border-radius:16px;padding:28px 32px;max-width:380px;width:90%;text-align:center;box-shadow:0 24px 48px rgba(0,0,0,.5)">
        <div style="font-size:36px;margin-bottom:14px">💡</div>
        <div style="font-size:16px;font-weight:700;color:#f1f5f9;margin-bottom:8px">检测到重复润色</div>
        <div style="font-size:13px;color:#94a3b8;line-height:1.7;margin-bottom:24px">同一篇文章重复润色，系统已自动返还 <span style="color:#fbbf24;font-weight:700">${chars}</span> 字。</div>
        <button onclick="closeRepeatRefundModal()" style="width:100%;padding:11px;border-radius:8px;border:none;background:#6366f1;color:#fff;font-size:14px;font-weight:600;cursor:pointer">我知道了</button>
      </div>`;
    modal.style.display = 'flex';
}
function closeRepeatRefundModal() {
    document.getElementById('refusal-prompt-modal').style.display = 'none';
}
function onRefusalYes() {
    if (currentMode === 'imitate') {
        setImitateStyle('emotional');
        if (!imitateBypassMode) toggleImitateBypass();
    } else {
        setPolishStyle('emotional');
        if (!bypassMode) toggleBypass();
    }
    document.getElementById('refusal-prompt-modal').innerHTML = `
      <div style="background:#1e293b;border:1px solid #334155;border-radius:16px;padding:28px 32px;max-width:360px;width:90%;text-align:center;box-shadow:0 24px 48px rgba(0,0,0,.5)">
        <div style="font-size:36px;margin-bottom:14px">✅</div>
        <div style="font-size:16px;font-weight:700;color:#f1f5f9;margin-bottom:8px">已为你调整好了！</div>
        <div style="font-size:13px;color:#94a3b8;line-height:1.6;margin-bottom:24px">已切换为<span style="color:#fbbf24;font-weight:600">情感丰富</span>风格<br>并开启了<span style="color:#f87171;font-weight:600">防拒绝</span>模式<br><br>重新提交试试吧 🚀</div>
        <button onclick="onRefusalNo()" style="width:100%;padding:11px;border-radius:8px;border:none;background:#6366f1;color:#fff;font-size:14px;font-weight:600;cursor:pointer">好的，我知道了</button>
      </div>`;
}
function onRefusalNo() {
    document.getElementById('refusal-prompt-modal').style.display = 'none';
}

// ===== 防拒绝开关 =====
function toggleBypass() {
    bypassMode = !bypassMode;
    const btn = document.getElementById('bypass-btn');
    btn.textContent = bypassMode ? '已开启' : '已关闭';
    btn.classList.toggle('active', bypassMode);
}
function toggleImitateBypass() {
    imitateBypassMode = !imitateBypassMode;
    const btn = document.getElementById('imitate-bypass-btn');
    btn.textContent = imitateBypassMode ? '已开启' : '已关闭';
    btn.classList.toggle('active', imitateBypassMode);
}

// ===== 仿写语气切换 =====
function setImitateStyle(style) {
    imitateStyle = style;
    document.getElementById('imitate-style-btn-default').classList.toggle('active', style === 'default');
    document.getElementById('imitate-style-btn-preserve').classList.toggle('active', style === 'preserve');
    document.getElementById('imitate-style-btn-emotional').classList.toggle('active', style === 'emotional');
}

// ===== 参考文章风格折叠 =====
function toggleStyleRef() {
    styleRefEnabled = !styleRefEnabled;
    const btn = document.getElementById('style-ref-toggle-btn');
    const area = document.getElementById('style-ref-area');
    btn.classList.toggle('active', styleRefEnabled);
    btn.textContent = styleRefEnabled ? '已开启' : '自定义文章风格';
    area.style.display = styleRefEnabled ? 'flex' : 'none';
}

// ===== 润色风格切换 =====
function setPolishStyle(style) {
    polishStyle = style;
    document.getElementById('style-btn-default').classList.toggle('active', style === 'default');
    document.getElementById('style-btn-preserve').classList.toggle('active', style === 'preserve');
    document.getElementById('style-btn-emotional').classList.toggle('active', style === 'emotional');
}

// ===== 文章类型选择弹窗 =====
let _articleTypeCallback = null;
function onArticleType(type) {
    document.getElementById('article-type-modal').style.display = 'none';
    if (_articleTypeCallback) {
        const cb = _articleTypeCallback;
        _articleTypeCallback = null;
        cb(type);
    }
}

function showArticleTypeModal(callback) {
    _articleTypeCallback = callback;
    document.getElementById('article-type-modal').style.display = 'flex';
}

function closeArticleTypeModal() {
    document.getElementById('article-type-modal').style.display = 'none';
    _articleTypeCallback = null;
}

// ===== 提交润色 =====
async function submitPolish() {
    if (isProcessing) return;
    const text = document.getElementById('input-text').value.trim();
    if (!text) { showToast('请先输入需要处理的文本', 'warning'); return; }
    if (!authToken) { showCardAuthOverlay(); return; }
    if (text.length > 3500) { showToast('文字最多 3500 字', 'warning'); return; }

    showArticleTypeModal(type => {
        if (type === 'digital') setPolishStyle('emotional');
        else if (type === 'emotional') setPolishStyle('default');
        _doSubmitPolish();
    });
}

async function _doSubmitPolish() {
    const text = document.getElementById('input-text').value.trim();
    resetOutputUI();
    setPolishUI(true);

    try {
        const resp = await fetch('/api/process/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + authToken },
            body: JSON.stringify({ text, style: polishStyle, bypass: bypassMode })
        });
        const data = await resp.json();
        if (!resp.ok) {
            showToast(data.error || '启动失败', 'error');
            setPolishUI(false); return;
        }

        if (currentCard) {
            if (data.card_type === 'chars' || currentCard.card_type === 'chars') {
                currentCard.card_type = 'chars';
                if (data.remaining_chars !== undefined) currentCard.remaining_chars = data.remaining_chars;
            } else if (data.remaining_uses !== undefined) {
                currentCard.remaining_uses = data.remaining_uses;
            }
            document.getElementById('user-remaining').textContent = formatCredit(currentCard);
        }

        currentSessionId = data.sessionId;
        localStorage.setItem('current_session_id', currentSessionId);
        await listenToSession(currentSessionId);

    } catch (e) {
        showToast('网络错误，请稍后重试', 'error');
        setPolishUI(false);
    }
}

// ===== 提交增强降AI =====
async function submitImitate() {
    if (isProcessing) return;
    if (!authToken) { showCardAuthOverlay(); return; }
    const newsText = document.getElementById('imitate-news').value.trim();
    if (!newsText) { showToast('请输入需要处理的文章', 'warning'); return; }
    if (newsText.length > 3500) { showToast('文章最多 3500 字', 'warning'); return; }

    showArticleTypeModal(type => {
        if (type === 'digital') setImitateStyle('emotional');
        else if (type === 'emotional') setImitateStyle('default');
        _doSubmitImitate();
    });
}

async function _doSubmitImitate() {
    const newsText = document.getElementById('imitate-news').value.trim();
    resetOutputUI();
    setImitateUI(true);

    try {
        const resp = await fetch('/api/imitate/enhanced/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + authToken },
            body: JSON.stringify({ news_text: newsText, bypass: imitateBypassMode, style: imitateStyle, style_ref: styleRefEnabled ? (document.getElementById('style-ref-text').value.trim()) : '' })
        });
        const data = await resp.json();
        if (!resp.ok) { showToast(data.error || '启动失败', 'error'); setImitateUI(false); return; }

        currentSessionId = data.sessionId;
        localStorage.setItem('current_session_id', currentSessionId);
        await listenToSession(currentSessionId);
    } catch (e) {
        showToast('网络错误，请稍后重试', 'error');
        setImitateUI(false);
    }
}

// ===== SSE 监听 =====
async function listenToSession(sessionId) {
    sseController = new AbortController();
    lastSseEventAt = Date.now();

    if (sseWatchdogTimer) clearInterval(sseWatchdogTimer);
    sseWatchdogTimer = setInterval(() => {
        if (!isProcessing) return;
        if (!lastSseEventAt) return;
        const idleMs = Date.now() - lastSseEventAt;
        if (idleMs < 120000) return;
        if (sseController) { sseController.abort(); sseController = null; }
        currentSessionId = null;
        localStorage.removeItem('current_session_id');
        showToast('处理超时，请重新提交', 'warning');
        setPolishUI(false);
        setImitateUI(false);
        clearInterval(sseWatchdogTimer);
        sseWatchdogTimer = null;
    }, 5000);

    try {
        const resp = await fetch(`/api/process/${sessionId}/events`, {
            headers: { 'Authorization': 'Bearer ' + authToken },
            signal: sseController.signal
        });
        if (!resp.ok) {
            showToast('连接失败', 'error'); setPolishUI(false); return;
        }

        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let sessionFinished = false; // 收到 done 或 error 事件才算正常结束

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n'); buffer = lines.pop();
            for (const line of lines) {
                if (!line.startsWith('data:')) continue;
                const raw = line.slice(5).trim();
                try {
                    const ev = JSON.parse(raw);
                    lastSseEventAt = Date.now();
                    if (ev.type === 'done' || ev.type === 'error') sessionFinished = true;
                    handleSSEEvent(ev);
                } catch (e) {}
            }
        }

        // 流结束但没有收到完成事件，说明连接被意外切断
        if (!sessionFinished && isProcessing) {
            showToast('连接中断，请重新提交', 'warning');
            setPolishUI(false);
            currentSessionId = null;
            localStorage.removeItem('current_session_id');
        }
    } catch (e) {
        if (e.name === 'AbortError') return;
        if (isProcessing) {
            currentSessionId = null;
            localStorage.removeItem('current_session_id');
            showToast('连接中断，请重新提交', 'warning');
            setPolishUI(false);
        }
    } finally {
        if (sseWatchdogTimer) { clearInterval(sseWatchdogTimer); sseWatchdogTimer = null; }
        lastSseEventAt = 0;
        sseController = null;
    }
}

// ===== 暂停处理 =====
async function stopProcessing() {
    if (sseController) { sseController.abort(); sseController = null; }

    if (currentSessionId && authToken) {
        try {
            const resp = await fetch(`/api/process/${currentSessionId}/cancel`, {
                method: 'POST',
                headers: { 'Authorization': 'Bearer ' + authToken }
            });
            const data = await resp.json();
            if (currentCard) {
                if (data.card_type === 'chars' || currentCard.card_type === 'chars') {
                    currentCard.card_type = 'chars';
                    if (data.remaining_chars !== undefined) currentCard.remaining_chars = data.remaining_chars;
                } else if (data.remaining_uses !== undefined) {
                    currentCard.remaining_uses = data.remaining_uses;
                }
                document.getElementById('user-remaining').textContent = formatCredit(currentCard);
            }
        } catch (e) {}
    }

    if (currentMode === 'imitate') setImitateUI(false); else setPolishUI(false);
    showToast('已暂停处理，本次用量已退回', 'warning');
}

// ===== SSE 事件处理 =====
function handleSSEEvent(ev) {
    switch (ev.type) {
        case 'queued':
            setStageIndicator(`排队中，前方还有 ${ev.position} 个任务...`);
            showToastPersistent(`排队中，前方还有 ${ev.position} 个任务，请稍候...`, 'warning');
            document.getElementById('output-text').value = `排队中，前方还有 ${ev.position} 个任务，请稍等...`;
            break;

        case 'start':
            hideToast();
            if (ev.mode === 'enhanced_imitate') {
                document.getElementById('output-text').value = '';
                document.getElementById('progress-wrap').style.display = 'none';
                setStageIndicator('仿写中...');
            } else if (ev.mode === 'imitate') {
                document.getElementById('output-text').value = '';
                document.getElementById('progress-wrap').style.display = 'none';
                setStageIndicator('仿写中...');
            } else {
                setProgressBar(0);
                document.getElementById('progress-wrap').style.display = 'flex';
                document.getElementById('output-text').value = '';
                outputSegments = {};
                layoutText = '';
            }
            break;

        case 'segment_skip':
            outputSegments[ev.index] = ev.text;
            renderOutput();
            break;

        case 'segment_start':
            setStageIndicator(`第 ${ev.index + 1}/${ev.total} 段 · 润色中...`);
            currentChunk = { index: ev.index, stage: ev.stage, text: '' };
            break;

        case 'chunk': {
            // 所有模式实时直接追加到输出框
            const chunkEl = document.getElementById('output-text');
            chunkEl.value += ev.delta;
            chunkEl.scrollTop = chunkEl.scrollHeight;
            break;
        }

        case 'segment_done':
            if (ev.stage === 'enhance') {
                outputSegments[ev.index] = ev.text;
                currentChunk = { index: -1, stage: '', text: '' };
                // 不直接 renderOutput，等 partial_layout 来驱动打字机
            }
            break;

        case 'progress':
            setProgressBar(ev.percent);
            break;

        case 'uses_updated':
            if (currentCard) {
                if (ev.card_type === 'chars' || currentCard.card_type === 'chars') {
                    currentCard.card_type = 'chars';
                    if (ev.remaining_chars !== undefined) currentCard.remaining_chars = ev.remaining_chars;
                } else {
                    if (ev.remaining_uses !== undefined) currentCard.remaining_uses = ev.remaining_uses;
                }
                document.getElementById('user-remaining').textContent = formatCredit(currentCard);
            }
            break;

        case 'repeat_refund':
            showRepeatRefundModal(ev.chars);
            break;

        case 'partial_layout':
            // 每批段完成后的中间合并结果 → 喂给打字机（慢速）
            twUpdateBuffer(ev.text);
            break;

        case 'layout_start':
            layoutText = '';
            setStageIndicator('段落合并中...');
            break;

        case 'layout_chunk':
            layoutText += ev.delta || '';
            break;

        case 'phase1_start':
            document.getElementById('output-text').value = '';
            setStageIndicator('第一阶段：解构分析中...');
            break;

        case 'phase2_start':
            document.getElementById('output-text').value = '';
            setStageIndicator('第二阶段：润色优化中...');
            break;

        case 'stuck_retry':
            // 清空已输出的内容，重新开始这一阶段
            outputSegments = {};
            layoutText = '';
            document.getElementById('output-text').value = '';
            setStageIndicator(`检测到卡顿，正在重试（第 ${ev.attempt || 1} 次）...`);
            showToast('AI 响应中断，自动重试中...', 'warning');
            break;

        case 'layout_done':
            layoutText = ev.text || '';
            document.getElementById('output-text').value = layoutText;
            break;

        case 'done': {
            setProgressBar(100);
            const doneText = document.getElementById('output-text').value || layoutText || '';
            const doneLabel = (ev.mode === 'enhanced_imitate') ? '仿写完成' : (ev.mode === 'imitate' ? '仿写完成' : '润色完成');
            setStageIndicator(doneLabel + ' ✓');
            const doneCount = countWords(doneText);
            document.getElementById('output-info').textContent = `${doneLabel} · 共 ${doneCount} 字`;
            setTimeout(() => document.getElementById('stage-indicator').style.display = 'none', 2000);
            showToast(doneLabel + '！', 'success');
            checkShortOutput(doneText);
            if (ev.mode === 'imitate' || ev.mode === 'enhanced_imitate') setImitateUI(false); else setPolishUI(false);
            document.getElementById('retry-btn').style.display = 'none';
            const cantReduceBtn = document.getElementById('btn-cant-reduce');
            const showEnhance = !ev.mode || ev.mode === 'polish';
            if (cantReduceBtn) cantReduceBtn.style.display = showEnhance ? '' : 'none';
            const nudge = document.getElementById('enhance-nudge');
            if (nudge) { if (showEnhance) nudge.classList.add('show'); else nudge.classList.remove('show'); }
            // 保存到本地历史
            const inputEl = (ev.mode === 'imitate' || ev.mode === 'enhanced_imitate')
                ? document.getElementById('imitate-news')
                : document.getElementById('input-text');
            const inputFull = inputEl ? inputEl.value : '';
            saveLocalHistory({
                session_id: currentSessionId || ('local_' + Date.now()),
                created_at: new Date().toISOString(),
                status: 'completed',
                mode: ev.mode || currentMode,
                preview: inputFull.slice(0, 50).replace(/\s+/g, ' '),
                input_text: inputFull,
                input_char_count: countWords(inputFull),
                result_text: doneText,
                char_count: countWords(doneText)
            });
            break;
        }

        case 'retry':
            document.getElementById('output-text').value = '';
            outputSegments = {};
            setStageIndicator('AI 未返回内容，正在自动重试...');
            break;

        case 'error':
            if (ev.index !== undefined) {
                setStageIndicator(`第 ${ev.index + 1} 段处理失败`);
                showToast(ev.message || '处理失败，可点击重试', 'error');
                document.getElementById('retry-btn').style.display = '';
            } else {
                showToast(ev.message || '处理失败', 'error');
                const errOutput = document.getElementById('output-text').value || twBuffer || '';
                if (errOutput.replace(/\s/g, '').length > 0) checkShortOutput(errOutput);
            }
            if (currentMode === 'imitate') setImitateUI(false); else setPolishUI(false);
            break;
    }
}

// ===== 重试 =====
async function retrySession() {
    if (!currentSessionId || !authToken) return;
    document.getElementById('retry-btn').style.display = 'none';
    if (currentMode === 'imitate') setImitateUI(true); else setPolishUI(true);
    setStageIndicator('正在重试...');

    try {
        const resp = await fetch(`/api/process/${currentSessionId}/retry`, {
            method: 'POST',
            headers: { 'Authorization': 'Bearer ' + authToken }
        });
        if (!resp.ok) {
            showToast('重试失败', 'error');
            if (currentMode === 'imitate') setImitateUI(false); else setPolishUI(false);
            return;
        }
        await listenToSession(currentSessionId);
    } catch (e) {
        showToast('网络错误', 'error');
        if (currentMode === 'imitate') setImitateUI(false); else setPolishUI(false);
    }
}

// ===== 渲染输出 =====
function buildFinalText() {
    const keys = Object.keys(outputSegments).map(Number).sort((a, b) => a - b);
    return keys.map(k => (outputSegments[k] || '').trim()).filter(t => t).join('\n\n');
}

function renderOutput() {
    document.getElementById('output-text').value = buildFinalText();
}

function renderOutputWithCursor() {
    const base = buildFinalText();
    const cursor = currentChunk.text;
    const combined = base ? base + '\n\n' + cursor : cursor;
    document.getElementById('output-text').value = combined + '▌';
}

// ===== UI 辅助 =====
function resetOutputUI() {
    twReset();
    outputSegments = {};
    currentChunk = { index: -1, stage: '', text: '' };
    layoutText = '';
    document.getElementById('output-text').value = '';
    document.getElementById('output-text').placeholder = '处理中，请稍候...';
    document.getElementById('output-info').textContent = '';
    document.getElementById('progress-wrap').style.display = 'none';
    document.getElementById('stage-indicator').style.display = 'none';
    document.getElementById('retry-btn').style.display = 'none';
    setProgressBar(0);
}

function setPolishUI(processing) {
    isProcessing = processing;
    const btn = document.getElementById('btn-polish');
    btn.disabled = processing;
    btn.innerHTML = processing
        ? '<span class="loading-spinner"></span> 处理中...'
        : '提交润色';
    const dots = document.getElementById('processing-dots');
    if (dots) dots.classList.toggle('active', processing);
    const stopBtn = document.getElementById('stop-btn');
    if (stopBtn) stopBtn.style.display = processing ? '' : 'none';
    if (processing) startCooking(); else stopCooking();
}

function setImitateUI(processing) {
    isProcessing = processing;
    const btn = document.getElementById('btn-imitate');
    if (btn) {
        btn.disabled = processing;
        btn.innerHTML = processing
            ? '<span class="loading-spinner"></span> 处理中...'
            : '提交仿写';
    }
    const dots = document.getElementById('processing-dots');
    if (dots) dots.classList.toggle('active', processing);
    const stopBtn = document.getElementById('stop-btn');
    if (stopBtn) stopBtn.style.display = processing ? '' : 'none';
    if (processing) startCooking(); else stopCooking();
}

function setProgressBar(percent) {
    document.getElementById('progress-bar').style.width = percent + '%';
    document.getElementById('progress-label').textContent = Math.round(percent) + '%';
}

function setStageIndicator(text) {
    const el = document.getElementById('stage-indicator');
    el.style.display = '';
    el.textContent = text;
}

// ===== 页面恢复 =====
async function tryResumeSession() {
    if (!currentSessionId || !authToken) return;
    try {
        const resp = await fetch(`/api/sessions/${currentSessionId}/result`, {
            headers: { 'Authorization': 'Bearer ' + authToken }
        });
        if (!resp.ok) { currentSessionId = null; localStorage.removeItem('current_session_id'); return; }
        const data = await resp.json();
        if (data.status === 'completed' && data.text) {
            document.getElementById('output-text').value = data.text;
            document.getElementById('output-info').textContent = `历史结果 · 共 ${data.text.length} 字`;
            showToast('已恢复上次处理结果', 'success');
        } else if (data.status === 'processing' || data.status === 'pending') {
            showToast('检测到未完成的任务，正在重新连接...', 'warning');
            setPolishUI(true);
            const resumeTimeout = setTimeout(() => {
                if (isProcessing) {
                    if (sseController) { sseController.abort(); sseController = null; }
                    setPolishUI(false);
                    currentSessionId = null;
                    localStorage.removeItem('current_session_id');
                    showToast('任务已中断，请重新提交', 'warning');
                }
            }, 15000);
            await listenToSession(currentSessionId);
            clearTimeout(resumeTimeout);
        } else {
            currentSessionId = null;
            localStorage.removeItem('current_session_id');
        }
    } catch (e) {}
}

// ===== 历史记录 =====
let historyVisible = false;

// ===== 本地历史记录（localStorage） =====
const LOCAL_HISTORY_KEY = 'runmo_history';
const LOCAL_HISTORY_MAX = 40;

function saveLocalHistory(entry) {
    try {
        const list = JSON.parse(localStorage.getItem(LOCAL_HISTORY_KEY) || '[]');
        const idx = list.findIndex(e => e.session_id === entry.session_id);
        if (idx >= 0) list.splice(idx, 1);
        list.unshift(entry);
        if (list.length > LOCAL_HISTORY_MAX) list.length = LOCAL_HISTORY_MAX;
        localStorage.setItem(LOCAL_HISTORY_KEY, JSON.stringify(list));
    } catch (e) {}
}

function getLocalHistory() {
    try { return JSON.parse(localStorage.getItem(LOCAL_HISTORY_KEY) || '[]'); }
    catch (e) { return []; }
}

function toggleHistory() {
    const panel = document.getElementById('history-panel');
    historyVisible = !historyVisible;
    panel.style.display = historyVisible ? 'block' : 'none';
    if (historyVisible) loadHistory();
}

function loadHistory() {
    renderHistory(getLocalHistory());
}

function renderHistory(sessions) {
    const list = document.getElementById('history-list');
    if (!sessions.length) { list.innerHTML = '<span style="color:#94a3b8;font-size:13px;">暂无历史记录</span>'; return; }
    list.innerHTML = sessions.map(s => {
        const date = new Date(s.created_at).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
        const statusColor = { completed: '#10b981', failed: '#ef4444' };
        const statusLabel = { completed: '✓ 完成', failed: '✗ 失败' };
        const modeLabel = (s.mode === 'polish') ? '润色' : '仿写';
        const st = s.status || 'completed';
        return `<div class="history-item">
            <div class="history-item-meta">
                <span style="color:${statusColor[st] || '#94a3b8'};font-weight:600;">${statusLabel[st] || st}</span>
                <span style="color:#64748b;font-size:11px;">${modeLabel}</span>
                <span style="color:#94a3b8;">${date}</span>
                ${s.char_count ? `<span style="color:#94a3b8;">${s.char_count} 字</span>` : ''}
            </div>
            ${s.preview ? `<div style="color:#475569;font-size:11px;margin-top:3px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:100%;">${s.preview}</div>` : ''}
            ${st === 'completed' && s.result_text
                ? `<button class="btn btn-secondary" style="margin-top:6px;padding:4px 12px;font-size:12px;" onclick="restoreSession('${s.session_id}')">恢复结果</button>`
                : st === 'failed'
                ? `<button class="btn btn-secondary" style="margin-top:6px;padding:4px 12px;font-size:12px;" onclick="retryFromHistory('${s.session_id}')">重试</button>`
                : ''}
        </div>`;
    }).join('');
}

// ===== 清除全部历史 =====
function clearAllHistory() {
    const list = getLocalHistory();
    if (!list.length) { showToast('暂无历史记录', 'warning'); return; }
    if (!confirm(`确定要清除全部 ${list.length} 条历史记录吗？此操作不可恢复。`)) return;
    localStorage.removeItem(LOCAL_HISTORY_KEY);
    renderHistory([]);
    showToast('历史记录已清除', 'success');
}

// ===== 导出历史记录（Excel XLS 格式）=====
function exportHistoryCSV() {
    const list = getLocalHistory();
    if (!list.length) { showToast('暂无历史记录可导出', 'warning'); return; }

    const esc = s => String(s ?? '')
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

    const thStyle = 'text-align:center;vertical-align:middle;background:#e8e8f0;border:1px solid #aaa;padding:8px 12px;font-size:13px;font-weight:bold;white-space:nowrap;';
    const tdStyle = 'text-align:center;vertical-align:middle;border:1px solid #d0d0d0;padding:6px 10px;font-size:12px;white-space:nowrap;';
    const tdLStyle = 'text-align:center;vertical-align:middle;border:1px solid #d0d0d0;padding:6px 10px;font-size:12px;word-wrap:break-word;white-space:pre-wrap;';

    const th  = t  => `<th style="${thStyle}">${t}</th>`;
    const td  = v  => `<td style="${tdStyle}">${esc(String(v ?? ''))}</td>`;
    const tdL = v  => `<td style="${tdLStyle}">${esc(String(v ?? ''))}</td>`;

    const headerRow = `<tr>${['序号','时间','原文','原文字数','处理结果','处理结果字数'].map(th).join('')}</tr>`;

    const dataRows = list.map((s, i) => {
        const dt = s.created_at
            ? new Date(s.created_at).toLocaleString('zh-CN', {year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit'})
            : '';
        const inputText   = s.input_text || s.preview || '';
        const inputCount  = s.input_char_count || countWords(inputText);
        const resultText  = s.result_text || '';
        const resultCount = s.char_count || countWords(resultText);
        return `<tr style="height:36pt;mso-height-source:userset;">${td(i+1)}${td(dt)}${tdL(inputText)}${td(inputCount)}${tdL(resultText)}${td(resultCount)}</tr>`;
    }).join('');

    const html = `<html xmlns:o="urn:schemas-microsoft-com:office:office"
 xmlns:x="urn:schemas-microsoft-com:office:excel"
 xmlns="http://www.w3.org/TR/REC-html40">
<head><meta charset="UTF-8">
<!--[if gte mso 9]><xml><x:ExcelWorkbook><x:ExcelWorksheets><x:ExcelWorksheet>
<x:Name>润墨历史记录</x:Name>
<x:WorksheetOptions><x:DisplayGridlines/></x:WorksheetOptions>
</x:ExcelWorksheet></x:ExcelWorksheets></x:ExcelWorkbook></xml><![endif]-->
</head>
<body>
<table style="border-collapse:collapse;">
  <colgroup>
    <col style="width:50px">
    <col style="width:165px">
    <col style="width:320px">
    <col style="width:80px">
    <col style="width:360px">
    <col style="width:100px">
  </colgroup>
  <thead>${headerRow}</thead>
  <tbody>${dataRows}</tbody>
</table>
</body></html>`;

    const blob = new Blob(['﻿' + html], { type: 'application/vnd.ms-excel;charset=utf-8' });
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement('a');
    a.href = url;
    a.download = `润墨历史记录_${new Date().toISOString().slice(0,10)}.xls`;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => { document.body.removeChild(a); URL.revokeObjectURL(url); }, 1000);
    showToast(`已导出 ${list.length} 条记录`, 'success');
}

function restoreSession(sessionId) {
    const entry = getLocalHistory().find(e => e.session_id === sessionId);
    if (entry && entry.result_text) {
        document.getElementById('output-text').value = entry.result_text;
        document.getElementById('output-info').textContent = `历史结果 · 共 ${entry.result_text.length} 字`;
        toggleHistory();
        showToast('历史结果已恢复', 'success');
    } else {
        showToast('本地记录不存在或已清除', 'error');
    }
}

async function retryFromHistory(sessionId) {
    currentSessionId = sessionId;
    localStorage.setItem('current_session_id', sessionId);
    toggleHistory();
    await retrySession();
}

// ===== 其他 =====
function showComingSoon(name) { showToast(`${name} 功能即将上线，敬请期待！`, 'warning'); }
function switchTab(tab) {
    document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
    event.target.classList.add('active');
    if (tab !== 'polish') showComingSoon(event.target.textContent);
}

// ===== 多开模式 =====
let pwIsActive = false;
let pwWinSeq = 0;

function toggleMultiWindow() {
    if (!pwIsActive) enterMultiWindowMode();
    else exitMultiWindowMode();
}

function enterMultiWindowMode() {
    pwIsActive = true;
    document.getElementById('main-single-area').style.display = 'none';
    document.getElementById('pw-area').style.display = 'flex';
    document.getElementById('pw-action-bar').style.display = 'flex';
    const btn = document.getElementById('btn-multi-window');
    btn.style.background = 'rgba(167,139,250,.18)';
    // 默认开启两个窗口
    if (document.getElementById('pw-area').children.length === 0) {
        addPWWindow();
        addPWWindow();
    }
}

function exitMultiWindowMode() {
    pwIsActive = false;
    document.getElementById('main-single-area').style.display = '';
    document.getElementById('pw-area').style.display = 'none';
    document.getElementById('pw-action-bar').style.display = 'none';
    const btn = document.getElementById('btn-multi-window');
    btn.style.background = '';
}

function addPWWindow() {
    const pwArea = document.getElementById('pw-area');
    if (pwArea.children.length >= 4) {
        showToast('最多同时开启 4 个窗口');
        return;
    }
    pwWinSeq++;
    const id = 'pw-win-' + pwWinSeq;
    const n = pwArea.children.length + 1;

    const div = document.createElement('div');
    div.id = id;
    div.className = 'pw-window glass';
    div.style.cssText = 'flex:1;min-width:240px;opacity:0;transition:flex .35s ease,opacity .35s ease;';
    div.innerHTML = `
      <div class="pw-header">
        <div style="display:flex;align-items:center;gap:8px;">
          <div class="panel-dot"></div>
          <span class="pw-title" style="font-size:13px;font-weight:600;color:var(--text-1);">窗口 ${n}</span>
        </div>
        <div style="display:flex;align-items:center;gap:6px;">
          <div class="mode-toggle" style="transform:scale(.88);transform-origin:right center;">
            <button class="mode-btn active" onclick="pwSetMode(this)">快速降AI</button>
            <button class="mode-btn" onclick="pwSetMode(this)">强化降AI</button>
          </div>
          <button class="pw-close-btn" onclick="removePWWindow('${id}')" title="关闭此窗口">✕</button>
        </div>
      </div>
      <div class="pw-input-area">
        <textarea id="${id}-in" class="text-area input-area" placeholder="粘贴需要处理的文章…" style="min-height:130px;flex:1;resize:none;" oninput="pwUpdateInCount('${id}')"></textarea>
        <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
          <span style="font-size:11px;color:var(--text-3);white-space:nowrap;">风格</span>
          <div class="mode-toggle pw-style-toggle" style="transform:scale(.88);transform-origin:left center;">
            <button class="mode-btn active" onclick="pwSetStyle(this)">严谨</button>
            <button class="mode-btn" onclick="pwSetStyle(this)">不变</button>
            <button class="mode-btn" onclick="pwSetStyle(this)">情感</button>
          </div>
          <span id="${id}-in-cnt" style="font-size:11px;color:var(--text-3);margin-left:auto;">0 字</span>
        </div>
        <div style="display:flex;justify-content:center;align-items:center;gap:8px;padding:2px 0 4px;">
          <button class="pw-submit-btn" onclick="pwSubmitWindow('${id}')" style="display:inline-flex;align-items:center;gap:6px;padding:9px 28px;font-size:13px;font-weight:600;border-radius:999px;border:1px solid var(--primary-s);background:var(--primary-s);color:#fff;cursor:pointer;letter-spacing:.3px;box-shadow:0 2px 12px rgba(var(--glow),.28);transition:opacity .2s,transform .15s;" onmouseover="this.style.opacity='.85';this.style.transform='translateY(-1px)'" onmouseout="this.style.opacity='1';this.style.transform=''">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m22 2-7 20-4-9-9-4Z"/><path d="M22 2 11 13"/></svg>
            提交润色
          </button>
          <button class="pw-stop-btn" onclick="pwStopWindow('${id}')" style="display:none;align-items:center;gap:5px;padding:9px 20px;font-size:13px;font-weight:600;border-radius:999px;border:1px solid rgba(239,68,68,.5);background:rgba(239,68,68,.12);color:#f87171;cursor:pointer;transition:opacity .2s;">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><rect x="6" y="6" width="12" height="12" rx="1"/></svg>
            停止
          </button>
          <span class="pw-status" style="display:none;font-size:11px;color:var(--text-3);"></span>
        </div>
      </div>
      <div class="pw-output-area">
        <div style="font-size:11px;color:var(--text-3);margin-bottom:5px;">处理结果</div>
        <textarea id="${id}-out" class="text-area output-area" readonly placeholder="处理结果将在此显示…" style="min-height:130px;flex:1;resize:none;"></textarea>
        <div style="display:flex;justify-content:space-between;align-items:center;padding-top:6px;">
          <span id="${id}-out-cnt" style="font-size:11px;color:var(--text-3);">结果：0 字</span>
          <div style="display:flex;gap:5px;">
          <button class="btn btn-secondary" style="font-size:11px;" onclick="pwCopy('${id}')">
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg>
            复制
          </button>
          <button class="btn btn-secondary" style="font-size:11px;" onclick="pwClear('${id}')">
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/></svg>
            清空
          </button>
          </div>
        </div>
      </div>`;

    pwArea.appendChild(div);
    // 淡入动画
    requestAnimationFrame(() => requestAnimationFrame(() => {
        div.style.opacity = '1';
    }));
    updatePWCloseButtons();
}

function removePWWindow(id) {
    const pwArea = document.getElementById('pw-area');
    if (pwArea.children.length <= 1) return;
    const el = document.getElementById(id);
    if (!el) return;
    el.style.flex = '0';
    el.style.opacity = '0';
    el.style.minWidth = '0';
    setTimeout(() => {
        el.remove();
        updatePWCloseButtons();
        updatePWWindowNumbers();
    }, 380);
}

function updatePWCloseButtons() {
    const pwArea = document.getElementById('pw-area');
    const wins = pwArea.querySelectorAll('.pw-window');
    wins.forEach(w => {
        const btn = w.querySelector('.pw-close-btn');
        if (btn) btn.style.display = wins.length <= 1 ? 'none' : '';
    });
}

function updatePWWindowNumbers() {
    const pwArea = document.getElementById('pw-area');
    const wins = pwArea.querySelectorAll('.pw-window');
    wins.forEach((w, i) => {
        const t = w.querySelector('.pw-title');
        if (t) t.textContent = `窗口 ${i + 1}`;
    });
}

function pwSetMode(btn) {
    const toggle = btn.closest('.mode-toggle');
    toggle.querySelectorAll('.mode-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
}

function pwSetStyle(btn) {
    const toggle = btn.closest('.mode-toggle');
    toggle.querySelectorAll('.mode-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
}

function pwUpdateInCount(id) {
    const ta  = document.getElementById(id + '-in');
    const cnt = document.getElementById(id + '-in-cnt');
    if (ta && cnt) cnt.textContent = countWords(ta.value) + ' 字';
}

function pwUpdateOutCount(id) {
    const ta  = document.getElementById(id + '-out');
    const cnt = document.getElementById(id + '-out-cnt');
    if (ta && cnt) cnt.textContent = '结果：' + countWords(ta.value) + ' 字';
}

// ===== 多开：每窗口状态 =====
const pwState = {}; // {[id]: {processing, controller, sessionId}}

function pwSubmitWindow(id) {
    if (!authToken) { showCardAuthOverlay(); return; }
    const state = pwState[id];
    if (state && state.processing) return;

    const inEl  = document.getElementById(id + '-in');
    const outEl = document.getElementById(id + '-out');
    if (!inEl || !outEl) return;

    const text = inEl.value.trim();
    if (!text) { showToast('请先输入需要处理的文章', 'warning'); return; }
    if (text.length > 3500) { showToast('文字最多 3500 字', 'warning'); return; }

    // 从窗口内的风格按钮取 style
    const win = document.getElementById(id);
    const styleBtns = win.querySelectorAll('.pw-style-toggle .mode-btn');
    let style = 'default';
    styleBtns.forEach(b => {
        if (b.classList.contains('active')) {
            if (b.textContent.includes('不变')) style = 'preserve';
            else if (b.textContent.includes('情感')) style = 'emotional';
            else style = 'default';
        }
    });

    pwState[id] = { processing: true, controller: null, sessionId: null };
    pwSetWindowUI(id, 'processing');
    outEl.value = '';

    fetch('/api/process/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + authToken },
        body: JSON.stringify({ text, style, bypass: false })
    }).then(resp => resp.json().then(data => ({ resp, data }))).then(({ resp, data }) => {
        if (!resp.ok) {
            showToast(data.error || '启动失败', 'error');
            pwSetWindowUI(id, 'idle'); return;
        }
        // 更新剩余用量
        if (currentCard) {
            if (data.card_type === 'chars' || currentCard.card_type === 'chars') {
                currentCard.card_type = 'chars';
                if (data.remaining_chars !== undefined) currentCard.remaining_chars = data.remaining_chars;
            } else if (data.remaining_uses !== undefined) {
                currentCard.remaining_uses = data.remaining_uses;
            }
            const remEl = document.getElementById('user-remaining');
            if (remEl) remEl.textContent = formatCredit(currentCard);
        }
        pwState[id].sessionId = data.sessionId;
        pwListenToSession(id, data.sessionId, outEl);
    }).catch(() => {
        showToast('网络错误，请稍后重试', 'error');
        pwSetWindowUI(id, 'idle');
    });
}

async function pwListenToSession(id, sessionId, outEl) {
    const controller = new AbortController();
    if (pwState[id]) pwState[id].controller = controller;
    let layoutText = '';

    try {
        const resp = await fetch(`/api/process/${sessionId}/events`, {
            headers: { 'Authorization': 'Bearer ' + authToken },
            signal: controller.signal
        });
        if (!resp.ok) { showToast('连接失败', 'error'); pwSetWindowUI(id, 'idle'); return; }

        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n'); buffer = lines.pop();
            for (const line of lines) {
                if (!line.startsWith('data:')) continue;
                try {
                    const ev = JSON.parse(line.slice(5).trim());
                    switch (ev.type) {
                        case 'chunk':
                            outEl.value += ev.delta;
                            outEl.scrollTop = outEl.scrollHeight;
                            break;
                        case 'layout_chunk':
                            layoutText += ev.delta || '';
                            break;
                        case 'layout_done':
                            layoutText = ev.text || '';
                            outEl.value = layoutText;
                            break;
                        case 'uses_updated':
                            if (currentCard) {
                                if (ev.card_type === 'chars') {
                                    currentCard.card_type = 'chars';
                                    if (ev.remaining_chars !== undefined) currentCard.remaining_chars = ev.remaining_chars;
                                } else {
                                    if (ev.remaining_uses !== undefined) currentCard.remaining_uses = ev.remaining_uses;
                                }
                                const remEl = document.getElementById('user-remaining');
                                if (remEl) remEl.textContent = formatCredit(currentCard);
                            }
                            break;
                        case 'done': {
                            if (layoutText) outEl.value = layoutText;
                            const doneText  = outEl.value;
                            const pwInEl    = document.getElementById(id + '-in');
                            const inputFull = pwInEl ? pwInEl.value : '';
                            saveLocalHistory({
                                session_id:       pwState[id]?.sessionId || ('pw_' + Date.now()),
                                created_at:       new Date().toISOString(),
                                status:           'completed',
                                mode:             'polish',
                                preview:          inputFull.slice(0, 50).replace(/\s+/g, ' '),
                                input_text:       inputFull,
                                input_char_count: countWords(inputFull),
                                result_text:      doneText,
                                char_count:       countWords(doneText)
                            });
                            pwUpdateOutCount(id);
                            pwSetWindowUI(id, 'done');
                            break;
                        }
                        case 'error':
                            showToast(ev.message || '处理失败', 'error');
                            pwSetWindowUI(id, 'idle');
                            break;
                    }
                } catch (e) {}
            }
        }
    } catch (e) {
        if (e.name === 'AbortError') return;
        showToast('连接中断，请重新提交', 'warning');
        pwSetWindowUI(id, 'idle');
    }
}

function pwStopWindow(id) {
    const state = pwState[id];
    if (!state) return;
    if (state.controller) { state.controller.abort(); state.controller = null; }
    pwSetWindowUI(id, 'idle');
    showToast('已停止', 'warning');
}

function pwSetWindowUI(id, mode) {
    const win = document.getElementById(id);
    if (!win) return;
    if (pwState[id]) pwState[id].processing = (mode === 'processing');

    const submitBtn = win.querySelector('.pw-submit-btn');
    const stopBtn   = win.querySelector('.pw-stop-btn');
    const statusEl  = win.querySelector('.pw-status');

    if (mode === 'processing') {
        if (submitBtn) submitBtn.style.display = 'none';
        if (stopBtn)   { stopBtn.style.display = 'inline-flex'; }
        if (statusEl)  { statusEl.textContent = '处理中…'; statusEl.style.color = 'var(--text-3)'; statusEl.style.display = ''; }
    } else if (mode === 'done') {
        if (submitBtn) submitBtn.style.display = 'inline-flex';
        if (stopBtn)   stopBtn.style.display = 'none';
        if (statusEl)  { statusEl.textContent = '✓ 完成'; statusEl.style.color = '#4ade80'; statusEl.style.display = ''; }
        setTimeout(() => { if (statusEl) statusEl.style.display = 'none'; }, 3000);
    } else {
        if (submitBtn) submitBtn.style.display = 'inline-flex';
        if (stopBtn)   stopBtn.style.display = 'none';
        if (statusEl)  statusEl.style.display = 'none';
    }
}

function pwSubmitAll() {
    if (!authToken) { showCardAuthOverlay(); return; }
    const wins = document.getElementById('pw-area').querySelectorAll('.pw-window');
    let started = 0;
    wins.forEach(w => {
        const id = w.id;
        if (pwState[id] && pwState[id].processing) return;
        const text = document.getElementById(id + '-in')?.value.trim();
        if (!text) return;
        pwSubmitWindow(id);
        started++;
    });
    if (started === 0) showToast('所有窗口均无内容或正在处理中', 'warning');
}

function pwCopy(id) {
    const out = document.getElementById(id + '-out');
    if (!out || !out.value.trim()) { showToast('暂无内容可复制'); return; }
    if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(out.value).then(() => showToast('已复制到剪贴板', 'success'));
    } else {
        out.select();
        document.execCommand('copy');
        window.getSelection && window.getSelection().removeAllRanges();
        showToast('已复制到剪贴板', 'success');
    }
}

function pwClear(id) {
    const inEl = document.getElementById(id + '-in');
    const outEl = document.getElementById(id + '-out');
    if (inEl) inEl.value = '';
    if (outEl) outEl.value = '';
    pwUpdateInCount(id);
    pwUpdateOutCount(id);
}

// ===== Ctrl+Enter 快捷键 =====
document.addEventListener('keydown', function(e) {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
        if (pwIsActive) {
            e.preventDefault();
            pwSubmitAll();
        }
    }
});

