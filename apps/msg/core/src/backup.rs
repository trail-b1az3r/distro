//! Importing an iPhone's messages and contacts from a local backup (made over USB by idevicebackup2), or from a
//! Mac's Messages database (chat.db, the same schema).
//!
//! A backup keeps each file under the SHA-1 of "<domain>-<path>", in a folder named after its first two hex digits
//! (older backups: flat). The messages are HomeDomain's Library/SMS/sms.db; their pictures are MediaDomain's
//! Library/SMS/Attachments/...; the contacts are HomeDomain's Library/AddressBook/AddressBook.sqlitedb (photos in
//! AddressBookImages.sqlitedb). Encrypted backups cannot be read: the app makes unencrypted ones.

use std::collections::HashMap;
use std::fs;
use std::path::{Path, PathBuf};

use rusqlite::{params, Connection, OpenFlags, OptionalExtension};
use serde_json::{json, Value};

use crate::store::{NewContact, NewMessage, Store};
use crate::typedstream::attributed_text;
use crate::util::{apple_date_ms, attachment_backup_path, backup_file_id, handle_key};

pub enum Files {
    /// An iPhone backup folder.
    Backup(PathBuf),
    /// A folder that "~/" in attachment paths means (a Mac's home), or none.
    Home(Option<PathBuf>),
}

impl Files {
    pub fn find(&self, domain: &str, relative: &str) -> Option<PathBuf> {
        match self {
            Files::Backup(dir) => {
                let id = backup_file_id(domain, relative);
                [dir.join(&id[..2]).join(&id), dir.join(&id)].into_iter().find(|p| p.is_file())
            }
            Files::Home(Some(home)) => Some(home.join(relative)).filter(|p| p.is_file()),
            Files::Home(None) => None,
        }
    }
}

fn open_ro(path: &Path) -> rusqlite::Result<Connection> {
    Connection::open_with_flags(path, OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX)
}

fn columns(db: &Connection, table: &str) -> rusqlite::Result<Vec<String>> {
    let mut st = db.prepare(&format!("PRAGMA table_info({table})"))?;
    let names = st.query_map([], |r| r.get::<_, String>(1))?.collect::<Result<Vec<_>, _>>()?;
    Ok(names)
}

/// Copies an attachment into the store's folder (backups get deleted and replaced); returns where it is.
fn keep_attachment(files: &Files, filename: &str, name: &str, into: &Path) -> Option<PathBuf> {
    let (domain, relative) = attachment_backup_path(filename)?;
    let source = files.find(&domain, &relative)?;
    let dir = into.join(&backup_file_id(&domain, &relative)[..12]);
    let base = Path::new(if name.is_empty() { relative.as_str() } else { name }).file_name()?.to_owned();
    let dest = dir.join(base);
    if !dest.exists() {
        fs::create_dir_all(&dir).ok()?;
        fs::copy(&source, &dest).ok()?;
    }
    Some(dest)
}

/// Imports every message of an sms.db (or chat.db). Returns (messages added, messages seen).
pub fn import_messages(store: &Store, sms: &Path, files: &Files, attachments_dir: &Path) -> rusqlite::Result<(u64, u64)> {
    let db = open_ro(sms)?;
    let cols = columns(&db, "message")?;
    let has = |c: &str| cols.iter().any(|x| x == c);
    let body = if has("attributedBody") { "m.attributedBody" } else { "NULL" };
    let reaction_filter = if has("associated_message_type") { "AND ifnull(m.associated_message_type, 0) = 0" } else { "" };

    // Each chat's people.
    let mut chat_handles: HashMap<i64, Vec<String>> = HashMap::new();
    {
        let mut st = db.prepare("SELECT chj.chat_id, h.id FROM chat_handle_join chj JOIN handle h ON h.ROWID = chj.handle_id")?;
        let rows = st.query_map([], |r| Ok((r.get::<_, i64>(0)?, r.get::<_, String>(1)?)))?;
        for row in rows {
            let (chat, handle) = row?;
            chat_handles.entry(chat).or_default().push(handle);
        }
    }
    let mut attach_st = db.prepare(
        "SELECT ifnull(a.filename, ''), ifnull(a.mime_type, ''), ifnull(a.transfer_name, '') FROM message_attachment_join maj
         JOIN attachment a ON a.ROWID = maj.attachment_id WHERE maj.message_id = ?1",
    )?;
    let sql = format!(
        "SELECT m.ROWID, m.guid, m.text, {body}, m.is_from_me, m.date, ifnull(m.service, ''), ifnull(h.id, ''),
                c.ROWID, ifnull(c.guid, ''), ifnull(c.display_name, ''), ifnull(c.chat_identifier, '')
         FROM message m LEFT JOIN handle h ON h.ROWID = m.handle_id
         LEFT JOIN chat_message_join cmj ON cmj.message_id = m.ROWID LEFT JOIN chat c ON c.ROWID = cmj.chat_id
         WHERE 1 {reaction_filter} ORDER BY m.date"
    );
    let mut st = db.prepare(&sql)?;
    let mut rows = st.query([])?;
    let (mut added, mut seen) = (0u64, 0u64);
    store.db.execute_batch("BEGIN")?;
    while let Some(r) = rows.next()? {
        seen += 1;
        let rowid: i64 = r.get(0)?;
        let text: Option<String> = r.get(2)?;
        let blob: Option<Vec<u8>> = r.get(3)?;
        let mut text = text.filter(|t| !t.is_empty()).or_else(|| blob.as_deref().and_then(attributed_text)).unwrap_or_default();
        text = text.replace('\u{FFFC}', "").trim().to_string();
        let chat_row: Option<i64> = r.get(8)?;
        let handle: String = r.get(7)?;
        let identifier: String = r.get(11)?;
        let people = chat_row.and_then(|c| chat_handles.get(&c).cloned()).unwrap_or_else(|| {
            let h = if handle.is_empty() { identifier.clone() } else { handle.clone() };
            if h.is_empty() { vec![] } else { vec![h] }
        });
        let chat_key = if people.len() > 1 {
            format!("g:{}", r.get::<_, String>(9)?)
        } else {
            format!("h:{}", handle_key(people.first().map(String::as_str).unwrap_or(&identifier)))
        };
        let mut attachments = vec![];
        let mut a = attach_st.query(params![rowid])?;
        while let Some(ar) = a.next()? {
            let (filename, mime, name): (String, String, String) = (ar.get(0)?, ar.get(1)?, ar.get(2)?);
            let kept = keep_attachment(files, &filename, &name, attachments_dir);
            attachments.push(json!({"path": kept.map(|p| p.to_string_lossy().into_owned()).unwrap_or_default(),
                                    "mime": mime, "name": name}));
        }
        if text.is_empty() && attachments.is_empty() {
            continue;
        }
        let from_me: bool = r.get::<_, i64>(4)? != 0;
        let m = NewMessage {
            guid: r.get(1)?,
            chat_key,
            chat_name: r.get(10)?,
            chat_handles: people.clone(),
            handle: if handle.is_empty() && !from_me { people.first().cloned().unwrap_or_default() } else { handle },
            from_me,
            date_ms: apple_date_ms(r.get::<_, Option<i64>>(5)?.unwrap_or(0)),
            text,
            service: r.get(6)?,
            source: "backup".into(),
            attachments,
            status: String::new(),
        };
        if store.add_message(&m)? {
            added += 1;
        }
    }
    store.db.execute_batch("COMMIT")?;
    Ok((added, seen))
}

/// Imports the address book (and its photos, when the images database is given). Returns the people imported.
pub fn import_contacts(store: &Store, book: &Path, images: Option<&Path>, photos_dir: &Path) -> rusqlite::Result<u64> {
    let db = open_ro(book)?;
    let mut handles: HashMap<i64, Vec<String>> = HashMap::new();
    {
        // property 3: phone numbers, 4: email addresses.
        let mut st = db.prepare("SELECT record_id, value FROM ABMultiValue WHERE property IN (3, 4) AND value IS NOT NULL")?;
        let rows = st.query_map([], |r| Ok((r.get::<_, i64>(0)?, r.get::<_, String>(1)?)))?;
        for row in rows {
            let (id, value) = row?;
            handles.entry(id).or_default().push(value);
        }
    }
    let images = images.and_then(|p| open_ro(p).ok());
    let mut st = db.prepare(
        "SELECT ROWID, ifnull(First, ''), ifnull(Last, ''), ifnull(Organization, ''), ifnull(Nickname, '') FROM ABPerson",
    )?;
    let rows = st.query_map([], |r| {
        Ok((r.get::<_, i64>(0)?, r.get::<_, String>(1)?, r.get::<_, String>(2)?, r.get::<_, String>(3)?, r.get::<_, String>(4)?))
    })?;
    let mut count = 0;
    store.db.execute_batch("BEGIN")?;
    for row in rows {
        let (id, first, last, org, nick) = row?;
        let mut name = format!("{first} {last}").trim().to_string();
        if name.is_empty() {
            name = if !nick.is_empty() { nick } else { org.clone() };
        }
        let mut photo = String::new();
        if let Some(img) = &images {
            let data: Option<Vec<u8>> = img
                .query_row("SELECT data FROM ABFullSizeImage WHERE record_id = ?1", [id], |r| r.get(0))
                .optional()
                .unwrap_or(None);
            if let Some(data) = data.filter(|d| !d.is_empty()) {
                let _ = fs::create_dir_all(photos_dir);
                let path = photos_dir.join(format!("ab-{id}.jpg"));
                if fs::write(&path, data).is_ok() {
                    photo = path.to_string_lossy().into_owned();
                }
            }
        }
        store.upsert_contact(&NewContact {
            key: format!("ab:{id}"),
            name,
            org,
            photo,
            handles: handles.remove(&id).unwrap_or_default(),
            source: "backup".into(),
        })?;
        count += 1;
    }
    store.db.execute_batch("COMMIT")?;
    Ok(count)
}

/// A whole backup: messages, then contacts. `data` is where the store keeps attachments and photos.
pub fn import_backup(store: &Store, backup: &Path, data: &Path) -> Result<Value, String> {
    let files = Files::Backup(backup.to_path_buf());
    if backup.join("Manifest.plist").is_file() {
        let manifest = fs::read(backup.join("Manifest.plist")).unwrap_or_default();
        let text = String::from_utf8_lossy(&manifest);
        if text.contains("<key>IsEncrypted</key>") && text.contains("<key>IsEncrypted</key>\n\t<true/>") {
            return Err("this backup is encrypted; frontline-msg makes and reads unencrypted backups (turn off \
                        \"Encrypt local backup\": idevicebackup2 encryption off PASSWORD)".into());
        }
    }
    let sms = files
        .find("HomeDomain", "Library/SMS/sms.db")
        .ok_or("no messages in this backup (Library/SMS/sms.db is missing)")?;
    let (added, seen) =
        import_messages(store, &sms, &files, &data.join("attachments")).map_err(|e| format!("messages: {e}"))?;
    let mut people = 0;
    if let Some(book) = files.find("HomeDomain", "Library/AddressBook/AddressBook.sqlitedb") {
        let images = files.find("HomeDomain", "Library/AddressBook/AddressBookImages.sqlitedb");
        people = import_contacts(store, &book, images.as_deref(), &data.join("photos")).map_err(|e| format!("contacts: {e}"))?;
    }
    Ok(json!({"added": added, "seen": seen, "contacts": people}))
}
