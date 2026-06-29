const Database = require('better-sqlite3');
const path = require('path');
const fs = require('fs');

const dataDir = path.join(__dirname, 'data');
if (!fs.existsSync(dataDir)) {
    fs.mkdirSync(dataDir, { recursive: true });
}

const dbPath = path.join(dataDir, 'app.db');
const db = new Database(dbPath);

db.pragma('journal_mode = WAL');

db.exec(`
    CREATE TABLE IF NOT EXISTS cards (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT UNIQUE NOT NULL,
        remaining_uses INTEGER NOT NULL DEFAULT 5,
        total_uses INTEGER NOT NULL DEFAULT 5,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        first_used_at DATETIME
    );

    CREATE TABLE IF NOT EXISTS sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT UNIQUE NOT NULL,
        card_id INTEGER NOT NULL,
        status TEXT DEFAULT 'pending',
        original_text TEXT NOT NULL,
        total_segments INTEGER DEFAULT 0,
        current_segment INTEGER DEFAULT 0,
        progress REAL DEFAULT 0,
        failed_segment INTEGER,
        error_message TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        completed_at DATETIME,
        FOREIGN KEY (card_id) REFERENCES cards(id)
    );

    CREATE TABLE IF NOT EXISTS segments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL,
        segment_index INTEGER NOT NULL,
        original_text TEXT NOT NULL,
        polished_text TEXT,
        enhanced_text TEXT,
        is_skipped INTEGER DEFAULT 0,
        status TEXT DEFAULT 'pending',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (session_id) REFERENCES sessions(session_id)
    );
`);

// 迁移
try { db.exec('ALTER TABLE cards ADD COLUMN expires_at DATETIME DEFAULT NULL'); } catch(e) {}
try { db.exec("ALTER TABLE sessions ADD COLUMN mode TEXT DEFAULT 'polish'"); } catch(e) {}
try { db.exec('ALTER TABLE sessions ADD COLUMN reference_text TEXT'); } catch(e) {}
try { db.exec('ALTER TABLE cards ADD COLUMN can_imitate INTEGER DEFAULT 0'); } catch(e) {}
try { db.exec("ALTER TABLE cards ADD COLUMN card_type TEXT DEFAULT 'uses'"); } catch(e) {}
try { db.exec('ALTER TABLE cards ADD COLUMN remaining_chars INTEGER DEFAULT 0'); } catch(e) {}
try { db.exec('ALTER TABLE cards ADD COLUMN total_chars INTEGER DEFAULT 0'); } catch(e) {}
try { db.exec('ALTER TABLE sessions ADD COLUMN style_reference TEXT'); } catch(e) {}
try { db.exec('ALTER TABLE sessions ADD COLUMN credit_refunded INTEGER DEFAULT 0'); } catch(e) {}
try { db.exec('ALTER TABLE sessions ADD COLUMN cancel_requested INTEGER DEFAULT 0'); } catch(e) {}
try { db.exec('ALTER TABLE sessions ADD COLUMN user_id INTEGER DEFAULT NULL'); } catch(e) {}
try { db.exec('ALTER TABLE users ADD COLUMN last_login DATETIME DEFAULT NULL'); } catch(e) {}
try { db.exec('ALTER TABLE users ADD COLUMN total_uses INTEGER DEFAULT 0'); } catch(e) {}

db.exec(`
    CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id TEXT UNIQUE NOT NULL,
        package_id TEXT NOT NULL,
        package_name TEXT NOT NULL,
        chars INTEGER NOT NULL,
        price REAL NOT NULL,
        pay_type INTEGER DEFAULT 2,
        status TEXT DEFAULT 'pending',
        card_code TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        paid_at DATETIME
    );
`);

db.exec(`
    CREATE TABLE IF NOT EXISTS feedback_reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        card_id INTEGER,
        session_id TEXT,
        mode TEXT DEFAULT 'polish',
        report_type TEXT DEFAULT 'article_feedback',
        issue_text TEXT NOT NULL,
        original_text TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (card_id) REFERENCES cards(id)
    );
`);

try { db.exec("ALTER TABLE feedback_reports ADD COLUMN report_type TEXT DEFAULT 'article_feedback'"); } catch(e) {}

db.exec(`
    CREATE TABLE IF NOT EXISTS chatbot_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        card_id INTEGER NOT NULL,
        chars_used INTEGER NOT NULL DEFAULT 0,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (card_id) REFERENCES cards(id)
    );
`);

db.exec(`
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT UNIQUE NOT NULL,
        normalized_email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        is_verified INTEGER DEFAULT 0,
        verify_token TEXT,
        verify_token_expires INTEGER,
        reset_token TEXT,
        reset_token_expires INTEGER,
        card_id INTEGER,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (card_id) REFERENCES cards(id)
    );
`);

db.exec(`
    CREATE TABLE IF NOT EXISTS article_corpus (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        card_code TEXT NOT NULL,
        submitted_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        char_count INTEGER NOT NULL DEFAULT 0,
        style TEXT DEFAULT 'default',
        original_text TEXT NOT NULL,
        text_hash TEXT NOT NULL
    );
`);
try { db.exec('CREATE INDEX IF NOT EXISTS idx_corpus_hash ON article_corpus(text_hash)'); } catch(e) {}
try { db.exec('CREATE INDEX IF NOT EXISTS idx_corpus_card ON article_corpus(card_code)'); } catch(e) {}

console.log('Database initialized successfully.');

module.exports = db;
