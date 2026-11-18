//! nexora-msg-core: nexora-msg's store. Run as a service (`serve STORE`: one JSON request per line on stdin, one
//! JSON reply per line on stdout), or once (`nexora-msg-core STORE OP [JSON]`).

mod backup;
mod store;
mod typedstream;
mod util;

use std::io::{BufRead, Write};
use std::path::{Path, PathBuf};

use serde_json::{json, Value};

use store::{NewContact, NewMessage, Store};

fn data_dir(store_path: &str) -> PathBuf {
    Path::new(store_path).parent().map(Path::to_path_buf).unwrap_or_else(|| PathBuf::from("."))
}

fn arg<'a>(req: &'a Value, key: &str) -> Result<&'a str, String> {
    req[key].as_str().ok_or_else(|| format!("'{key}' is missing"))
}

fn handle(store: &Store, store_path: &str, req: &Value) -> Result<Value, String> {
    let e = |err: rusqlite::Error| err.to_string();
    let int = |key: &str, default: i64| req[key].as_i64().unwrap_or(default);
    match req["op"].as_str().unwrap_or("") {
        "stats" => store.stats().map_err(e),
        "chats" => Ok(json!(store.chats(int("limit", 200), int("offset", 0)).map_err(e)?)),
        "messages" => Ok(json!(store.messages(int("chat", 0), int("before", 0), int("limit", 80)).map_err(e)?)),
        "mark-read" => store.mark_read(int("chat", 0)).map(|_| json!(true)).map_err(e),
        "search" => store.search(arg(req, "query")?, int("limit", 50)).map_err(e),
        "contacts" => Ok(json!(store.contacts(int("limit", 5000)).map_err(e)?)),
        "chat-for" => Ok(json!(store.chat_for(arg(req, "handle")?).map_err(e)?)),
        "add-messages" => {
            let list: Vec<NewMessage> = serde_json::from_value(req["messages"].clone()).map_err(|x| x.to_string())?;
            let mut added = vec![];
            for m in &list {
                if store.add_message(m).map_err(e)? {
                    added.push(m.guid.clone());
                }
            }
            Ok(json!({"added": added.len()}))
        }
        "add-contacts" => {
            let list: Vec<NewContact> = serde_json::from_value(req["contacts"].clone()).map_err(|x| x.to_string())?;
            for c in &list {
                store.upsert_contact(c).map_err(e)?;
            }
            Ok(json!({"contacts": list.len()}))
        }
        "import-backup" => backup::import_backup(store, Path::new(arg(req, "backup")?), &data_dir(store_path)),
        "import-chatdb" => {
            // A Mac's ~/Library/Messages/chat.db, with its home folder for the attachments.
            let files = backup::Files::Home(req["home"].as_str().map(PathBuf::from));
            let (added, seen) = backup::import_messages(store, Path::new(arg(req, "path")?), &files,
                                                        &data_dir(store_path).join("attachments")).map_err(e)?;
            Ok(json!({"added": added, "seen": seen}))
        }
        "ping" => Ok(json!(env!("CARGO_PKG_VERSION"))),
        other => Err(format!("unknown request '{other}'")),
    }
}

fn reply(store: &Store, path: &str, req: &Value) -> Value {
    let id = req.get("id").cloned().unwrap_or(Value::Null);
    match handle(store, path, req) {
        Ok(data) => json!({"id": id, "ok": true, "data": data}),
        Err(error) => json!({"id": id, "ok": false, "error": error}),
    }
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    if args.len() < 3 {
        eprintln!("usage: nexora-msg-core serve STORE | nexora-msg-core STORE OP [JSON]");
        std::process::exit(2);
    }
    if args[1] == "serve" {
        let path = &args[2];
        let store = match Store::open(path) {
            Ok(s) => s,
            Err(err) => {
                eprintln!("nexora-msg-core: {path}: {err}");
                std::process::exit(1);
            }
        };
        let stdin = std::io::stdin();
        let mut out = std::io::stdout().lock();
        for line in stdin.lock().lines() {
            let Ok(line) = line else { break };
            if line.trim().is_empty() {
                continue;
            }
            let answer = match serde_json::from_str::<Value>(&line) {
                Ok(req) => reply(&store, path, &req),
                Err(err) => json!({"ok": false, "error": format!("not JSON: {err}")}),
            };
            let _ = writeln!(out, "{answer}");
            let _ = out.flush();
        }
        return;
    }
    let path = &args[1];
    let store = Store::open(path).unwrap_or_else(|err| {
        eprintln!("nexora-msg-core: {path}: {err}");
        std::process::exit(1)
    });
    let mut req: Value = args.get(3).map(|s| serde_json::from_str(s).unwrap_or(json!({}))).unwrap_or(json!({}));
    req["op"] = json!(args[2]);
    let answer = reply(&store, path, &req);
    println!("{}", serde_json::to_string_pretty(&answer).unwrap());
    std::process::exit(if answer["ok"] == json!(true) { 0 } else { 1 });
}
