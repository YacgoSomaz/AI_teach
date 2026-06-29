require('dotenv').config();
const express = require('express');
const cors = require('cors');
const rateLimit = require('express-rate-limit');
const jwt = require('jsonwebtoken');
const crypto = require('crypto');
const path = require('path');
const axios = require('axios');

const bcrypt = require('bcryptjs');

const db = require('./database');
const authMiddleware = require('./middleware/auth');
const { sendVerifyCode, sendVerificationEmail, sendPasswordResetEmail } = require('./mailer');
const { processSession, processImitation, processImitationFree, processEnhancedImitation, countTextLength, refundCreditOnce } = require('./service');
const { getTodayUsage } = require('./usage');

const app = express();
const PORT = process.env.PORT || 3000;
const ADMIN_SECRET = process.env.ADMIN_SECRET || 'admin123';

app.set('trust proxy', 1); // nginx 反向代理后需要信任 X-Forwarded-For
app.use(cors());
app.use(express.json({ limit: '10mb' }));
app.use(express.static(path.join(__dirname, 'public')));

const apiLimiter = rateLimit({ windowMs: 15 * 60 * 1000, max: 200, message: { error: '请求过于频繁' } });
app.use('/api/', apiLimiter);

// ============ 文章语料库 · 输出缓存（防循环润色） ============

// outputCache: card_id(number) → string[] (最近15条输出文本hash)
const outputCache = new Map();
const OUTPUT_CACHE_SIZE = 15;

function normalizeText(text) {
    return text.replace(/\s+/g, '').toLowerCase();
}

function hashText(text) {
    return crypto.createHash('sha256').update(normalizeText(text)).digest('hex');
}

function isRecycledOutput(cardId, inputText) {
    const hashes = outputCache.get(cardId);
    if (!hashes || hashes.length === 0) return false;
    const h = hashText(inputText);
    return hashes.includes(h);
}

function addToOutputCache(cardId, outputText) {
    if (!outputText || !outputText.trim()) return;
    let hashes = outputCache.get(cardId) || [];
    const h = hashText(outputText);
    hashes = hashes.filter(x => x !== h); // 去重
    hashes.unshift(h);
    if (hashes.length > OUTPUT_CACHE_SIZE) hashes = hashes.slice(0, OUTPUT_CACHE_SIZE);
    outputCache.set(cardId, hashes);
}

// ============ 并发管理器 ============

class ConcurrencyManager {
    constructor(max = 3) {
        this.max = max;
        this.active = new Set();
        this.queue = [];
    }
    // signal: 可选 AbortSignal，取消时从队列移除并 reject
    // onQueued: 入队瞬间同步回调(position)，用于通知前端排队位置
    async acquire(sessionId, signal, onQueued) {
        if (this.active.size < this.max) { this.active.add(sessionId); return; }
        await new Promise((resolve, reject) => {
            const entry = { sessionId, resolve };
            this.queue.push(entry);
            if (onQueued) onQueued(this.queue.length); // 入队时立即通知位置
            if (signal) {
                signal.addEventListener('abort', () => {
                    const idx = this.queue.findIndex(q => q.sessionId === sessionId);
                    if (idx !== -1) this.queue.splice(idx, 1);
                    const err = new Error('Cancelled while queued');
                    err.name = 'AbortError';
                    reject(err);
                }, { once: true });
            }
        });
    }
    release(sessionId) {
        if (!this.active.has(sessionId)) return; // 防止重复 release
        this.active.delete(sessionId);
        if (this.queue.length > 0) {
            const next = this.queue.shift();
            this.active.add(next.sessionId);
            next.resolve();
        }
    }
}
const concurrency = new ConcurrencyManager(15);

// 存储每个处理中会话的 AbortController，用于取消时立即中止 AI 调用
const sessionAborts = new Map();

// ============ SSE 事件总线 ============

const sessionBus = new Map();

function getSessionBus(sessionId) {
    if (!sessionBus.has(sessionId)) sessionBus.set(sessionId, { events: [], listeners: new Set() });
    return sessionBus.get(sessionId);
}

function emitEvent(sessionId, type, data) {
    const session = db.prepare('SELECT status, error_message FROM sessions WHERE session_id = ?').get(sessionId);
    const cancelled = session && (session.error_message === '用户已取消' || session.status === 'failed' && session.error_message === 'USER_CANCELLED');
    if (cancelled && !['error', 'uses_updated'].includes(type)) return;
    const bus = getSessionBus(sessionId);
    const event = { type, ...data };
    bus.events.push(event);
    const line = `data: ${JSON.stringify(event)}\n\n`;
    for (const res of bus.listeners) {
        try {
            res.write(line);
            if (typeof res.flush === 'function') res.flush();
        } catch (e) {}
    }
    if (type === 'done' || (type === 'error' && data.index === undefined)) {
        setTimeout(() => sessionBus.delete(sessionId), 60000);
    }
}

// ============ FREE_MODE 初始化 + 邮箱用户系统卡 ============

// 确保 FREE 系统卡存在（邮箱登录用户在免费阶段使用此卡创建会话）
let _freeCardRow = db.prepare("SELECT * FROM cards WHERE code = 'FREE'").get();
if (!_freeCardRow) {
    db.prepare("INSERT INTO cards (code, remaining_uses, total_uses, can_imitate, card_type, remaining_chars, total_chars) VALUES ('FREE', 0, 0, 1, 'chars', 1000000000, 1000000000)").run();
    _freeCardRow = db.prepare("SELECT * FROM cards WHERE code = 'FREE'").get();
}
const FREE_CARD_ID = _freeCardRow.id;

let freeToken = null;
if (process.env.FREE_MODE === 'true') {
    freeToken = jwt.sign({ card_id: FREE_CARD_ID }, process.env.JWT_SECRET, { expiresIn: '100y' });
    console.log('FREE_MODE enabled, free card id:', FREE_CARD_ID);
}

// 判断是否为邮箱用户 token
function isUserToken(decoded) { return decoded && decoded.type === 'user'; }
// 邮箱用户取得系统卡（免费阶段）
function getUserCard() { return db.prepare('SELECT * FROM cards WHERE id = ?').get(FREE_CARD_ID); }

app.get('/api/free-token', (req, res) => {
    if (process.env.FREE_MODE !== 'true' || !freeToken) return res.status(404).json({ error: 'not free mode' });
    res.json({ token: freeToken });
});

// ============ 卡密激活（前端登录入口）============

app.post('/api/activate', (req, res) => {
    try {
        const { code } = req.body;
        if (!code || !code.trim()) return res.status(400).json({ error: '请输入卡密' });
        const card = db.prepare(
            "SELECT * FROM cards WHERE code = ? AND (expires_at IS NULL OR datetime(expires_at) > datetime('now'))"
        ).get(code.trim().toUpperCase());
        if (!card) return res.status(404).json({ error: '卡密无效或已过期' });
        if (card.card_type === 'chars' && (card.remaining_chars || 0) <= 0)
            return res.status(403).json({ error: '该卡密字数已用完，请联系管理员' });
        if (card.card_type !== 'chars' && card.remaining_uses <= 0)
            return res.status(403).json({ error: '该卡密次数已用完，请联系管理员' });
        // 记录首次使用时间
        if (!card.first_used_at) {
            db.prepare('UPDATE cards SET first_used_at = CURRENT_TIMESTAMP WHERE id = ?').run(card.id);
        }
        const token = jwt.sign({ card_id: card.id }, process.env.JWT_SECRET, { expiresIn: '100y' });
        res.json({ token });
    } catch (err) {
        res.status(500).json({ error: '激活失败，请稍后重试' });
    }
});

// ============ 卡密工具 ============

function generateCardCode() {
    const chars = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';
    const seg = () => Array.from({ length: 4 }, () => chars[Math.floor(Math.random() * chars.length)]).join('');
    return `${seg()}-${seg()}-${seg()}-${seg()}`;
}

// ============ 用户信息 ============

app.get('/api/user/info', authMiddleware, (req, res) => {
    try {
        if (isUserToken(req.user)) {
            // 邮箱账号用户：返回用户信息 + 免费标识
            const user = db.prepare('SELECT id, email, created_at FROM users WHERE id = ?').get(req.user.userId);
            if (!user) return res.status(404).json({ error: '用户不存在' });
            return res.json({ userMode: true, email: user.email, userId: user.id });
        }
        const card = db.prepare('SELECT id, code, remaining_uses, total_uses, can_imitate, card_type, remaining_chars, total_chars FROM cards WHERE id = ?').get(req.user.card_id);
        if (!card) return res.status(404).json({ error: '卡密不存在' });
        res.json(card);
    } catch (err) { res.status(500).json({ error: '获取信息失败' }); }
});

// ============ 开始润色会话 ============

app.post('/api/process/start', authMiddleware, (req, res) => {
    try {
        const { text, style, bypass } = req.body;
        if (!text || !text.trim()) return res.status(400).json({ error: '请输入需要处理的文本' });
        if (text.length > 3500) return res.status(400).json({ error: '单次最多处理 3500 字' });

        // 邮箱用户（免费阶段）使用系统 FREE 卡，跳过信用检查
        const card = isUserToken(req.user)
            ? getUserCard()
            : db.prepare('SELECT id, remaining_uses, card_type, remaining_chars FROM cards WHERE id = ?').get(req.user.card_id);
        if (!card) return res.status(404).json({ error: '账户信息不存在' });
        if (!isUserToken(req.user)) {
            if (card.card_type === 'chars') {
                if ((card.remaining_chars || 0) <= 0) return res.status(403).json({ error: '字数余额不足，请联系管理员充值' });
            } else {
                if (card.remaining_uses <= 0) return res.status(403).json({ error: '次数已用完，请联系管理员获取新卡密' });
            }
        }

        // 只创建会话，不扣次数（processSession 里扣，失败自动退回）
        const sessionId = crypto.randomUUID();
        const polishStyle = ['default', 'preserve', 'emotional'].includes(style) ? style : 'default';
        const bypassFlag = bypass ? '1' : '0';
        const trimmedText = text.trim();
        const sessionUserId = isUserToken(req.user) ? (req.user.userId || null) : null;
        db.prepare("INSERT INTO sessions (session_id, card_id, user_id, original_text, reference_text, status) VALUES (?, ?, ?, ?, ?, 'pending')")
            .run(sessionId, card.id, sessionUserId, trimmedText, `${polishStyle}:${bypassFlag}`);

        // 语料库：仅收录未被循环润色的原文
        const recycled = isRecycledOutput(card.id, trimmedText);
        if (!recycled) {
            try {
                const cardCode = isUserToken(req.user)
                    ? (req.user.email || `user:${req.user.userId}`)
                    : (db.prepare('SELECT code FROM cards WHERE id = ?').get(card.id)?.code || String(card.id));
                const charCount = countTextLength(trimmedText);
                const textHash = hashText(trimmedText);
                // 相同 hash 不重复存（去重）
                const exists = db.prepare('SELECT id FROM article_corpus WHERE text_hash = ?').get(textHash);
                if (!exists) {
                    db.prepare('INSERT INTO article_corpus (card_code, char_count, style, original_text, text_hash) VALUES (?, ?, ?, ?, ?)')
                        .run(cardCode, charCount, polishStyle, trimmedText, textHash);
                }
            } catch (e) {
                console.error('Corpus save error:', e.message);
            }
        }

        res.json({ sessionId });

        setImmediate(async () => {
            const cardIdForCache = card.id;
            const baseEmit = (type, data) => emitEvent(sessionId, type, data);
            const emit = (type, data) => {
                // 拦截 done 事件：把输出文本加入该卡密的输出缓存
                if (type === 'done' && data && data.outputText) {
                    addToOutputCache(cardIdForCache, data.outputText);
                }
                baseEmit(type, data);
            };
            const ac = new AbortController();
            sessionAborts.set(sessionId, ac);
            try {
                await concurrency.acquire(sessionId, ac.signal, pos => emit('queued', { position: pos }));
            } catch (e) {
                sessionAborts.delete(sessionId);
                return; // 排队中被取消，直接退出
            }
            try {
                const session = db.prepare('SELECT * FROM sessions WHERE session_id = ?').get(sessionId);
                if (ac.signal.aborted || session.status === 'failed') return;
                await processSession(session, db, emit, ac.signal);
            } catch (e) {
                if (e.name !== 'AbortError' && e.code !== 'ERR_CANCELED') {
                    emitEvent(sessionId, 'error', { message: e.message });
                }
            } finally {
                concurrency.release(sessionId);
                sessionAborts.delete(sessionId);
            }
        });
    } catch (err) {
        console.error('Process start error:', err.message);
        res.status(500).json({ error: '启动失败，请稍后重试' });
    }
});

// ============ SSE 事件流 ============

app.get('/api/process/:sessionId/events', authMiddleware, (req, res) => {
    const { sessionId } = req.params;
    const session = db.prepare('SELECT * FROM sessions WHERE session_id = ?').get(sessionId);
    const ownSession = isUserToken(req.user)
        ? (session && session.card_id === FREE_CARD_ID)
        : (session && session.card_id === req.user.card_id);
    if (!ownSession) return res.status(404).json({ error: '会话不存在' });

    res.setHeader('Content-Type', 'text/event-stream; charset=utf-8');
    res.setHeader('Cache-Control', 'no-cache, no-transform');
    res.setHeader('Connection', 'keep-alive');
    res.setHeader('X-Accel-Buffering', 'no');
    res.flushHeaders();
    res.write(': connected\n\n');

    const bus = getSessionBus(sessionId);
    for (const ev of bus.events) res.write(`data: ${JSON.stringify(ev)}\n\n`);
    if (typeof res.flush === 'function') res.flush();

    if (session.status === 'completed' || session.status === 'failed') { res.end(); return; }

    bus.listeners.add(res);
    const heartbeat = setInterval(() => {
        try {
            res.write(': ping\n\n');
            if (typeof res.flush === 'function') res.flush();
        } catch (e) {}
    }, 15000);
    req.on('close', () => {
        clearInterval(heartbeat);
        bus.listeners.delete(res);
    });
});

// ============ 取消处理中的会话 ============

app.post('/api/process/:sessionId/cancel', authMiddleware, (req, res) => {
    try {
        const { sessionId } = req.params;
        const session = db.prepare('SELECT * FROM sessions WHERE session_id = ?').get(sessionId);
        if (!session || session.card_id !== req.user.card_id) return res.status(404).json({ error: '会话不存在' });
        if (!['pending', 'processing'].includes(session.status)) return res.status(400).json({ error: '当前状态不可取消' });

        db.prepare("UPDATE sessions SET cancel_requested = 1, status = 'failed', error_message = '用户已取消' WHERE session_id = ?").run(sessionId);

        // 立即中止正在进行的 AI 调用，释放并发槽
        const ac = sessionAborts.get(sessionId);
        if (ac) ac.abort();
        // 暂停不退字数：用户主动取消不返还，防止取消后重复润色二次退款漏洞

        const card = db.prepare('SELECT remaining_uses, remaining_chars, card_type FROM cards WHERE id = ?').get(session.card_id);
        res.json({ ok: true, remaining_uses: card?.remaining_uses, remaining_chars: card?.remaining_chars, card_type: card?.card_type });
    } catch (err) { res.status(500).json({ error: '取消失败' }); }
});

// ============ 重试失败会话 ============

app.post('/api/process/:sessionId/retry', authMiddleware, (req, res) => {
    try {
        const { sessionId } = req.params;
        const session = db.prepare('SELECT * FROM sessions WHERE session_id = ?').get(sessionId);
        if (!session || session.card_id !== req.user.card_id) return res.status(404).json({ error: '会话不存在' });
        if (session.status !== 'failed') return res.status(400).json({ error: '只能重试失败的会话' });

        db.prepare("UPDATE sessions SET status = 'pending', error_message = NULL, cancel_requested = 0, credit_refunded = 0 WHERE session_id = ?").run(sessionId);
        db.prepare("UPDATE segments SET status = 'pending' WHERE session_id = ? AND status = 'failed'").run(sessionId);
        if (sessionBus.has(sessionId)) sessionBus.get(sessionId).events = [];

        res.json({ ok: true });

        setImmediate(async () => {
            const emit = (type, data) => emitEvent(sessionId, type, data);
            await concurrency.acquire(sessionId);
            try {
                const fresh = db.prepare('SELECT * FROM sessions WHERE session_id = ?').get(sessionId);
                if (fresh.mode === 'imitate') {
                    await processImitation(fresh, db, emit);
                } else if (fresh.mode === 'enhanced_imitate') {
                    await processEnhancedImitation(fresh, db, emit);
                } else {
                    await processSession(fresh, db, emit);
                }
            } catch (e) {
                emitEvent(sessionId, 'error', { message: e.message });
            } finally {
                concurrency.release(sessionId);
            }
        });
    } catch (err) { res.status(500).json({ error: '重试失败' }); }
});

// ============ 开始仿写会话 ============

app.post('/api/imitate/start', authMiddleware, (req, res) => {
    try {
        const { news_text, reference_text } = req.body;
        if (!news_text?.trim()) return res.status(400).json({ error: '请输入原新闻文章' });
        if (!reference_text?.trim()) return res.status(400).json({ error: '请输入参考风格文章' });
        if (news_text.length > 3500) return res.status(400).json({ error: '原新闻文章最多 3500 字' });
        if (reference_text.length > 3500) return res.status(400).json({ error: '参考风格文章最多 3500 字' });

        const card = db.prepare('SELECT id, remaining_uses, card_type, remaining_chars, can_imitate FROM cards WHERE id = ?').get(req.user.card_id);
        if (!card) return res.status(404).json({ error: '卡密不存在' });
        if (!card.can_imitate) return res.status(403).json({ error: '当前卡密无仿写权限，请联系管理员获取专属卡密' });
        if (card.card_type === 'chars') {
            if ((card.remaining_chars || 0) <= 0) return res.status(403).json({ error: '字数余额不足，请联系管理员充值' });
        } else {
            if (card.remaining_uses <= 0) return res.status(403).json({ error: '次数已用完，请联系管理员获取新卡密' });
        }

        const sessionId = crypto.randomUUID();
        db.prepare("INSERT INTO sessions (session_id, card_id, original_text, mode, reference_text, status) VALUES (?, ?, ?, 'imitate', ?, 'pending')")
            .run(sessionId, card.id, news_text.trim(), reference_text.trim());

        res.json({ sessionId });

        setImmediate(async () => {
            const emit = (type, data) => emitEvent(sessionId, type, data);
            const ac = new AbortController();
            sessionAborts.set(sessionId, ac);
            try {
                await concurrency.acquire(sessionId, ac.signal, pos => emit('queued', { position: pos }));
            } catch (e) {
                sessionAborts.delete(sessionId);
                return; // 排队中被取消，直接退出
            }
            try {
                const session = db.prepare('SELECT * FROM sessions WHERE session_id = ?').get(sessionId);
                if (ac.signal.aborted || session.status === 'failed') return;
                await processImitation(session, db, emit, ac.signal);
            } catch (e) {
                if (e.name !== 'AbortError' && e.code !== 'ERR_CANCELED') {
                    emitEvent(sessionId, 'error', { message: e.message });
                }
            } finally {
                concurrency.release(sessionId);
                sessionAborts.delete(sessionId);
            }
        });
    } catch (err) {
        console.error('Imitate start error:', err.message);
        res.status(500).json({ error: '启动失败，请稍后重试' });
    }
});

// ============ 开始增强仿写会话（仿写 + 润色）============

app.post('/api/imitate/enhanced/start', authMiddleware, (req, res) => {
    try {
        const { news_text, target_chars, bypass, style, style_ref } = req.body;
        if (!news_text?.trim()) return res.status(400).json({ error: '请输入需要处理的文章' });
        if (news_text.length > 3500) return res.status(400).json({ error: '文章最多 3500 字' });

        const card = db.prepare('SELECT id, remaining_uses, card_type, remaining_chars FROM cards WHERE id = ?').get(req.user.card_id);
        if (!card) return res.status(404).json({ error: '卡密不存在' });
        if (card.card_type === 'chars') {
            if (card.remaining_chars <= 0) return res.status(403).json({ error: '字数余额不足，请联系管理员充值' });
        } else {
            if (card.remaining_uses <= 0) return res.status(403).json({ error: '次数已用完，请联系管理员获取新卡密' });
        }

        const sessionId = crypto.randomUUID();
        const tChars = parseInt(target_chars) || 0;
        const bypassFlag = bypass ? '1' : '0';
        const styleVal = ['default', 'preserve', 'emotional'].includes(style) ? style : 'default';
        const styleRefText = (style_ref || '').trim() || null;
        db.prepare("INSERT INTO sessions (session_id, card_id, original_text, mode, reference_text, style_reference, status) VALUES (?, ?, ?, 'enhanced_imitate', ?, ?, 'pending')")
            .run(sessionId, card.id, news_text.trim(), `${tChars > 0 ? String(tChars) : ''}:${bypassFlag}:${styleVal}`, styleRefText);

        res.json({ sessionId });

        setImmediate(async () => {
            const emit = (type, data) => emitEvent(sessionId, type, data);
            const ac = new AbortController();
            sessionAborts.set(sessionId, ac);
            try {
                await concurrency.acquire(sessionId, ac.signal, pos => emit('queued', { position: pos }));
            } catch (e) {
                sessionAborts.delete(sessionId);
                return; // 排队中被取消，直接退出
            }
            try {
                const session = db.prepare('SELECT * FROM sessions WHERE session_id = ?').get(sessionId);
                if (ac.signal.aborted || session.status === 'failed') return;
                await processEnhancedImitation(session, db, emit, ac.signal);
            } catch (e) {
                if (e.name !== 'AbortError' && e.code !== 'ERR_CANCELED') {
                    emitEvent(sessionId, 'error', { message: e.message });
                }
            } finally {
                concurrency.release(sessionId);
                sessionAborts.delete(sessionId);
            }
        });
    } catch (err) {
        console.error('Enhanced imitate start error:', err.message);
        res.status(500).json({ error: '启动失败，请稍后重试' });
    }
});

// ============ 历史记录 ============

app.get('/api/sessions/history', authMiddleware, (req, res) => {
    try {
        const sessions = db.prepare(
            "SELECT session_id, status, created_at, completed_at, total_segments FROM sessions WHERE card_id = ? ORDER BY created_at DESC LIMIT 20"
        ).all(req.user.card_id);
        res.json(sessions);
    } catch (err) { res.status(500).json({ error: '获取失败' }); }
});

app.get('/api/sessions/:sessionId/result', authMiddleware, (req, res) => {
    try {
        const session = db.prepare('SELECT * FROM sessions WHERE session_id = ?').get(req.params.sessionId);
        if (!session || session.card_id !== req.user.card_id) return res.status(404).json({ error: '不存在' });

        const segs = db.prepare(
            'SELECT original_text, enhanced_text, is_skipped FROM segments WHERE session_id = ? ORDER BY segment_index'
        ).all(req.params.sessionId);

        const text = segs.map(s => s.is_skipped ? s.original_text : (s.enhanced_text || '')).filter(t => t).join('\n\n');
        res.json({ text, status: session.status, created_at: session.created_at });
    } catch (err) { res.status(500).json({ error: '获取失败' }); }
});

// ============ 管理员接口 ============

function adminAuth(req, res, next) {
    if (req.headers['x-admin-secret'] !== ADMIN_SECRET) return res.status(403).json({ error: '无权限' });
    next();
}

app.post('/api/admin/generate-cards', adminAuth, (req, res) => {
    try {
        const count = Math.min(parseInt(req.body.count) || 1, 100);
        const expiresHours = req.body.expires_hours ? parseInt(req.body.expires_hours) : null;
        const expiresAt = expiresHours ? new Date(Date.now() + expiresHours * 3600000).toISOString().slice(0, 19).replace('T', ' ') : null;
        const canImitate = req.body.can_imitate ? 1 : 0;
        const cardType = req.body.card_type === 'chars' ? 'chars' : 'uses';
        const generated = [];

        if (cardType === 'chars') {
            const chars = Math.max(1, parseInt(req.body.chars) || 10000);
            const insert = db.prepare("INSERT INTO cards (code, remaining_uses, total_uses, expires_at, can_imitate, card_type, remaining_chars, total_chars) VALUES (?, 1, 1, ?, ?, 'chars', ?, ?)");
            db.transaction(() => {
                for (let i = 0; i < count; i++) {
                    let code, attempts = 0;
                    do { code = generateCardCode(); attempts++; }
                    while (db.prepare('SELECT id FROM cards WHERE code = ?').get(code) && attempts < 10);
                    insert.run(code, expiresAt, canImitate, chars, chars);
                    generated.push(code);
                }
            })();
        } else {
            const uses = Math.min(parseInt(req.body.uses) || 5, 1000);
            const insert = db.prepare("INSERT INTO cards (code, remaining_uses, total_uses, expires_at, can_imitate, card_type) VALUES (?, ?, ?, ?, ?, 'uses')");
            db.transaction(() => {
                for (let i = 0; i < count; i++) {
                    let code, attempts = 0;
                    do { code = generateCardCode(); attempts++; }
                    while (db.prepare('SELECT id FROM cards WHERE code = ?').get(code) && attempts < 10);
                    insert.run(code, uses, uses, expiresAt, canImitate);
                    generated.push(code);
                }
            })();
        }
        res.json({ generated, expires_at: expiresAt, card_type: cardType });
    } catch (err) { res.status(500).json({ error: '生成失败' }); }
});

app.get('/api/admin/cards', adminAuth, (req, res) => {
    try { res.json(db.prepare('SELECT * FROM cards ORDER BY id DESC').all()); }
    catch (err) { res.status(500).json({ error: '获取失败' }); }
});

app.patch('/api/admin/cards/:id', adminAuth, (req, res) => {
    try {
        const { remaining_uses, remaining_chars, expires_at } = req.body;
        if (remaining_uses !== undefined) {
            const safeUses = parseInt(remaining_uses, 10);
            if (!Number.isInteger(safeUses) || safeUses < 0 || safeUses > 1000000) return res.status(400).json({ error: 'remaining_uses 超出允许范围' });
            db.prepare('UPDATE cards SET remaining_uses = ? WHERE id = ?').run(safeUses, req.params.id);
        }
        if (remaining_chars !== undefined) {
            const safeChars = parseInt(remaining_chars, 10);
            if (!Number.isInteger(safeChars) || safeChars < 0 || safeChars > 100000000) return res.status(400).json({ error: 'remaining_chars 超出允许范围' });
            db.prepare('UPDATE cards SET remaining_chars = ? WHERE id = ?').run(safeChars, req.params.id);
        }
        if (expires_at !== undefined) db.prepare('UPDATE cards SET expires_at = ? WHERE id = ?').run(expires_at || null, req.params.id);
        res.json({ message: '已更新' });
    } catch (err) { res.status(500).json({ error: '更新失败' }); }
});

app.delete('/api/admin/cards/exhausted', adminAuth, (req, res) => {
    try {
        const exhausted = db.prepare('SELECT id FROM cards WHERE remaining_uses <= 0').all();
        db.transaction(() => {
            for (const card of exhausted) {
                const sessions = db.prepare('SELECT session_id FROM sessions WHERE card_id = ?').all(card.id);
                for (const s of sessions) {
                    db.prepare('DELETE FROM segments WHERE session_id = ?').run(s.session_id);
                }
                db.prepare('DELETE FROM sessions WHERE card_id = ?').run(card.id);
                db.prepare('DELETE FROM cards WHERE id = ?').run(card.id);
            }
        })();
        res.json({ deleted: exhausted.length });
    } catch (err) { res.status(500).json({ error: '删除失败' }); }
});

app.delete('/api/admin/cards/:id', adminAuth, (req, res) => {
    try {
        const sessions = db.prepare('SELECT session_id FROM sessions WHERE card_id = ?').all(req.params.id);
        db.transaction(() => {
            for (const s of sessions) {
                db.prepare('DELETE FROM segments WHERE session_id = ?').run(s.session_id);
            }
            db.prepare('DELETE FROM sessions WHERE card_id = ?').run(req.params.id);
            db.prepare('DELETE FROM cards WHERE id = ?').run(req.params.id);
        })();
        res.json({ message: '已删除' });
    } catch (err) { res.status(500).json({ error: '删除失败' }); }
});

app.get('/api/admin/stats', adminAuth, (req, res) => {
    try {
        // ===== 卡密基础 =====
        const totalCards = db.prepare('SELECT COUNT(*) as n FROM cards').get().n;
        const activeCards = db.prepare("SELECT COUNT(*) as n FROM cards WHERE remaining_uses > 0 AND (expires_at IS NULL OR datetime(expires_at) > datetime('now'))").get().n;

        // ===== 用户增长（以卡密首次使用为"新用户"） =====
        const totalUsers     = db.prepare("SELECT COUNT(*) as n FROM cards WHERE first_used_at IS NOT NULL").get().n;
        const todayNewUsers  = db.prepare("SELECT COUNT(*) as n FROM cards WHERE date(datetime(first_used_at,'+8 hours')) = date(datetime('now','+8 hours'))").get().n;
        const weekNewUsers   = db.prepare("SELECT COUNT(*) as n FROM cards WHERE first_used_at >= datetime('now','-7 days')").get().n;
        const monthNewUsers  = db.prepare("SELECT COUNT(*) as n FROM cards WHERE first_used_at >= datetime('now','-30 days')").get().n;
        // 上周 / 上月（用于环比）
        const lastWeekNew    = db.prepare("SELECT COUNT(*) as n FROM cards WHERE first_used_at >= datetime('now','-14 days') AND first_used_at < datetime('now','-7 days')").get().n;
        const lastMonthNew   = db.prepare("SELECT COUNT(*) as n FROM cards WHERE first_used_at >= datetime('now','-60 days') AND first_used_at < datetime('now','-30 days')").get().n;

        // ===== 活跃用户（当期内有完成会话的独立卡密） =====
        const todayActiveUsers  = db.prepare("SELECT COUNT(DISTINCT card_id) as n FROM sessions WHERE status='completed' AND date(datetime(created_at,'+8 hours')) = date(datetime('now','+8 hours'))").get().n;
        const weekActiveUsers   = db.prepare("SELECT COUNT(DISTINCT card_id) as n FROM sessions WHERE status='completed' AND created_at >= datetime('now','-7 days')").get().n;
        const monthActiveUsers  = db.prepare("SELECT COUNT(DISTINCT card_id) as n FROM sessions WHERE status='completed' AND created_at >= datetime('now','-30 days')").get().n;

        // ===== 使用量 =====
        const todayDone    = db.prepare("SELECT COUNT(*) as n FROM sessions WHERE status='completed' AND date(datetime(created_at,'+8 hours')) = date(datetime('now','+8 hours'))").get().n;
        const weekDone     = db.prepare("SELECT COUNT(*) as n FROM sessions WHERE status='completed' AND created_at >= datetime('now','-7 days')").get().n;
        const monthDone    = db.prepare("SELECT COUNT(*) as n FROM sessions WHERE status='completed' AND created_at >= datetime('now','-30 days')").get().n;
        const lastWeekDone = db.prepare("SELECT COUNT(*) as n FROM sessions WHERE status='completed' AND created_at >= datetime('now','-14 days') AND created_at < datetime('now','-7 days')").get().n;
        const lastMonthDone= db.prepare("SELECT COUNT(*) as n FROM sessions WHERE status='completed' AND created_at >= datetime('now','-60 days') AND created_at < datetime('now','-30 days')").get().n;
        const totalDone    = db.prepare("SELECT COUNT(*) as n FROM sessions WHERE status='completed'").get().n;

        // ===== 字数经营 =====
        const totalCharsSold     = db.prepare("SELECT COALESCE(SUM(total_chars),0) as n FROM cards WHERE card_type='chars'").get().n;
        const totalCharsConsumed = db.prepare("SELECT COALESCE(SUM(total_chars - remaining_chars),0) as n FROM cards WHERE card_type='chars'").get().n;
        const totalCharsRemain   = db.prepare("SELECT COALESCE(SUM(remaining_chars),0) as n FROM cards WHERE card_type='chars' AND remaining_chars > 0 AND (expires_at IS NULL OR datetime(expires_at) > datetime('now'))").get().n;
        const charsCardCount     = db.prepare("SELECT COUNT(*) as n FROM cards WHERE card_type='chars'").get().n;
        const charsActiveCount   = db.prepare("SELECT COUNT(*) as n FROM cards WHERE card_type='chars' AND remaining_chars > 0 AND (expires_at IS NULL OR datetime(expires_at) > datetime('now'))").get().n;

        const todayCharsUsed = db.prepare(`
            SELECT COALESCE(SUM(LENGTH(REPLACE(REPLACE(s.original_text, CHAR(10), ''), CHAR(13), ''))),0) as n
            FROM sessions s WHERE s.status='completed' AND s.card_id IN (SELECT id FROM cards WHERE card_type='chars')
              AND date(datetime(s.created_at,'+8 hours')) = date(datetime('now','+8 hours'))
        `).get().n;
        const weekCharsUsed = db.prepare(`
            SELECT COALESCE(SUM(LENGTH(REPLACE(REPLACE(s.original_text, CHAR(10), ''), CHAR(13), ''))),0) as n
            FROM sessions s WHERE s.status='completed' AND s.card_id IN (SELECT id FROM cards WHERE card_type='chars')
              AND s.created_at >= datetime('now','-7 days')
        `).get().n;
        const monthCharsUsed = db.prepare(`
            SELECT COALESCE(SUM(LENGTH(REPLACE(REPLACE(s.original_text, CHAR(10), ''), CHAR(13), ''))),0) as n
            FROM sessions s WHERE s.status='completed' AND s.card_id IN (SELECT id FROM cards WHERE card_type='chars')
              AND s.created_at >= datetime('now','-30 days')
        `).get().n;
        const lastWeekCharsUsed = db.prepare(`
            SELECT COALESCE(SUM(LENGTH(REPLACE(REPLACE(s.original_text, CHAR(10), ''), CHAR(13), ''))),0) as n
            FROM sessions s WHERE s.status='completed' AND s.card_id IN (SELECT id FROM cards WHERE card_type='chars')
              AND s.created_at >= datetime('now','-14 days') AND s.created_at < datetime('now','-7 days')
        `).get().n;
        const lastMonthCharsUsed = db.prepare(`
            SELECT COALESCE(SUM(LENGTH(REPLACE(REPLACE(s.original_text, CHAR(10), ''), CHAR(13), ''))),0) as n
            FROM sessions s WHERE s.status='completed' AND s.card_id IN (SELECT id FROM cards WHERE card_type='chars')
              AND s.created_at >= datetime('now','-60 days') AND s.created_at < datetime('now','-30 days')
        `).get().n;

        // ===== 环比增长率 =====
        const growth = (now, last) => last > 0 ? Math.round((now - last) / last * 100) : (now > 0 ? 100 : 0);
        const weekUserGrowth  = growth(weekNewUsers,  lastWeekNew);
        const monthUserGrowth = growth(monthNewUsers, lastMonthNew);
        const weekDoneGrowth  = growth(weekDone,  lastWeekDone);
        const monthDoneGrowth = growth(monthDone, lastMonthDone);
        const weekCharsGrowth  = growth(weekCharsUsed,  lastWeekCharsUsed);
        const monthCharsGrowth = growth(monthCharsUsed, lastMonthCharsUsed);

        // ===== 近 14 天每日趋势 =====
        const sessionTrendRaw = db.prepare(`
            SELECT date(datetime(created_at,'+8 hours')) as day, COUNT(*) as sessions, COUNT(DISTINCT card_id) as users
            FROM sessions WHERE status='completed' AND created_at >= datetime('now','-13 days')
            GROUP BY day ORDER BY day
        `).all();
        const newUserTrendRaw = db.prepare(`
            SELECT date(datetime(first_used_at,'+8 hours')) as day, COUNT(*) as newUsers
            FROM cards WHERE first_used_at >= datetime('now','-13 days')
            GROUP BY day ORDER BY day
        `).all();
        const sessMap = {}, newMap = {};
        sessionTrendRaw.forEach(r => { sessMap[r.day] = { sessions: r.sessions, users: r.users }; });
        newUserTrendRaw.forEach(r => { newMap[r.day] = r.newUsers; });
        const trend = [];
        for (let i = 13; i >= 0; i--) {
            const d = new Date(Date.now() + 8 * 3600000 - i * 86400000);
            const key = d.toISOString().slice(0, 10);
            trend.push({ day: key, sessions: sessMap[key]?.sessions || 0, users: sessMap[key]?.users || 0, newUsers: newMap[key] || 0 });
        }

        res.json({
            totalCards, activeCards, totalUsers,
            todayNewUsers, weekNewUsers, monthNewUsers,
            weekUserGrowth, monthUserGrowth,
            todayActiveUsers, weekActiveUsers, monthActiveUsers,
            todayDone, weekDone, monthDone, totalDone,
            weekDoneGrowth, monthDoneGrowth,
            totalCharsSold, totalCharsConsumed, totalCharsRemain,
            charsCardCount, charsActiveCount,
            todayCharsUsed, weekCharsUsed, monthCharsUsed,
            weekCharsGrowth, monthCharsGrowth,
            trend
        });
    } catch (err) { res.status(500).json({ error: '获取失败' }); }
});

app.get('/api/admin/hourly', adminAuth, (req, res) => {
    try {
        const rows = db.prepare(`
            SELECT CAST(strftime('%H', datetime(created_at, '+8 hours')) AS INTEGER) as hour,
                   COUNT(*) as count
            FROM sessions WHERE status='completed'
              AND date(datetime(created_at,'+8 hours')) = date(datetime('now','+8 hours'))
            GROUP BY hour ORDER BY hour
        `).all();
        const hourly = Array.from({ length: 24 }, (_, i) => ({ hour: i, count: 0 }));
        rows.forEach(r => { hourly[r.hour].count = r.count; });
        res.json({ hourly });
    } catch (err) { res.status(500).json({ error: '获取失败' }); }
});

app.get('/api/admin/token-usage', adminAuth, (req, res) => {
    try {
        res.json(getTodayUsage());
    } catch (err) { res.status(500).json({ error: '获取失败' }); }
});

app.get('/api/admin/sessions', adminAuth, (req, res) => {
    try {
        const rows = db.prepare(
            "SELECT s.*, c.code as card_code FROM sessions s LEFT JOIN cards c ON s.card_id = c.id ORDER BY s.created_at DESC LIMIT 50"
        ).all();
        res.json(rows);
    } catch (err) { res.status(500).json({ error: '获取失败' }); }
});

// ============ 拒绝记录 ============

app.get('/api/admin/refusals/stats', adminAuth, (req, res) => {
    try {
        const todayTotal   = db.prepare("SELECT COUNT(*) as n FROM sessions WHERE date(datetime(created_at,'+8 hours')) = date(datetime('now','+8 hours'))").get().n;
        const todayRefused = db.prepare("SELECT COUNT(*) as n FROM sessions WHERE error_message='AI_REFUSAL' AND date(datetime(created_at,'+8 hours')) = date(datetime('now','+8 hours'))").get().n;
        const todaySuccess = db.prepare("SELECT COUNT(*) as n FROM sessions WHERE status='completed' AND date(datetime(created_at,'+8 hours')) = date(datetime('now','+8 hours'))").get().n;
        const totalRefused  = db.prepare("SELECT COUNT(*) as n FROM sessions WHERE error_message='AI_REFUSAL'").get().n;
        const totalFinished = db.prepare("SELECT COUNT(*) as n FROM sessions WHERE status IN ('completed','failed')").get().n;
        const totalSuccess  = db.prepare("SELECT COUNT(*) as n FROM sessions WHERE status='completed'").get().n;
        const todaySuggestions = db.prepare("SELECT COUNT(*) as n FROM feedback_reports WHERE report_type='suggestion' AND date(datetime(created_at,'+8 hours')) = date(datetime('now','+8 hours'))").get().n;
        const totalSuggestions = db.prepare("SELECT COUNT(*) as n FROM feedback_reports WHERE report_type='suggestion'").get().n;
        const todayArticleFeedback = db.prepare("SELECT COUNT(*) as n FROM feedback_reports WHERE report_type='article_feedback' AND date(datetime(created_at,'+8 hours')) = date(datetime('now','+8 hours'))").get().n;
        const totalArticleFeedback = db.prepare("SELECT COUNT(*) as n FROM feedback_reports WHERE report_type='article_feedback'").get().n;
        res.json({
            todayTotal, todayRefused, todaySuccess,
            todayRate: todayTotal > 0 ? Math.round(todaySuccess / todayTotal * 100) : null,
            totalRefused, totalFinished, totalSuccess,
            totalRate: totalFinished > 0 ? Math.round(totalSuccess / totalFinished * 100) : null,
            todaySuggestions, totalSuggestions,
            todayArticleFeedback, totalArticleFeedback
        });
    } catch (err) { res.status(500).json({ error: '获取失败' }); }
});

app.get('/api/admin/refusals/list', adminAuth, (req, res) => {
    try {
        const merged = db.prepare(`
            SELECT
                'ai_refusal' as source_type,
                s.session_id as session_id,
                s.original_text as original_text,
                s.created_at as created_at,
                s.mode as mode,
                NULL as report_type,
                s.reference_text as reference_text,
                sg.enhanced_text as ai_output,
                NULL as issue_text
            FROM sessions s
            LEFT JOIN segments sg ON sg.session_id = s.session_id AND sg.segment_index = 0
            WHERE s.error_message = 'AI_REFUSAL'

            UNION ALL

            SELECT
                'user_feedback' as source_type,
                f.session_id as session_id,
                f.original_text as original_text,
                f.created_at as created_at,
                f.mode as mode,
                f.report_type as report_type,
                NULL as reference_text,
                NULL as ai_output,
                f.issue_text as issue_text
            FROM feedback_reports f

            ORDER BY created_at DESC
            LIMIT 100
        `).all();
        res.json(merged);
    } catch (err) { res.status(500).json({ error: '获取失败' }); }
});

app.post('/api/feedback', authMiddleware, (req, res) => {
    try {
        const { report_type, issue_text, original_text, mode, session_id } = req.body || {};
        const safeType = report_type === 'article_feedback' ? 'article_feedback' : 'suggestion';
        const issue = String(issue_text || '').trim();
        const original = String(original_text || '').trim();
        const safeMode = ['polish', 'imitate', 'enhanced_imitate'].includes(mode) ? mode : 'polish';
        const safeSessionId = session_id ? String(session_id).trim() : null;

        if (!issue) return res.status(400).json({ error: safeType === 'suggestion' ? '请输入你的建议内容' : '请输入你遇到的问题' });
        if (safeType === 'article_feedback' && !original) return res.status(400).json({ error: '未找到当前润色输入框中的文章原文' });
        if (issue.length > 1000) return res.status(400).json({ error: '反馈内容最多 1000 字' });
        if (original.length > 20000) return res.status(400).json({ error: '原文过长，暂时无法提交反馈' });

        db.prepare(`
            INSERT INTO feedback_reports (card_id, session_id, mode, report_type, issue_text, original_text)
            VALUES (?, ?, ?, ?, ?, ?)
        `).run(req.user.card_id, safeSessionId, safeMode, safeType, issue, original || null);

        res.json({ success: true });
    } catch (err) { res.status(500).json({ error: '反馈提交失败' }); }
});

// ============ 文章语料库 ============

app.get('/api/admin/corpus', adminAuth, (req, res) => {
    try {
        const page = Math.max(1, parseInt(req.query.page) || 1);
        const limit = Math.min(500, Math.max(1, parseInt(req.query.limit) || 50));
        const offset = (page - 1) * limit;
        const search = req.query.search ? `%${req.query.search}%` : null;

        let where = search ? "WHERE original_text LIKE ? OR card_code LIKE ?" : "";
        let params = search ? [search, search] : [];

        const total = db.prepare(`SELECT COUNT(*) as cnt FROM article_corpus ${where}`).get(...params).cnt;
        const rows = db.prepare(`SELECT id, card_code, submitted_at, char_count, style, original_text FROM article_corpus ${where} ORDER BY submitted_at DESC LIMIT ? OFFSET ?`)
            .all(...params, limit, offset);

        res.json({ total, page, limit, rows });
    } catch (err) { res.status(500).json({ error: '获取语料库失败' }); }
});

app.delete('/api/admin/corpus/:id', adminAuth, (req, res) => {
    try {
        db.prepare('DELETE FROM article_corpus WHERE id = ?').run(req.params.id);
        res.json({ success: true });
    } catch (err) { res.status(500).json({ error: '删除失败' }); }
});

// ============ 邮箱验证码 ============

// 内存存储：{ email -> { code, expiresAt, attempts } }
const emailCodeStore = new Map();

// 发送验证码（60秒内只能发一次）
app.post('/api/email/send-code', async (req, res) => {
  const { email } = req.body || {};
  if (!email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
    return res.status(400).json({ error: '邮箱格式不正确' });
  }
  const existing = emailCodeStore.get(email);
  if (existing && Date.now() < existing.expiresAt - 4 * 60 * 1000) {
    return res.status(429).json({ error: '发送太频繁，请 60 秒后再试' });
  }
  const code = String(Math.floor(100000 + Math.random() * 900000));
  emailCodeStore.set(email, { code, expiresAt: Date.now() + 5 * 60 * 1000, attempts: 0 });
  try {
    await sendVerifyCode(email, code);
    res.json({ ok: true });
  } catch (e) {
    console.error('发送验证码失败:', e.message);
    emailCodeStore.delete(email);
    res.status(500).json({ error: '邮件发送失败，请稍后重试' });
  }
});

// 校验验证码
app.post('/api/email/verify-code', (req, res) => {
  const { email, code } = req.body || {};
  if (!email || !code) return res.status(400).json({ error: '参数不完整' });
  const record = emailCodeStore.get(email);
  if (!record) return res.status(400).json({ error: '请先发送验证码' });
  if (Date.now() > record.expiresAt) {
    emailCodeStore.delete(email);
    return res.status(400).json({ error: '验证码已过期，请重新发送' });
  }
  record.attempts = (record.attempts || 0) + 1;
  if (record.attempts > 5) return res.status(429).json({ error: '错误次数过多，请重新发送' });
  if (record.code !== String(code)) return res.status(400).json({ error: '验证码不正确' });
  emailCodeStore.delete(email);
  res.json({ ok: true });
});

// ============ 用户账号系统 ============

// 图形验证码（内存存储）
const captchaStore = new Map();
setInterval(() => { const now = Date.now(); for (const [k, v] of captchaStore) { if (v.expires < now) captchaStore.delete(k); } }, 5 * 60 * 1000);

function generateCaptcha() {
  const a = Math.floor(Math.random() * 9) + 1;
  const b = Math.floor(Math.random() * 9) + 1;
  const token = crypto.randomBytes(16).toString('hex');
  captchaStore.set(token, { answer: a + b, expires: Date.now() + 10 * 60 * 1000 });
  const noise = Array.from({ length: 4 }, () => {
    const x1 = Math.floor(Math.random() * 110), y1 = Math.floor(Math.random() * 38);
    const x2 = Math.floor(Math.random() * 110), y2 = Math.floor(Math.random() * 38);
    return `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="rgba(129,140,248,0.25)" stroke-width="1"/>`;
  }).join('');
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="110" height="38"><rect width="110" height="38" fill="rgba(10,13,24,0.65)" rx="4"/>${noise}<text x="55" y="26" font-size="17" font-weight="700" font-family="monospace" fill="#818cf8" text-anchor="middle" letter-spacing="3">${a} + ${b} = ?</text></svg>`;
  return { token, svg };
}

// GET /api/auth/captcha
app.get('/api/auth/captcha', (req, res) => {
  const { token, svg } = generateCaptcha();
  res.json({ token, svg });
});

// POST /api/auth/register
app.post('/api/auth/register', async (req, res) => {
  const { email, password, captchaToken, captchaAnswer } = req.body || {};
  if (!email || !password || !captchaToken || captchaAnswer === undefined) {
    return res.status(400).json({ error: '请填写所有字段' });
  }
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
    return res.status(400).json({ error: '邮箱格式不正确' });
  }
  if (String(password).length < 8) {
    return res.status(400).json({ error: '密码至少 8 位' });
  }
  // 验证码
  const captcha = captchaStore.get(captchaToken);
  if (!captcha || captcha.expires < Date.now()) {
    captchaStore.delete(captchaToken);
    return res.status(400).json({ error: '验证码已过期，请刷新' });
  }
  if (parseInt(captchaAnswer) !== captcha.answer) {
    captchaStore.delete(captchaToken);
    return res.status(400).json({ error: '验证码不正确' });
  }
  captchaStore.delete(captchaToken);

  const normalizedEmail = email.trim().toLowerCase();
  // 已注册检测
  const existing = db.prepare('SELECT id, is_verified FROM users WHERE normalized_email = ?').get(normalizedEmail);
  if (existing && existing.is_verified) {
    return res.status(400).json({ error: '该邮箱已注册，请直接登录' });
  }

  const passwordHash = await bcrypt.hash(password, 10);
  const verifyToken = crypto.randomBytes(32).toString('hex');
  const verifyExpires = Date.now() + 24 * 60 * 60 * 1000;

  if (existing && !existing.is_verified) {
    // 重发验证邮件
    db.prepare('UPDATE users SET password_hash=?, verify_token=?, verify_token_expires=? WHERE id=?')
      .run(passwordHash, verifyToken, verifyExpires, existing.id);
  } else {
    try {
      db.prepare('INSERT INTO users (email, normalized_email, password_hash, verify_token, verify_token_expires) VALUES (?,?,?,?,?)')
        .run(email.trim(), normalizedEmail, passwordHash, verifyToken, verifyExpires);
    } catch (e) {
      return res.status(400).json({ error: '该邮箱已注册' });
    }
  }

  const baseUrl = process.env.BASE_URL || `http://localhost:${PORT}`;
  try {
    await sendVerificationEmail(email.trim(), `${baseUrl}/api/auth/verify-email?token=${verifyToken}`);
  } catch (e) {
    console.error('发送验证邮件失败:', e.message);
  }
  res.json({ message: '注册成功！请查收验证邮件（注意检查垃圾邮件文件夹），验证后即可登录。' });
});

// GET /api/auth/verify-email
app.get('/api/auth/verify-email', (req, res) => {
  const { token } = req.query;
  if (!token) return res.redirect('/login?msg=invalid');
  const user = db.prepare('SELECT * FROM users WHERE verify_token = ? AND is_verified = 0').get(token);
  if (!user) return res.redirect('/login?msg=invalid');
  if (Date.now() > user.verify_token_expires) return res.redirect('/login?msg=expired');
  db.prepare('UPDATE users SET is_verified=1, verify_token=NULL, verify_token_expires=NULL WHERE id=?').run(user.id);
  res.redirect('/login?msg=verified');
});

// POST /api/auth/login
app.post('/api/auth/login', async (req, res) => {
  const { email, password } = req.body || {};
  if (!email || !password) return res.status(400).json({ error: '请填写邮箱和密码' });
  const normalizedEmail = email.trim().toLowerCase();
  const user = db.prepare('SELECT * FROM users WHERE normalized_email = ?').get(normalizedEmail);
  if (!user) return res.status(401).json({ error: '邮箱或密码不正确' });
  const ok = await bcrypt.compare(password, user.password_hash);
  if (!ok) return res.status(401).json({ error: '邮箱或密码不正确' });
  if (!user.is_verified) return res.status(403).json({ error: '邮箱未验证，请查收验证邮件（注意垃圾邮件）' });
  db.prepare('UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE id = ?').run(user.id);
  const token = jwt.sign({ type: 'user', userId: user.id, email: user.email }, process.env.JWT_SECRET, { expiresIn: '30d' });
  res.json({ token, email: user.email });
});

// GET /api/auth/me
app.get('/api/auth/me', (req, res) => {
  const auth = req.headers.authorization;
  if (!auth || !auth.startsWith('Bearer ')) return res.status(401).json({ error: '未登录' });
  try {
    const payload = jwt.verify(auth.slice(7), process.env.JWT_SECRET);
    if (payload.type !== 'user') return res.status(401).json({ error: '无效令牌' });
    const user = db.prepare('SELECT id, email, created_at FROM users WHERE id = ?').get(payload.userId);
    if (!user) return res.status(401).json({ error: '用户不存在' });
    res.json({ ok: true, email: user.email, userId: user.id });
  } catch { res.status(401).json({ error: '令牌无效或已过期' }); }
});

// POST /api/auth/forgot-password
app.post('/api/auth/forgot-password', async (req, res) => {
  const { email } = req.body || {};
  if (!email) return res.status(400).json({ error: '请输入邮箱' });
  const normalizedEmail = email.trim().toLowerCase();
  const user = db.prepare('SELECT * FROM users WHERE normalized_email = ? AND is_verified = 1').get(normalizedEmail);
  // 无论是否存在都返回成功，防止邮箱枚举
  if (!user) return res.json({ message: '如果该邮箱已注册，重置链接已发送，请查收（注意垃圾邮件）' });
  const resetToken = crypto.randomBytes(32).toString('hex');
  const resetExpires = Date.now() + 30 * 60 * 1000;
  db.prepare('UPDATE users SET reset_token=?, reset_token_expires=? WHERE id=?').run(resetToken, resetExpires, user.id);
  const baseUrl = process.env.BASE_URL || `http://localhost:${PORT}`;
  try {
    await sendPasswordResetEmail(user.email, `${baseUrl}/reset-password?token=${resetToken}`);
  } catch (e) {
    console.error('发送重置邮件失败:', e.message);
  }
  res.json({ message: '如果该邮箱已注册，重置链接已发送，请查收（注意垃圾邮件）' });
});

// POST /api/auth/reset-password
app.post('/api/auth/reset-password', async (req, res) => {
  const { token, password } = req.body || {};
  if (!token || !password) return res.status(400).json({ error: '参数不完整' });
  if (String(password).length < 8) return res.status(400).json({ error: '密码至少 8 位' });
  const user = db.prepare('SELECT * FROM users WHERE reset_token = ?').get(token);
  if (!user || !user.reset_token_expires) return res.status(400).json({ error: '重置链接无效' });
  if (Date.now() > user.reset_token_expires) return res.status(400).json({ error: '重置链接已过期，请重新申请' });
  const hash = await bcrypt.hash(password, 10);
  db.prepare('UPDATE users SET password_hash=?, reset_token=NULL, reset_token_expires=NULL WHERE id=?').run(hash, user.id);
  res.json({ ok: true, message: '密码已重置，2 秒后跳转登录…' });
});

// ============ 账号管理 Admin API ============

// 用户统计概览
app.get('/api/admin/user-stats', adminAuth, (req, res) => {
    const total      = db.prepare('SELECT COUNT(*) AS n FROM users').get().n;
    const verified   = db.prepare('SELECT COUNT(*) AS n FROM users WHERE is_verified = 1').get().n;
    const todayNew   = db.prepare("SELECT COUNT(*) AS n FROM users WHERE date(created_at) = date('now')").get().n;
    const weekNew    = db.prepare("SELECT COUNT(*) AS n FROM users WHERE created_at >= datetime('now','-7 days')").get().n;
    const dau        = db.prepare("SELECT COUNT(DISTINCT user_id) AS n FROM sessions WHERE user_id IS NOT NULL AND date(created_at) = date('now') AND status = 'completed'").get().n;
    const wau        = db.prepare("SELECT COUNT(DISTINCT user_id) AS n FROM sessions WHERE user_id IS NOT NULL AND created_at >= datetime('now','-7 days') AND status = 'completed'").get().n;
    const mau        = db.prepare("SELECT COUNT(DISTINCT user_id) AS n FROM sessions WHERE user_id IS NOT NULL AND created_at >= datetime('now','-30 days') AND status = 'completed'").get().n;
    // 近14天每日新注册趋势
    const trend = db.prepare(`
        WITH RECURSIVE dates(d) AS (
            SELECT date('now','-13 days')
            UNION ALL SELECT date(d,'+1 day') FROM dates WHERE d < date('now')
        )
        SELECT d AS day,
            (SELECT COUNT(*) FROM users WHERE date(created_at) = d) AS newUsers,
            (SELECT COUNT(DISTINCT user_id) FROM sessions WHERE user_id IS NOT NULL AND date(created_at) = d AND status='completed') AS dau
        FROM dates ORDER BY d
    `).all();
    res.json({ total, verified, todayNew, weekNew, dau, wau, mau, trend });
});

// 用户列表
app.get('/api/admin/users', adminAuth, (req, res) => {
    const page   = Math.max(1, parseInt(req.query.page) || 1);
    const limit  = Math.min(100, parseInt(req.query.limit) || 20);
    const offset = (page - 1) * limit;
    const search = req.query.search ? '%' + req.query.search + '%' : null;
    const where  = search ? 'WHERE u.email LIKE ?' : '';
    const params = search ? [search] : [];
    const total  = db.prepare(`SELECT COUNT(*) AS n FROM users u ${where}`).get(...params).n;
    const rows   = db.prepare(`
        SELECT u.id, u.email, u.is_verified, u.created_at, u.last_login,
               COUNT(s.id) AS total_uses,
               SUM(CASE WHEN date(s.created_at) = date('now') THEN 1 ELSE 0 END) AS today_uses
        FROM users u
        LEFT JOIN sessions s ON s.user_id = u.id AND s.status = 'completed'
        ${where}
        GROUP BY u.id
        ORDER BY u.created_at DESC
        LIMIT ? OFFSET ?
    `).all(...params, limit, offset);
    res.json({ total, page, limit, rows });
});

// 删除用户
app.delete('/api/admin/users/:id', adminAuth, (req, res) => {
    db.prepare('DELETE FROM users WHERE id = ?').run(req.params.id);
    res.json({ ok: true });
});

// 重置用户验证状态（强制通过验证）
app.post('/api/admin/users/:id/verify', adminAuth, (req, res) => {
    db.prepare('UPDATE users SET is_verified = 1 WHERE id = ?').run(req.params.id);
    res.json({ ok: true });
});

// ============ 前端路由 ============

app.get('/admin', (req, res) => res.sendFile(path.join(__dirname, 'public', 'admin.html')));
app.get('/login', (req, res) => res.sendFile(path.join(__dirname, 'public', 'login.html')));
app.get('/reset-password', (req, res) => res.sendFile(path.join(__dirname, 'public', 'reset-password.html')));
app.get('*', (req, res) => res.sendFile(path.join(__dirname, 'public', 'index.html')));

app.listen(PORT, () => {
    // 启动时清理残留的 processing/pending session，防止前端重连后永久卡住
    const stale = db.prepare("UPDATE sessions SET status = 'failed', error_message = '服务重启，任务中断' WHERE status IN ('processing', 'pending')").run();
    if (stale.changes > 0) console.log(`  已清理 ${stale.changes} 个残留任务`);

    console.log(`\n  润墨智检 服务已启动！`);
    console.log(`  访问地址: http://localhost:${PORT}`);
    console.log(`  管理后台: http://localhost:${PORT}/admin`);
    console.log(`  管理密钥: ${ADMIN_SECRET}\n`);
});
