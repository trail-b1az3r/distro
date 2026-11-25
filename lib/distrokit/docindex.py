"""Local document indexing and retrieval (`frontline docs`).

Your documents are read where they are (by default ~/Documents, ~/Desktop, ~/Downloads and ~/Notes), cut into
passages of about a paragraph or two, and kept in a SQLite full-text index (FTS5, BM25 ranking) in
~/.local/share/<id>/docs.sqlite. Nothing leaves the computer: search, the picker and the passages handed to the local
model (`docs ask`, which needs `frontline model serve`) all read that file.

Indexing is incremental: a file is read again only when its size or modification time changed, and files that are
gone are dropped. A user timer runs it every half hour (`docs on|off`).

Readable: plain text and source-like files (Markdown, MDXL, reStructuredText, Org, LaTeX, CSV...), HTML, PDF (with
poppler's pdftotext), Word (.docx), OpenDocument (.odt, .ods, .odp), EPUB, PowerPoint (.pptx) and Excel (.xlsx).
"""
from __future__ import annotations

import html
import json
import os
import re
import shutil
import sqlite3
import subprocess
import time
import zipfile
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable, Iterable, Iterator

TEXT_EXTENSIONS = {
    ".txt", ".text", ".md", ".markdown", ".mdxl", ".rst", ".org", ".tex", ".adoc", ".asciidoc", ".csv", ".tsv",
    ".log", ".nfo", ".rtf", ".json", ".yaml", ".yml", ".toml", ".ini", ".conf",
}
HTML_EXTENSIONS = {".html", ".htm", ".xhtml"}
ZIP_EXTENSIONS = {".docx", ".odt", ".ods", ".odp", ".epub", ".pptx", ".xlsx"}
SUPPORTED = TEXT_EXTENSIONS | HTML_EXTENSIONS | ZIP_EXTENSIONS | {".pdf"}

# Folders never worth reading: version control, caches, build trees, dependency trees.
SKIP_DIRS = {".git", ".hg", ".svn", "node_modules", "__pycache__", ".cache", ".venv", "venv", "target", "build",
             "dist", ".tox", ".mypy_cache", ".pytest_cache", "Trash"}
MAX_FILE_BYTES = 40 * 1024 * 1024     # bigger files are skipped
MAX_TEXT_CHARS = 2_000_000            # the first 2 MB of a document's text is indexed
CHUNK_CHARS = 1400                    # a passage: about a paragraph or two
DEFAULT_ROOTS = ("Documents", "Desktop", "Downloads", "Notes")

SCHEMA = """
CREATE TABLE IF NOT EXISTS files(
    id INTEGER PRIMARY KEY, path TEXT UNIQUE NOT NULL, mtime REAL NOT NULL, size INTEGER NOT NULL,
    kind TEXT NOT NULL, title TEXT NOT NULL, indexed REAL NOT NULL);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks USING fts5(
    title, body, file_id UNINDEXED, seq UNINDEXED, tokenize='unicode61 remove_diacritics 2');
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
"""


class DocIndexError(RuntimeError):
    """A docs command could not be carried out; the message says why."""


# ── Where things are ─────────────────────────────────────────────────────────────────────────────────────────────────

def _xdg(variable: str, fallback: str) -> Path:
    return Path(os.environ.get(variable) or Path.home() / fallback)


def db_path(app: str) -> Path:
    return _xdg("XDG_DATA_HOME", ".local/share") / app / "docs.sqlite"


def config_path(app: str) -> Path:
    return _xdg("XDG_CONFIG_HOME", ".config") / app / "docs.json"


@dataclass
class Config:
    roots: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)

    def root_paths(self) -> list[Path]:
        return [Path(os.path.expanduser(r)) for r in self.roots]


def load_config(app: str) -> Config:
    path = config_path(app)
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return Config(roots=list(data.get("roots", [])), exclude=list(data.get("exclude", [])))
        except (ValueError, OSError) as exc:
            raise DocIndexError(f"{path} is not valid JSON: {exc}") from exc
    home = Path.home()
    return Config(roots=[str(home / name) for name in DEFAULT_ROOTS])


def save_config(app: str, config: Config) -> None:
    path = config_path(app)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"roots": config.roots, "exclude": config.exclude}, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def connect(app: str) -> sqlite3.Connection:
    path = db_path(app)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    try:
        db.executescript(SCHEMA)
    except sqlite3.OperationalError as exc:  # an SQLite built without FTS5
        raise DocIndexError(f"SQLite has no full-text search here: {exc}") from exc
    return db


# ── Reading documents ────────────────────────────────────────────────────────────────────────────────────────────────

class _HtmlText(HTMLParser):
    BLOCKS = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "blockquote",
              "pre", "td", "th", "dt", "dd", "figcaption"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title = ""
        self._skip = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript", "svg"):
            self._skip += 1
        elif tag == "title":
            self._in_title = True
        elif tag in self.BLOCKS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "svg"):
            self._skip = max(0, self._skip - 1)
        elif tag == "title":
            self._in_title = False
        elif tag in self.BLOCKS:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip:
            self.parts.append(data)


def html_text(markup: str) -> tuple[str, str]:
    """(text, title) of an HTML document."""
    parser = _HtmlText()
    parser.feed(markup)
    parser.close()
    return "".join(parser.parts), parser.title.strip()


_XML_BREAKS = re.compile(r"</(?:w:p|text:p|text:h|a:p|si|row|table:table-row)>|<(?:w:br|w:tab|text:tab|text:line-break)\b[^>]*/>")
_XML_TAGS = re.compile(r"<[^>]+>")


def xml_text(xml: str) -> str:
    """The text of an office XML part, a line per paragraph."""
    return html.unescape(_XML_TAGS.sub("", _XML_BREAKS.sub("\n", xml)))


def _zip_parts(archive: zipfile.ZipFile, pattern: str) -> list[str]:
    def number(name: str) -> int:
        found = re.search(r"(\d+)\.xml$", name)
        return int(found.group(1)) if found else 0
    return sorted((n for n in archive.namelist() if re.fullmatch(pattern, n)), key=number)


def _epub_order(archive: zipfile.ZipFile) -> list[str]:
    """The chapters of an EPUB in reading order (its spine), else every XHTML file."""
    try:
        container = archive.read("META-INF/container.xml").decode("utf-8", "replace")
        opf_path = re.search(r'full-path="([^"]+)"', container).group(1)
        opf = archive.read(opf_path).decode("utf-8", "replace")
        base = os.path.dirname(opf_path)
        items = dict(re.findall(r'<item\b[^>]*\bid="([^"]+)"[^>]*\bhref="([^"]+)"', opf))
        items.update({k: v for v, k in re.findall(r'<item\b[^>]*\bhref="([^"]+)"[^>]*\bid="([^"]+)"', opf)})
        spine = re.findall(r'<itemref\b[^>]*\bidref="([^"]+)"', opf)
        names = [os.path.normpath(os.path.join(base, items[i])).replace(os.sep, "/") for i in spine if i in items]
        known = set(archive.namelist())
        ordered = [n for n in names if n in known]
        if ordered:
            return ordered
    except (KeyError, AttributeError):
        pass
    return sorted(n for n in archive.namelist() if n.endswith((".xhtml", ".html", ".htm")))


def extract(path: Path) -> tuple[str, str]:
    """(text, title) of a document; empty text when it cannot be read."""
    suffix = path.suffix.lower()
    title = ""
    if suffix in TEXT_EXTENSIONS:
        with path.open("rb") as handle:
            raw = handle.read(MAX_TEXT_CHARS * 2)
        if b"\0" in raw[:4096]:
            return "", ""          # binary after all
        text = raw.decode("utf-8", "replace")
        heading = re.search(r"^\s{0,3}#{1,2}\s+(.+?)\s*#*\s*$", text, re.M)
        title = heading.group(1) if heading and suffix in (".md", ".markdown", ".mdxl") else ""
    elif suffix in HTML_EXTENSIONS:
        text, title = html_text(path.read_text(encoding="utf-8", errors="replace")[: MAX_TEXT_CHARS * 2])
    elif suffix == ".pdf":
        tool = shutil.which("pdftotext")
        if not tool:
            return "", ""
        done = subprocess.run([tool, "-q", "-enc", "UTF-8", str(path), "-"], capture_output=True, timeout=120,
                              check=False)
        text = done.stdout.decode("utf-8", "replace")
    elif suffix in ZIP_EXTENSIONS:
        with zipfile.ZipFile(path) as archive:
            if suffix == ".docx":
                names = ["word/document.xml"] + _zip_parts(archive, r"word/(?:header|footer|footnotes)\d*\.xml")
            elif suffix in (".odt", ".ods", ".odp"):
                names = ["content.xml"]
            elif suffix == ".pptx":
                names = _zip_parts(archive, r"ppt/slides/slide\d+\.xml")
            elif suffix == ".xlsx":
                names = ["xl/sharedStrings.xml"]
            else:
                names = _epub_order(archive)
            parts = []
            for name in names:
                try:
                    data = archive.read(name).decode("utf-8", "replace")
                except KeyError:
                    continue
                if suffix == ".epub":
                    chapter, chapter_title = html_text(data)
                    parts.append(chapter)
                    title = title or chapter_title
                else:
                    parts.append(xml_text(data))
            text = "\n".join(parts)
            if suffix in (".docx", ".pptx", ".xlsx") and "docProps/core.xml" in archive.namelist():
                found = re.search(r"<dc:title>([^<]+)</dc:title>", archive.read("docProps/core.xml").decode("utf-8", "replace"))
                title = html.unescape(found.group(1)).strip() if found else ""
            elif suffix in (".odt", ".ods", ".odp") and "meta.xml" in archive.namelist():
                found = re.search(r"<dc:title>([^<]+)</dc:title>", archive.read("meta.xml").decode("utf-8", "replace"))
                title = html.unescape(found.group(1)).strip() if found else ""
    else:
        return "", ""
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
    return text[:MAX_TEXT_CHARS], title.strip()


def chunks(text: str, size: int = CHUNK_CHARS) -> list[str]:
    """Passages of about `size` characters, cut between paragraphs, else between sentences, else between words."""
    pieces: list[str] = []
    for paragraph in re.split(r"\n\s*\n", text):
        paragraph = paragraph.strip()
        while len(paragraph) > size:
            cut = max(paragraph.rfind(". ", 0, size), paragraph.rfind("\n", 0, size))
            if cut < size // 3:
                cut = paragraph.rfind(" ", 0, size)
            end = cut + 1 if cut >= size // 3 else size      # no break worth keeping: cut at the size itself
            pieces.append(paragraph[:end].strip())
            paragraph = paragraph[end:].strip()
        if paragraph:
            pieces.append(paragraph)
    out: list[str] = []
    for piece in pieces:
        if out and len(out[-1]) + len(piece) + 2 <= size:
            out[-1] += "\n\n" + piece
        else:
            out.append(piece)
    return out


# ── Indexing ─────────────────────────────────────────────────────────────────────────────────────────────────────────

@dataclass
class IndexStats:
    added: int = 0
    updated: int = 0
    unchanged: int = 0
    removed: int = 0
    unreadable: int = 0
    seconds: float = 0.0


def walk(config: Config) -> Iterator[Path]:
    excluded = [Path(os.path.expanduser(e)).resolve() for e in config.exclude]
    seen: set[Path] = set()
    for root in config.root_paths():
        if not root.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            here = Path(dirpath)
            dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in SKIP_DIRS
                           and not any((here / d).resolve() == e for e in excluded)]
            for name in filenames:
                path = here / name
                if name.startswith(".") or path.suffix.lower() not in SUPPORTED or path in seen:
                    continue
                if any(e in path.resolve().parents for e in excluded):
                    continue
                seen.add(path)
                yield path


def index(app: str, full: bool = False, progress: Callable[[Path], None] | None = None) -> IndexStats:
    """Bring the index up to date with the documents under the roots."""
    started = time.monotonic()
    config = load_config(app)
    stats = IndexStats()
    db = connect(app)
    known = {row[0]: (row[1], row[2], row[3]) for row in db.execute("SELECT path, id, mtime, size FROM files")}
    present: set[str] = set()
    try:
        for count, path in enumerate(walk(config), 1):
            try:
                st = path.stat()
            except OSError:
                continue
            key = str(path)
            present.add(key)
            if st.st_size > MAX_FILE_BYTES:
                continue
            old = known.get(key)
            if old and not full and old[1] == st.st_mtime and old[2] == st.st_size:
                stats.unchanged += 1
                continue
            if progress:
                progress(path)
            try:
                text, title = extract(path)
            except (OSError, zipfile.BadZipFile, subprocess.SubprocessError, ValueError, UnicodeError):
                text, title = "", ""
            if not text:
                stats.unreadable += 1
            title = title or path.stem.replace("_", " ")
            if old:
                db.execute("DELETE FROM chunks WHERE file_id = ?", (old[0],))
                db.execute("UPDATE files SET mtime=?, size=?, kind=?, title=?, indexed=? WHERE id=?",
                           (st.st_mtime, st.st_size, path.suffix.lower().lstrip("."), title, time.time(), old[0]))
                file_id = old[0]
                stats.updated += 1
            else:
                cursor = db.execute("INSERT INTO files(path, mtime, size, kind, title, indexed) VALUES (?,?,?,?,?,?)",
                                    (key, st.st_mtime, st.st_size, path.suffix.lower().lstrip("."), title, time.time()))
                file_id = cursor.lastrowid
                stats.added += 1
            # The file's name is searchable too, as the title of every passage.
            passages = chunks(text) or [""]
            db.executemany("INSERT INTO chunks(title, body, file_id, seq) VALUES (?,?,?,?)",
                           [(f"{title} {path.name}", body, file_id, n) for n, body in enumerate(passages)])
            if count % 50 == 0:
                db.commit()
        for key, (file_id, _, _) in known.items():
            if key not in present:
                db.execute("DELETE FROM chunks WHERE file_id = ?", (file_id,))
                db.execute("DELETE FROM files WHERE id = ?", (file_id,))
                stats.removed += 1
        stats.seconds = time.monotonic() - started
        db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('last_index', ?)", (str(time.time()),))
        db.commit()
    finally:
        db.close()
    return stats


# ── Retrieval ────────────────────────────────────────────────────────────────────────────────────────────────────────

def fts_query(text: str) -> str:
    """FTS5 syntax for what a person typed: every word must match (the last one as a prefix), "quoted words" as a
    phrase, -word or NOT word must not."""
    wanted, unwanted = [], []
    negate_next = False
    for token in re.findall(r'-?"[^"]*"|\S+', text):
        if token == "NOT":
            negate_next = True
            continue
        negative = (token.startswith("-") and len(token) > 1) or negate_next
        negate_next = False
        token = token[1:] if token.startswith("-") and len(token) > 1 else token
        if token.startswith('"'):
            words = re.findall(r"\w+", token, re.UNICODE)
            term = '"' + " ".join(words) + '"' if words else ""
        else:
            words = re.findall(r"\w+", token, re.UNICODE)
            term = " ".join(f'"{w}"' for w in words)
        if term:
            (unwanted if negative else wanted).append(term)
    if not wanted:
        raise DocIndexError("search for at least one word")
    if wanted[-1].endswith('"') and " " not in wanted[-1]:
        wanted[-1] += "*"
    return " ".join(wanted) + "".join(f" NOT {t}" for t in unwanted)


@dataclass
class Hit:
    path: str
    title: str
    kind: str
    mtime: float
    snippet: str
    rank: float
    passage: str = ""


def search(app: str, text: str, limit: int = 20, kind: str | None = None, under: str | None = None,
           passages: bool = False, mark: tuple[str, str] = ("[", "]")) -> list[Hit]:
    """The best documents for a query (one hit each), or with passages=True the best passages (several per
    document, with their whole text)."""
    if not db_path(app).is_file():
        raise DocIndexError("nothing is indexed yet: run `docs index` first")
    query = fts_query(text)
    where, args = ["chunks MATCH ?"], [query]
    if kind:
        where.append("f.kind = ?")
        args.append(kind.lower().lstrip("."))
    if under:
        where.append("f.path LIKE ? ESCAPE '\\'")
        prefix = str(Path(os.path.expanduser(under)).resolve())
        args.append(prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "/%")
    sql = (f"SELECT f.path, f.title, f.kind, f.mtime, snippet(chunks, 1, ?, ?, ' … ', 16), "
           f"bm25(chunks, 3.0, 1.0) AS score, chunks.body FROM chunks JOIN files f ON f.id = chunks.file_id "
           f"WHERE {' AND '.join(where)} ORDER BY score LIMIT ?")
    db = connect(app)
    try:
        rows = db.execute(sql, [mark[0], mark[1], *args, limit * (1 if passages else 6)]).fetchall()
    except sqlite3.OperationalError as exc:
        raise DocIndexError(f"could not search for {text!r}: {exc}") from exc
    finally:
        db.close()
    hits: list[Hit] = []
    seen: set[str] = set()
    for path, title, kind_, mtime, snippet, score, body in rows:
        if not passages:
            if path in seen:
                continue
            seen.add(path)
        hits.append(Hit(path, title, kind_, mtime, snippet.strip(), score, body if passages else ""))
        if len(hits) >= limit:
            break
    return hits


def status(app: str) -> dict:
    path = db_path(app)
    info = {"database": str(path), "roots": load_config(app).roots, "files": 0, "passages": 0, "bytes": 0,
            "last_index": None, "kinds": {}}
    if not path.is_file():
        return info
    db = connect(app)
    try:
        info["files"] = db.execute("SELECT count(*) FROM files").fetchone()[0]
        info["passages"] = db.execute("SELECT count(*) FROM chunks").fetchone()[0]
        info["kinds"] = dict(db.execute("SELECT kind, count(*) FROM files GROUP BY kind ORDER BY 2 DESC").fetchall())
        row = db.execute("SELECT value FROM meta WHERE key = 'last_index'").fetchone()
        info["last_index"] = float(row[0]) if row else None
    finally:
        db.close()
    info["bytes"] = path.stat().st_size
    return info


def ask_messages(question: str, hits: Iterable[Hit]) -> list[dict]:
    """A chat request that answers from the passages only, citing them by number."""
    context = "\n\n".join(f"[{n}] {Path(h.path).name}\n{h.passage}" for n, h in enumerate(hits, 1))
    return [
        {"role": "system", "content": (
            "You answer questions using only the numbered passages from the user's own documents. "
            "Cite the passages you used like [1]. If the passages do not contain the answer, say so plainly.")},
        {"role": "user", "content": f"Passages:\n\n{context}\n\nQuestion: {question}"},
    ]
