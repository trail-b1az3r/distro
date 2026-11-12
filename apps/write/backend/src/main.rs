//! JSON-lines backend for Nexora Write.
//!
//! The Qt Quick process owns presentation. Application operations are handled
//! here in Rust; each input line is one request and each output line one reply.
use serde::{Deserialize, Serialize};
use std::fs;
use std::io::{self, BufRead, Write};
use std::path::{Path, PathBuf};

#[derive(Debug, Deserialize)]
#[serde(tag = "op", rename_all = "snake_case")]
enum Request {
    Read { path: PathBuf },
    Write { path: PathBuf, content: String },
    WordCount { text: String },
    List { path: PathBuf },
    CreateNote { root: PathBuf, title: String },
    CreateBook { root: PathBuf, title: String },
    CreateChapter { book: PathBuf, title: String },
    ImportImage { source: PathBuf, book: PathBuf },
}

#[derive(Debug, Serialize)]
struct Reply<T: Serialize> {
    ok: bool,
    result: Option<T>,
    error: Option<String>,
}

fn reply(result: Result<serde_json::Value, String>) -> String {
    let value = match result {
        Ok(value) => Reply { ok: true, result: Some(value), error: None },
        Err(error) => Reply { ok: false, result: None, error: Some(error) },
    };
    serde_json::to_string(&value).unwrap_or_else(|_| r#"{"ok":false,"result":null,"error":"serialization failure"}"#.into())
}

fn slug(input: &str) -> String {
    let mut out = String::new();
    let mut separator = false;
    for ch in input.trim().chars() {
        if ch.is_alphanumeric() {
            if separator && !out.is_empty() { out.push('-'); }
            for lower in ch.to_lowercase() { out.push(lower); }
            separator = false;
        } else {
            separator = true;
        }
    }
    if out.is_empty() { "untitled".into() } else { out }
}

fn unique_file(root: &Path, stem: &str, extension: &str) -> PathBuf {
    let mut candidate = root.join(format!("{stem}.{extension}"));
    let mut index = 2;
    while candidate.exists() {
        candidate = root.join(format!("{stem}-{index}.{extension}"));
        index += 1;
    }
    candidate
}

fn create_note(root: &Path, title: &str) -> Result<String, String> {
    fs::create_dir_all(root).map_err(|e| e.to_string())?;
    let path = unique_file(root, &slug(title), "mdxl");
    fs::write(&path, format!("# {}\n\n", title.trim())).map_err(|e| e.to_string())?;
    Ok(path.to_string_lossy().into_owned())
}

fn create_book(root: &Path, title: &str) -> Result<String, String> {
    fs::create_dir_all(root).map_err(|e| e.to_string())?;
    let mut dir = root.join(slug(title));
    let mut index = 2;
    while dir.exists() {
        dir = root.join(format!("{}-{index}", slug(title)));
        index += 1;
    }
    fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
    fs::create_dir_all(dir.join("images")).map_err(|e| e.to_string())?;
    fs::write(dir.join("00-About.mdxl"),
        format!("# {}\n\n-# A book written in MDXL. Each chapter is a file in this folder.\n", title.trim()))
        .map_err(|e| e.to_string())?;
    fs::write(dir.join("01-Chapter-one.mdxl"), "## Chapter one\n\n")
        .map_err(|e| e.to_string())?;
    Ok(dir.to_string_lossy().into_owned())
}

fn create_chapter(book: &Path, title: &str) -> Result<String, String> {
    fs::create_dir_all(book).map_err(|e| e.to_string())?;
    let count = fs::read_dir(book).map_err(|e| e.to_string())?
        .filter_map(Result::ok)
        .filter(|entry| entry.path().extension().is_some_and(|ext| ext == "mdxl"))
        .count();
    let path = book.join(format!("{count:02}-{}.mdxl", slug(title)));
    fs::write(&path, format!("# {}\n\n", title.trim())).map_err(|e| e.to_string())?;
    Ok(path.to_string_lossy().into_owned())
}

fn import_image(source: &Path, book: &Path) -> Result<String, String> {
    let extension = source.extension().and_then(|value| value.to_str())
        .ok_or_else(|| "image has no file extension".to_string())?.to_ascii_lowercase();
    if !["png", "jpg", "jpeg", "webp", "gif", "svg", "avif", "bmp"].contains(&extension.as_str()) {
        return Err("unsupported image format".into());
    }
    let original = source.file_stem().and_then(|value| value.to_str())
        .ok_or_else(|| "invalid image filename".to_string())?;
    let images = book.join("images");
    fs::create_dir_all(&images).map_err(|e| e.to_string())?;
    let mut target = images.join(format!("{original}.{extension}"));
    let mut index = 2;
    while target.exists() {
        target = images.join(format!("{original}-{index}.{extension}"));
        index += 1;
    }
    fs::copy(source, &target).map_err(|e| e.to_string())?;
    let filename = target.file_name().and_then(|value| value.to_str())
        .ok_or_else(|| "invalid destination filename".to_string())?;
    Ok(format!("images/{filename}"))
}

fn handle(request: Request) -> Result<serde_json::Value, String> {
    match request {
        Request::Read { path } => fs::read_to_string(path).map(serde_json::Value::String).map_err(|e| e.to_string()),
        Request::Write { path, content } => {
            if let Some(parent) = path.parent() { fs::create_dir_all(parent).map_err(|e| e.to_string())?; }
            let temporary = path.with_extension("mdxl.tmp");
            fs::write(&temporary, content).map_err(|e| e.to_string())?;
            fs::rename(&temporary, &path).map_err(|e| e.to_string())?;
            Ok(serde_json::Value::Bool(true))
        }
        Request::WordCount { text } => {
            let count = text.split_whitespace().filter(|word| word.chars().any(char::is_alphanumeric)).count();
            Ok(serde_json::json!(count))
        }
        Request::List { path } => {
            let mut entries = Vec::new();
            for entry in fs::read_dir(path).map_err(|e| e.to_string())? {
                let entry = entry.map_err(|e| e.to_string())?;
                let metadata = entry.metadata().map_err(|e| e.to_string())?;
                entries.push(serde_json::json!({
                    "path": entry.path().to_string_lossy(),
                    "name": entry.file_name().to_string_lossy(),
                    "directory": metadata.is_dir(),
                    "modified": metadata.modified().ok().and_then(|t| t.duration_since(std::time::UNIX_EPOCH).ok()).map(|d| d.as_secs())
                }));
            }
            entries.sort_by(|a, b| a["name"].as_str().cmp(&b["name"].as_str()));
            Ok(serde_json::Value::Array(entries))
        }
        Request::CreateNote { root, title } => create_note(&root, &title).map(serde_json::Value::String),
        Request::CreateBook { root, title } => create_book(&root, &title).map(serde_json::Value::String),
        Request::CreateChapter { book, title } => create_chapter(&book, &title).map(serde_json::Value::String),
        Request::ImportImage { source, book } => import_image(&source, &book).map(serde_json::Value::String),
    }
}

fn main() {
    let stdin = io::stdin();
    let mut stdout = io::BufWriter::new(io::stdout().lock());
    for line in stdin.lock().lines() {
        let response = match line {
            Ok(line) => match serde_json::from_str::<Request>(&line) {
                Ok(request) => reply(handle(request)),
                Err(error) => reply(Err(format!("invalid request: {error}"))),
            },
            Err(error) => reply(Err(error.to_string())),
        };
        if writeln!(stdout, "{response}").is_err() { break; }
        if stdout.flush().is_err() { break; }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn slug_is_safe_and_stable() {
        assert_eq!(slug("My First Book!"), "my-first-book");
        assert_eq!(slug("   "), "untitled");
    }

    #[test]
    fn word_count_ignores_whitespace_only_tokens() {
        let request = Request::WordCount { text: "hello, world!  \n  ".into() };
        assert_eq!(handle(request).unwrap(), serde_json::json!(2));
    }

    #[test]
    fn creates_unique_notes() {
        let root = std::env::temp_dir().join(format!("nexora-write-test-{}", std::process::id()));
        let _ = fs::remove_dir_all(&root);
        let first = create_note(&root, "Draft").unwrap();
        let second = create_note(&root, "Draft").unwrap();
        assert_ne!(first, second);
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn creates_book_with_first_chapter_and_sequential_followup() {
        let root = std::env::temp_dir().join(format!("nexora-write-book-test-{}", std::process::id()));
        let _ = fs::remove_dir_all(&root);
        let book = PathBuf::from(create_book(&root, "A Test Book").unwrap());
        assert!(book.join("00-About.mdxl").exists());
        assert!(book.join("01-Chapter-one.mdxl").exists());
        assert!(book.join("images").is_dir());
        let next = PathBuf::from(create_chapter(&book, "Second chapter").unwrap());
        assert_eq!(next.file_name().unwrap(), "02-second-chapter.mdxl");
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn imports_images_into_book_assets() {
        let root = std::env::temp_dir().join(format!("nexora-write-image-test-{}", std::process::id()));
        let _ = fs::remove_dir_all(&root);
        let book = root.join("book");
        let source = root.join("cover.png");
        fs::create_dir_all(&root).unwrap();
        fs::write(&source, b"not-a-real-png-but-a-copy-test").unwrap();
        assert_eq!(import_image(&source, &book).unwrap(), "images/cover.png");
        assert!(book.join("images/cover.png").exists());
        assert!(import_image(&source, &book).unwrap().contains("cover-2.png"));
        fs::remove_dir_all(root).unwrap();
    }
}
