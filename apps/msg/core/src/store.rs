//! The message store: chats, messages and contacts in one SQLite file, with full-text search (FTS5) over messages
//! and contacts. Every source (an iPhone backup, Bluetooth MAP, the companion app) adds to the same store; the same
//! message seen twice (a Bluetooth message, then the next backup) is kept once.

use rusqlite::{params, Connection, OptionalExtension};
use serde_json::{json, Value};

use crate::util::handle_key;

pub const HIGHLIGHT_START: &str = "\u{2}";
pub const HIGHLIGHT_END: &str = "\u{3}";

const SCHEMA: &str = r#"
PRAGMA journal_mode = WAL;
CREATE TABLE IF NOT EXISTS chats (
    id INTEGER PRIMARY KEY, key TEXT UNIQUE NOT NULL, name TEXT NOT NULL DEFAULT '', service TEXT NOT NULL DEFAULT '',
    handles TEXT NOT NULL DEFAULT '[]', last_ms INTEGER NOT NULL DEFAULT 0, unread INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY, guid TEXT UNIQUE NOT NULL, chat_id INTEGER NOT NULL REFERENCES chats(id),
    handle TEXT NOT NULL DEFAULT '', from_me INTEGER NOT NULL DEFAULT 0, date_ms INTEGER NOT NULL DEFAULT 0,
    text TEXT NOT NULL DEFAULT '', service TEXT NOT NULL DEFAULT '', source TEXT NOT NULL DEFAULT '',
    attachments TEXT NOT NULL DEFAULT '[]', status TEXT NOT NULL DEFAULT '');
CREATE INDEX IF NOT EXISTS messages_chat_date ON messages(chat_id, date_ms);
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    text, content='messages', content_rowid='id', tokenize='unicode61 remove_diacritics 2');
CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
    INSERT INTO messages_fts(rowid, text) VALUES (new.id, new.text); END;
CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, text) VALUES ('delete', old.id, old.text); END;
CREATE TRIGGER IF NOT EXISTS messages_au AFTER UPDATE OF text ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, text) VALUES ('delete', old.id, old.text);
    INSERT INTO messages_fts(rowid, text) VALUES (new.id, new.text); END;
CREATE TABLE IF NOT EXISTS contacts (
    id INTEGER PRIMARY KEY, key TEXT UNIQUE NOT NULL, name TEXT NOT NULL DEFAULT '', org TEXT NOT NULL DEFAULT '',
    photo TEXT NOT NULL DEFAULT '', handles TEXT NOT NULL DEFAULT '[]', source TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS contact_handles (
    handle_key TEXT NOT NULL, contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    PRIMARY KEY (handle_key, contact_id));
CREATE VIRTUAL TABLE IF NOT EXISTS contacts_fts USING fts5(
    name, org, handles, content='contacts', content_rowid='id', tokenize='unicode61 remove_diacritics 2');
CREATE TRIGGER IF NOT EXISTS contacts_ai AFTER INSERT ON contacts BEGIN
    INSERT INTO contacts_fts(rowid, name, org, handles) VALUES (new.id, new.name, new.org, new.handles); END;
CREATE TRIGGER IF NOT EXISTS contacts_ad AFTER DELETE ON contacts BEGIN
    INSERT INTO contacts_fts(contacts_fts, rowid, name, org, handles) VALUES ('delete', old.id, old.name, old.org, old.handles); END;
CREATE TRIGGER IF NOT EXISTS contacts_au AFTER UPDATE ON contacts BEGIN
    INSERT INTO contacts_fts(contacts_fts, rowid, name, org, handles) VALUES ('delete', old.id, old.name, old.org, old.handles);
    INSERT INTO contacts_fts(rowid, name, org, handles) VALUES (new.id, new.name, new.org, new.handles); END;
"#;

pub struct Store {
    pub db: Connection,
}

/// One message to add, from any source.
#[derive(Debug, Default, Clone, serde::Deserialize)]
#[serde(default)]
pub struct NewMessage {
    pub guid: String,
    /// The chat: a group's own id ("g:..."), or empty for a one-to-one chat with `handle`.
    pub chat_key: String,
    pub chat_name: String,
    pub chat_handles: Vec<String>,
    pub handle: String,
    pub from_me: bool,
    pub date_ms: i64,
    pub text: String,
    pub service: String,
    pub source: String,
    pub attachments: Vec<Value>,
    pub status: String,
}

#[derive(Debug, Default, Clone, serde::Deserialize)]
#[serde(default)]
pub struct NewContact {
    pub key: String,
    pub name: String,
    pub org: String,
    pub photo: String,
    pub handles: Vec<String>,
    pub source: String,
}

/// What a person typed as an FTS5 query: every word must match, each as a prefix ("pizz" finds "pizza").
pub fn fts_query(text: &str) -> String {
    text.split_whitespace()
        .map(|w| w.chars().filter(|c| c.is_alphanumeric() || *c == '\'' || *c == '@' || *c == '.').collect::<String>())
        .filter(|w| !w.is_empty())
        .map(|w| format!("\"{}\"*", w.replace('"', "")))
        .collect::<Vec<_>>()
        .join(" ")
}

impl Store {
    pub fn open(path: &str) -> rusqlite::Result<Store> {
        let db = Connection::open(path)?;
        db.execute_batch("PRAGMA foreign_keys = ON;")?;
        db.execute_batch(SCHEMA)?;
        Ok(Store { db })
    }

    /// The chat for a key, made if new. A one-to-one chat's key is its person's handle key, so a message from
    /// Bluetooth and one from a backup land in the same chat.
    pub fn chat_id(&self, key: &str, name: &str, service: &str, handles: &[String]) -> rusqlite::Result<i64> {
        if let Some(id) = self.db.query_row("SELECT id FROM chats WHERE key = ?1", [key], |r| r.get(0)).optional()? {
            if !name.is_empty() {
                self.db.execute("UPDATE chats SET name = ?2 WHERE id = ?1 AND name = ''", params![id, name])?;
            }
            return Ok(id);
        }
        self.db.execute(
            "INSERT INTO chats(key, name, service, handles) VALUES (?1, ?2, ?3, ?4)",
            params![key, name, service, serde_json::to_string(handles).unwrap()],
        )?;
        Ok(self.db.last_insert_rowid())
    }

    /// Adds a message unless it is already there (same guid; or, from a source without guids, the same text in the
    /// same chat from the same side within two minutes). Returns whether it was new.
    pub fn add_message(&self, m: &NewMessage) -> rusqlite::Result<bool> {
        let key = if !m.chat_key.is_empty() {
            m.chat_key.clone()
        } else {
            format!("h:{}", handle_key(&m.handle))
        };
        let handles = if m.chat_handles.is_empty() && !m.handle.is_empty() { vec![m.handle.clone()] } else { m.chat_handles.clone() };
        let chat = self.chat_id(&key, &m.chat_name, &m.service, &handles)?;
        let guid = if m.guid.is_empty() {
            format!("{}:{}:{}:{}", m.source, key, m.date_ms / 1000, sha1_smol::Sha1::from(&m.text).digest())
        } else {
            m.guid.clone()
        };
        if self.db.query_row("SELECT 1 FROM messages WHERE guid = ?1", [&guid], |_| Ok(())).optional()?.is_some() {
            return Ok(false);
        }
        let twin: Option<(i64, String)> = self
            .db
            .query_row(
                "SELECT id, source FROM messages WHERE chat_id = ?1 AND from_me = ?2 AND text = ?3
                 AND abs(date_ms - ?4) < 120000 LIMIT 1",
                params![chat, m.from_me, m.text, m.date_ms],
                |r| Ok((r.get(0)?, r.get(1)?)),
            )
            .optional()?;
        if let Some((id, source)) = twin {
            // A backup knows more (the real id, the exact time, the attachments): it replaces what Bluetooth gave.
            if m.source == "backup" && source != "backup" {
                self.db.execute(
                    "UPDATE messages SET guid = ?2, date_ms = ?3, attachments = ?4, source = 'backup' WHERE id = ?1",
                    params![id, guid, m.date_ms, serde_json::to_string(&m.attachments).unwrap()],
                )?;
            }
            return Ok(false);
        }
        self.db.execute(
            "INSERT INTO messages(guid, chat_id, handle, from_me, date_ms, text, service, source, attachments, status)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10)",
            params![guid, chat, m.handle, m.from_me, m.date_ms, m.text, m.service, m.source,
                    serde_json::to_string(&m.attachments).unwrap(), m.status],
        )?;
        self.db.execute(
            "UPDATE chats SET last_ms = max(last_ms, ?2), unread = unread + ?3 WHERE id = ?1",
            params![chat, m.date_ms, (!m.from_me && m.source != "backup") as i64],
        )?;
        Ok(true)
    }

    pub fn upsert_contact(&self, c: &NewContact) -> rusqlite::Result<i64> {
        let handles = serde_json::to_string(&c.handles).unwrap();
        self.db.execute(
            "INSERT INTO contacts(key, name, org, photo, handles, source) VALUES (?1, ?2, ?3, ?4, ?5, ?6)
             ON CONFLICT(key) DO UPDATE SET name = excluded.name, org = excluded.org, handles = excluded.handles,
             source = excluded.source, photo = CASE WHEN excluded.photo != '' THEN excluded.photo ELSE photo END",
            params![c.key, c.name, c.org, c.photo, handles, c.source],
        )?;
        let id: i64 = self.db.query_row("SELECT id FROM contacts WHERE key = ?1", [&c.key], |r| r.get(0))?;
        self.db.execute("DELETE FROM contact_handles WHERE contact_id = ?1", [id])?;
        for h in &c.handles {
            self.db.execute(
                "INSERT OR IGNORE INTO contact_handles(handle_key, contact_id) VALUES (?1, ?2)",
                params![handle_key(h), id],
            )?;
        }
        Ok(id)
    }

    /// The person behind a handle: (name, photo), or the handle itself.
    pub fn who(&self, handle: &str) -> (String, String) {
        self.db
            .query_row(
                "SELECT c.name, c.photo FROM contact_handles h JOIN contacts c ON c.id = h.contact_id
                 WHERE h.handle_key = ?1 AND c.name != '' ORDER BY c.photo = '' LIMIT 1",
                [handle_key(handle)],
                |r| Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?)),
            )
            .unwrap_or_else(|_| (handle.to_string(), String::new()))
    }

    fn chat_json(&self, id: i64, name: String, handles: String, last_ms: i64, unread: i64, service: String) -> Value {
        let handles: Vec<String> = serde_json::from_str(&handles).unwrap_or_default();
        let people: Vec<(String, String)> = handles.iter().map(|h| self.who(h)).collect();
        let title = if !name.is_empty() {
            name
        } else if people.is_empty() {
            "Unknown".to_string()
        } else {
            people.iter().map(|p| p.0.clone()).collect::<Vec<_>>().join(", ")
        };
        let last: Option<(String, i64, String)> = self
            .db
            .query_row(
                "SELECT text, from_me, attachments FROM messages WHERE chat_id = ?1 ORDER BY date_ms DESC, id DESC LIMIT 1",
                [id],
                |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
            )
            .optional()
            .unwrap_or(None);
        let (last_text, last_from_me) = match last {
            Some((t, me, a)) if t.trim().is_empty() && a != "[]" => ("📷 Photo".to_string(), me != 0),
            Some((t, me, _)) => (t, me != 0),
            None => (String::new(), false),
        };
        json!({"id": id, "title": title, "handles": handles, "last_ms": last_ms, "unread": unread, "service": service,
               "photo": if people.len() == 1 { people[0].1.clone() } else { String::new() },
               "group": handles.len() > 1, "last_text": last_text, "last_from_me": last_from_me})
    }

    pub fn chats(&self, limit: i64, offset: i64) -> rusqlite::Result<Vec<Value>> {
        let mut st = self.db.prepare(
            "SELECT id, name, handles, last_ms, unread, service FROM chats ORDER BY last_ms DESC LIMIT ?1 OFFSET ?2",
        )?;
        let rows = st.query_map(params![limit, offset], |r| {
            Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?, r.get(4)?, r.get(5)?))
        })?;
        let mut out = vec![];
        for row in rows {
            let (id, name, handles, last, unread, service) = row?;
            out.push(self.chat_json(id, name, handles, last, unread, service));
        }
        Ok(out)
    }

    fn message_json(&self, r: &rusqlite::Row) -> rusqlite::Result<Value> {
        let handle: String = r.get("handle")?;
        let from_me: bool = r.get("from_me")?;
        let (name, _) = if from_me { ("Me".to_string(), String::new()) } else { self.who(&handle) };
        let attachments: String = r.get("attachments")?;
        Ok(json!({"id": r.get::<_, i64>("id")?, "chat_id": r.get::<_, i64>("chat_id")?, "handle": handle,
                  "sender": name, "from_me": from_me, "date_ms": r.get::<_, i64>("date_ms")?,
                  "text": r.get::<_, String>("text")?, "service": r.get::<_, String>("service")?,
                  "source": r.get::<_, String>("source")?, "status": r.get::<_, String>("status")?,
                  "attachments": serde_json::from_str::<Value>(&attachments).unwrap_or(json!([]))}))
    }

    /// A chat's messages before a time (0: the latest), oldest first.
    pub fn messages(&self, chat: i64, before_ms: i64, limit: i64) -> rusqlite::Result<Vec<Value>> {
        let before = if before_ms <= 0 { i64::MAX } else { before_ms };
        let mut st = self.db.prepare(
            "SELECT * FROM messages WHERE chat_id = ?1 AND date_ms < ?2 ORDER BY date_ms DESC, id DESC LIMIT ?3",
        )?;
        let mut out = vec![];
        let mut rows = st.query(params![chat, before, limit])?;
        while let Some(r) = rows.next()? {
            out.push(self.message_json(r)?);
        }
        out.reverse();
        Ok(out)
    }

    pub fn mark_read(&self, chat: i64) -> rusqlite::Result<()> {
        self.db.execute("UPDATE chats SET unread = 0 WHERE id = ?1", [chat])?;
        Ok(())
    }

    /// Messages, chats and contacts that match, best first.
    pub fn search(&self, text: &str, limit: i64) -> rusqlite::Result<Value> {
        let q = fts_query(text);
        if q.is_empty() {
            return Ok(json!({"messages": [], "contacts": [], "chats": []}));
        }
        let mut st = self.db.prepare(
            "SELECT m.*, snippet(messages_fts, 0, ?2, ?3, '…', 14) AS snip FROM messages_fts
             JOIN messages m ON m.id = messages_fts.rowid WHERE messages_fts MATCH ?1
             ORDER BY bm25(messages_fts), m.date_ms DESC LIMIT ?4",
        )?;
        let mut messages = vec![];
        let mut rows = st.query(params![q, HIGHLIGHT_START, HIGHLIGHT_END, limit])?;
        while let Some(r) = rows.next()? {
            let mut m = self.message_json(r)?;
            m["snippet"] = json!(r.get::<_, String>("snip")?);
            messages.push(m);
        }
        let mut contacts = vec![];
        let mut st = self.db.prepare(
            "SELECT c.id, c.name, c.org, c.photo, c.handles FROM contacts_fts JOIN contacts c ON c.id = contacts_fts.rowid
             WHERE contacts_fts MATCH ?1 ORDER BY bm25(contacts_fts) LIMIT ?2",
        )?;
        let rows = st.query_map(params![q, limit], |r| {
            Ok(json!({"id": r.get::<_, i64>(0)?, "name": r.get::<_, String>(1)?, "org": r.get::<_, String>(2)?,
                      "photo": r.get::<_, String>(3)?,
                      "handles": serde_json::from_str::<Value>(&r.get::<_, String>(4)?).unwrap_or(json!([]))}))
        })?;
        for row in rows {
            contacts.push(row?);
        }
        // Chats whose title (a group's name, or its people) matches every word.
        let words: Vec<String> = text.split_whitespace().map(|w| w.to_lowercase()).collect();
        let chats: Vec<Value> = self
            .chats(500, 0)?
            .into_iter()
            .filter(|c| {
                let title = c["title"].as_str().unwrap_or("").to_lowercase();
                words.iter().all(|w| title.contains(w.as_str()))
            })
            .take(limit as usize)
            .collect();
        Ok(json!({"messages": messages, "contacts": contacts, "chats": chats}))
    }

    pub fn contacts(&self, limit: i64) -> rusqlite::Result<Vec<Value>> {
        let mut st = self.db.prepare(
            "SELECT id, name, org, photo, handles FROM contacts WHERE name != '' ORDER BY name COLLATE NOCASE LIMIT ?1",
        )?;
        let rows = st.query_map([limit], |r| {
            Ok(json!({"id": r.get::<_, i64>(0)?, "name": r.get::<_, String>(1)?, "org": r.get::<_, String>(2)?,
                      "photo": r.get::<_, String>(3)?,
                      "handles": serde_json::from_str::<Value>(&r.get::<_, String>(4)?).unwrap_or(json!([]))}))
        })?;
        rows.collect()
    }

    /// The chat with one person (made if new): where "new message to X" goes.
    pub fn chat_for(&self, handle: &str) -> rusqlite::Result<i64> {
        self.chat_id(&format!("h:{}", handle_key(handle)), "", "", &[handle.to_string()])
    }

    pub fn stats(&self) -> rusqlite::Result<Value> {
        let count = |sql: &str| -> rusqlite::Result<i64> { self.db.query_row(sql, [], |r| r.get(0)) };
        Ok(json!({"chats": count("SELECT count(*) FROM chats")?, "messages": count("SELECT count(*) FROM messages")?,
                  "contacts": count("SELECT count(*) FROM contacts")?}))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn msg(handle: &str, text: &str, date: i64, source: &str) -> NewMessage {
        NewMessage { handle: handle.into(), text: text.into(), date_ms: date, source: source.into(), ..Default::default() }
    }

    #[test]
    fn one_chat_per_person_and_no_duplicates() {
        let s = Store::open(":memory:").unwrap();
        assert!(s.add_message(&msg("+1 555 010 2030", "pizza tonight?", 1_000_000, "map")).unwrap());
        // The same message from the next backup: kept once, with the backup's id.
        let mut b = msg("5550102030", "pizza tonight?", 1_030_000, "backup");
        b.guid = "ABC".into();
        assert!(!s.add_message(&b).unwrap());
        assert!(s.add_message(&msg("5550102030", "sure", 1_100_000, "map")).unwrap());
        let chats = s.chats(10, 0).unwrap();
        assert_eq!(chats.len(), 1);
        assert_eq!(chats[0]["last_text"], "sure");
        assert_eq!(chats[0]["unread"], 2);
        let ms = s.messages(chats[0]["id"].as_i64().unwrap(), 0, 10).unwrap();
        assert_eq!(ms.len(), 2);
        assert_eq!(ms[0]["source"], "backup");
    }

    #[test]
    fn names_and_search() {
        let s = Store::open(":memory:").unwrap();
        s.upsert_contact(&NewContact { key: "ab:1".into(), name: "Ann Lee".into(), handles: vec!["+15550102030".into()], ..Default::default() }).unwrap();
        s.add_message(&msg("555-010-2030", "Meet at the café near the station", 5, "map")).unwrap();
        s.add_message(&msg("555-999-0000", "unrelated", 6, "map")).unwrap();
        let chats = s.chats(10, 0).unwrap();
        assert!(chats.iter().any(|c| c["title"] == "Ann Lee"));
        let found = s.search("cafe stat", 10).unwrap();
        assert_eq!(found["messages"].as_array().unwrap().len(), 1, "accents and prefixes");
        assert_eq!(found["messages"][0]["sender"], "Ann Lee");
        assert!(found["messages"][0]["snippet"].as_str().unwrap().contains("\u{2}café\u{3}"));
        assert_eq!(s.search("ann", 10).unwrap()["contacts"][0]["name"], "Ann Lee");
        assert_eq!(s.search("lee", 10).unwrap()["chats"][0]["title"], "Ann Lee");
        assert_eq!(fts_query("hi \"there\" -x"), "\"hi\"* \"there\"* \"x\"*");
    }
}
