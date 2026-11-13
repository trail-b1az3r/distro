//! EPUB-MXL: an EPUB 3 book whose chapters are MDXL rendered as rich text (XHTML), carrying the MDXL sources and the
//! book's images with it. Any e-book reader opens it as an ordinary EPUB; Write can also take it apart again into an
//! editable MDXL book folder (OEBPS/mdxl/ holds the sources, OEBPS/images/ the pictures they use).
//!
//! The container is written by hand: entries are stored (EPUB allows it, and `mimetype` must be stored anyway), so
//! all it takes is a CRC-32 and the ZIP headers.
use serde::Deserialize;
use std::fs;
use std::path::PathBuf;
use std::time::{SystemTime, UNIX_EPOCH};

pub const FORMAT: &str = "epub-mxl 1";

#[derive(Debug, Deserialize)]
pub struct Chapter {
    pub title: String,
    /// The chapter's MDXL file, relative to the book folder.
    pub source: String,
    /// The chapter rendered by MDXL, as the inside of an XHTML <body>.
    pub body: String,
}

#[derive(Debug, Deserialize)]
pub struct Pack {
    pub out: PathBuf,
    pub book: PathBuf,
    pub title: String,
    #[serde(default)]
    pub author: String,
    #[serde(default = "default_language")]
    pub language: String,
    #[serde(default)]
    pub css: String,
    pub chapters: Vec<Chapter>,
}

fn default_language() -> String {
    "en".into()
}

fn crc32(data: &[u8]) -> u32 {
    let mut crc = 0xFFFF_FFFFu32;
    for &byte in data {
        crc ^= byte as u32;
        for _ in 0..8 {
            crc = if crc & 1 != 0 { (crc >> 1) ^ 0xEDB8_8320 } else { crc >> 1 };
        }
    }
    !crc
}

/// A ZIP archive of stored (uncompressed) entries.
struct Zip {
    data: Vec<u8>,
    central: Vec<u8>,
    count: u16,
}

impl Zip {
    fn new() -> Self {
        Zip { data: Vec::new(), central: Vec::new(), count: 0 }
    }

    fn add(&mut self, name: &str, content: &[u8]) -> Result<(), String> {
        let size = u32::try_from(content.len()).map_err(|_| format!("{name} is too large for the book"))?;
        let offset = u32::try_from(self.data.len()).map_err(|_| "the book is too large".to_string())?;
        let crc = crc32(content);
        let name_bytes = name.as_bytes();
        let name_len = name_bytes.len() as u16;
        // 1980-01-01 00:00, so the same book always gives the same file.
        let (time, date) = (0u16, 0x0021u16);
        let mut header = Vec::with_capacity(30 + name_bytes.len());
        header.extend_from_slice(&0x0403_4b50u32.to_le_bytes());
        header.extend_from_slice(&20u16.to_le_bytes()); // version needed
        header.extend_from_slice(&0x0800u16.to_le_bytes()); // UTF-8 names
        header.extend_from_slice(&0u16.to_le_bytes()); // stored
        header.extend_from_slice(&time.to_le_bytes());
        header.extend_from_slice(&date.to_le_bytes());
        header.extend_from_slice(&crc.to_le_bytes());
        header.extend_from_slice(&size.to_le_bytes());
        header.extend_from_slice(&size.to_le_bytes());
        header.extend_from_slice(&name_len.to_le_bytes());
        header.extend_from_slice(&0u16.to_le_bytes());
        header.extend_from_slice(name_bytes);
        self.data.extend_from_slice(&header);
        self.data.extend_from_slice(content);

        let c = &mut self.central;
        c.extend_from_slice(&0x0201_4b50u32.to_le_bytes());
        c.extend_from_slice(&20u16.to_le_bytes()); // made by
        c.extend_from_slice(&20u16.to_le_bytes()); // needed
        c.extend_from_slice(&0x0800u16.to_le_bytes());
        c.extend_from_slice(&0u16.to_le_bytes());
        c.extend_from_slice(&time.to_le_bytes());
        c.extend_from_slice(&date.to_le_bytes());
        c.extend_from_slice(&crc.to_le_bytes());
        c.extend_from_slice(&size.to_le_bytes());
        c.extend_from_slice(&size.to_le_bytes());
        c.extend_from_slice(&name_len.to_le_bytes());
        c.extend_from_slice(&[0u8; 8]); // extra, comment, disk, internal attributes
        c.extend_from_slice(&0u32.to_le_bytes()); // external attributes
        c.extend_from_slice(&offset.to_le_bytes());
        c.extend_from_slice(name_bytes);
        self.count = self.count.checked_add(1).ok_or_else(|| "too many files for the book".to_string())?;
        Ok(())
    }

    fn finish(mut self) -> Result<Vec<u8>, String> {
        let start = u32::try_from(self.data.len()).map_err(|_| "the book is too large".to_string())?;
        let size = self.central.len() as u32;
        self.data.extend_from_slice(&self.central);
        self.data.extend_from_slice(&0x0605_4b50u32.to_le_bytes());
        self.data.extend_from_slice(&[0u8; 4]);
        self.data.extend_from_slice(&self.count.to_le_bytes());
        self.data.extend_from_slice(&self.count.to_le_bytes());
        self.data.extend_from_slice(&size.to_le_bytes());
        self.data.extend_from_slice(&start.to_le_bytes());
        self.data.extend_from_slice(&0u16.to_le_bytes());
        Ok(self.data)
    }
}

fn xml(text: &str) -> String {
    let mut out = String::with_capacity(text.len());
    for ch in text.chars() {
        match ch {
            '&' => out.push_str("&amp;"),
            '<' => out.push_str("&lt;"),
            '>' => out.push_str("&gt;"),
            '"' => out.push_str("&quot;"),
            '\'' => out.push_str("&#39;"),
            // Characters XML 1.0 forbids.
            c if (c as u32) < 0x20 && !matches!(c, '\t' | '\n' | '\r') => {}
            c => out.push(c),
        }
    }
    out
}

fn media_type(name: &str) -> Option<&'static str> {
    let ext = name.rsplit('.').next()?.to_ascii_lowercase();
    Some(match ext.as_str() {
        "png" => "image/png",
        "jpg" | "jpeg" => "image/jpeg",
        "gif" => "image/gif",
        "webp" => "image/webp",
        "svg" => "image/svg+xml",
        "avif" => "image/avif",
        "bmp" => "image/bmp",
        _ => return None,
    })
}

/// A file name safe inside the book: no folders, no "..".
fn plain_name(name: &str) -> Result<&str, String> {
    if name.is_empty() || name.contains('/') || name.contains('\\') || name == "." || name == ".." {
        return Err(format!("not a file in the book: {name}"));
    }
    Ok(name)
}

fn identifier(seed: &str) -> String {
    let now = SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_nanos()).unwrap_or(0);
    // Two FNV-1a hashes over the time, the process and the title: 128 well-mixed bits.
    let mut halves = [0xcbf2_9ce4_8422_2325u64, 0x8422_2325_cbf2_9ce4u64];
    for (i, half) in halves.iter_mut().enumerate() {
        for byte in now.to_le_bytes().iter().chain(std::process::id().to_le_bytes().iter())
            .chain(seed.as_bytes()).chain(std::iter::once(&(i as u8))) {
            *half ^= *byte as u64;
            *half = half.wrapping_mul(0x0000_0100_0000_01b3);
        }
    }
    let hex = format!("{:016x}{:016x}", halves[0], halves[1]);
    // The layout of a random (version 4, variant 1) UUID.
    format!("{}-{}-4{}-a{}-{}", &hex[0..8], &hex[8..12], &hex[13..16], &hex[17..20], &hex[20..32])
}

/// A BCP 47 language tag ("en", "pt-BR"); anything else (a POSIX "C" locale) is English.
fn language_tag(input: &str) -> String {
    let tag = input.trim().replace('_', "-");
    let mut parts = tag.split('-');
    let primary_ok = parts.next().is_some_and(|p| (2..=3).contains(&p.len()) && p.chars().all(|c| c.is_ascii_alphabetic()));
    if primary_ok && parts.all(|p| (1..=8).contains(&p.len()) && p.chars().all(|c| c.is_ascii_alphanumeric())) {
        tag
    } else {
        "en".into()
    }
}

fn chapter_document(title: &str, language: &str, body: &str) -> String {
    format!(
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<!DOCTYPE html>\n\
         <html xmlns=\"http://www.w3.org/1999/xhtml\" xmlns:epub=\"http://www.idpf.org/2007/ops\" lang=\"{lang}\" xml:lang=\"{lang}\">\n\
         <head><meta charset=\"utf-8\"/><title>{title}</title><link rel=\"stylesheet\" type=\"text/css\" href=\"style.css\"/></head>\n\
         <body>\n{body}\n</body>\n</html>\n",
        lang = xml(language),
        title = xml(title),
        body = body
    )
}

pub fn pack(request: &Pack) -> Result<String, String> {
    if request.chapters.is_empty() {
        return Err("the book has no chapters".into());
    }
    let title = if request.title.trim().is_empty() { "Untitled book" } else { request.title.trim() };
    let language = language_tag(&request.language);
    let language = language.as_str();
    let id = identifier(title);
    let modified = {
        let secs = SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0) as i64;
        let (days, rem) = (secs.div_euclid(86_400), secs.rem_euclid(86_400));
        let (y, m, d) = civil_from_days(days);
        format!("{y:04}-{m:02}-{d:02}T{:02}:{:02}:{:02}Z", rem / 3600, rem % 3600 / 60, rem % 60)
    };

    let mut zip = Zip::new();
    zip.add("mimetype", b"application/epub+zip")?;
    zip.add("META-INF/container.xml", br#"<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>
"#)?;

    let mut manifest = String::new();
    let mut spine = String::new();
    let mut nav = String::new();
    manifest.push_str("    <item id=\"nav\" href=\"nav.xhtml\" media-type=\"application/xhtml+xml\" properties=\"nav\"/>\n");
    manifest.push_str("    <item id=\"css\" href=\"style.css\" media-type=\"text/css\"/>\n");

    for (index, chapter) in request.chapters.iter().enumerate() {
        let number = index + 1;
        let href = format!("chapter-{number:03}.xhtml");
        let chapter_title = if chapter.title.trim().is_empty() { format!("Chapter {number}") } else { chapter.title.trim().to_string() };
        zip.add(&format!("OEBPS/{href}"), chapter_document(&chapter_title, language, &chapter.body).as_bytes())?;
        manifest.push_str(&format!("    <item id=\"c{number}\" href=\"{href}\" media-type=\"application/xhtml+xml\"/>\n"));
        spine.push_str(&format!("    <itemref idref=\"c{number}\"/>\n"));
        nav.push_str(&format!("      <li><a href=\"{href}\">{}</a></li>\n", xml(&chapter_title)));
    }

    // The MDXL sources: every chapter, and the book's other MDXL files (its About page).
    let mut sources: Vec<String> = request.chapters.iter().map(|c| c.source.clone()).collect();
    if let Ok(entries) = fs::read_dir(&request.book) {
        let mut extra: Vec<String> = entries.filter_map(Result::ok)
            .filter(|e| e.path().is_file())
            .filter_map(|e| e.file_name().to_str().map(str::to_string))
            .filter(|n| n.ends_with(".mdxl") || n.ends_with(".md"))
            .filter(|n| !sources.contains(n))
            .collect();
        extra.sort();
        sources.extend(extra);
    }
    for (index, source) in sources.iter().enumerate() {
        let name = plain_name(source)?;
        let content = fs::read(request.book.join(name)).map_err(|e| format!("{name}: {e}"))?;
        zip.add(&format!("OEBPS/mdxl/{name}"), &content)?;
        manifest.push_str(&format!("    <item id=\"src{}\" href=\"mdxl/{}\" media-type=\"text/x-mdxl\"/>\n", index + 1, xml(name)));
    }

    let images = request.book.join("images");
    if let Ok(entries) = fs::read_dir(&images) {
        let mut names: Vec<String> = entries.filter_map(Result::ok)
            .filter(|e| e.path().is_file())
            .filter_map(|e| e.file_name().to_str().map(str::to_string))
            .filter(|n| media_type(n).is_some())
            .collect();
        names.sort();
        for (index, name) in names.iter().enumerate() {
            let content = fs::read(images.join(name)).map_err(|e| format!("images/{name}: {e}"))?;
            zip.add(&format!("OEBPS/images/{name}"), &content)?;
            manifest.push_str(&format!("    <item id=\"img{}\" href=\"images/{}\" media-type=\"{}\"/>\n",
                index + 1, xml(name), media_type(name).unwrap_or("application/octet-stream")));
        }
    }

    zip.add("OEBPS/style.css", request.css.as_bytes())?;
    zip.add("OEBPS/nav.xhtml", format!(
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<!DOCTYPE html>\n\
         <html xmlns=\"http://www.w3.org/1999/xhtml\" xmlns:epub=\"http://www.idpf.org/2007/ops\" lang=\"{lang}\" xml:lang=\"{lang}\">\n\
         <head><meta charset=\"utf-8\"/><title>{title}</title></head>\n<body>\n  <nav epub:type=\"toc\" id=\"toc\">\n    <h1>{title}</h1>\n    <ol>\n{nav}    </ol>\n  </nav>\n</body>\n</html>\n",
        lang = xml(language), title = xml(title), nav = nav).as_bytes())?;
    let creator = if request.author.trim().is_empty() { String::new() }
        else { format!("    <dc:creator>{}</dc:creator>\n", xml(request.author.trim())) };
    zip.add("OEBPS/content.opf", format!(
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n\
         <package xmlns=\"http://www.idpf.org/2007/opf\" version=\"3.0\" unique-identifier=\"bookid\" prefix=\"nexora: https://github.com/trail-b1az3r/distro/ns#\">\n\
         \x20 <metadata xmlns:dc=\"http://purl.org/dc/elements/1.1/\">\n\
         \x20   <dc:identifier id=\"bookid\">urn:uuid:{id}</dc:identifier>\n\
         \x20   <dc:title>{title}</dc:title>\n{creator}\
         \x20   <dc:language>{lang}</dc:language>\n\
         \x20   <meta property=\"dcterms:modified\">{modified}</meta>\n\
         \x20   <meta property=\"nexora:format\">{FORMAT}</meta>\n\
         \x20 </metadata>\n  <manifest>\n{manifest}  </manifest>\n  <spine>\n{spine}  </spine>\n</package>\n",
        title = xml(title), lang = xml(language)).as_bytes())?;

    let bytes = zip.finish()?;
    crate::atomic_write(&request.out, &bytes)?;
    Ok(request.out.to_string_lossy().into_owned())
}

/// Days since 1970-01-01 to (year, month, day), proleptic Gregorian (Howard Hinnant's algorithm).
fn civil_from_days(days: i64) -> (i64, u32, u32) {
    let z = days + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z.rem_euclid(146_097);
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = (doy - (153 * mp + 2) / 5 + 1) as u32;
    let m = if mp < 10 { mp + 3 } else { mp - 9 } as u32;
    let y = yoe + era * 400 + if m <= 2 { 1 } else { 0 };
    (y, m, d)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Read;

    fn temp(name: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!("epub-mxl-{name}-{}", std::process::id()));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).unwrap();
        dir
    }

    #[test]
    fn crc32_matches_the_standard_check_value() {
        assert_eq!(crc32(b"123456789"), 0xCBF4_3926);
    }

    #[test]
    fn languages_are_tags() {
        assert_eq!(language_tag("C"), "en");
        assert_eq!(language_tag(""), "en");
        assert_eq!(language_tag("pt_BR"), "pt-BR");
        assert_eq!(language_tag("de"), "de");
    }

    #[test]
    fn identifiers_look_like_uuids() {
        let id = identifier("A book");
        assert_eq!(id.len(), 36);
        assert_eq!(&id[14..15], "4");
        assert_ne!(id, identifier("Another book"));
        assert!(!id.starts_with("00000000"));
    }

    #[test]
    fn dates_are_civil() {
        assert_eq!(civil_from_days(0), (1970, 1, 1));
        assert_eq!(civil_from_days(20_405), (2025, 11, 13));
        assert_eq!(civil_from_days(-1), (1969, 12, 31));
        assert_eq!(civil_from_days(11_016), (2000, 2, 29));
    }

    #[test]
    fn packs_a_book_that_unzip_reads() {
        let book = temp("book");
        fs::write(book.join("00-About.mdxl"), "# My book\n").unwrap();
        fs::write(book.join("01-one.mdxl"), "# One & only\n").unwrap();
        fs::create_dir_all(book.join("images")).unwrap();
        fs::write(book.join("images/cover.png"), b"\x89PNG fake").unwrap();
        let out = book.join("out.epub-mxl");
        let request = Pack {
            out: out.clone(), book: book.clone(), title: "My <book>".into(), author: "Me".into(),
            language: "en".into(), css: "body{}".into(),
            chapters: vec![Chapter { title: "One & only".into(), source: "01-one.mdxl".into(),
                                     body: "<h1 id=\"one\">One &amp; only</h1>".into() }],
        };
        pack(&request).unwrap();
        let bytes = fs::read(&out).unwrap();
        // mimetype first and stored, so readers recognise the book from its first bytes.
        assert_eq!(&bytes[0..4], b"PK\x03\x04");
        assert_eq!(&bytes[30..38], b"mimetype");
        assert_eq!(&bytes[38..58], b"application/epub+zip");

        // Python's zipfile (when there) checks every CRC and lists every entry.
        let check = std::process::Command::new("python3").args(["-c",
            "import sys,zipfile; z=zipfile.ZipFile(sys.argv[1]); assert z.testzip() is None; print('\\n'.join(z.namelist())); print(z.read('OEBPS/content.opf').decode())"])
            .arg(&out).output();
        if let Ok(result) = check {
            if result.status.success() {
                let listing = String::from_utf8_lossy(&result.stdout);
                for name in ["META-INF/container.xml", "OEBPS/chapter-001.xhtml", "OEBPS/nav.xhtml",
                             "OEBPS/mdxl/01-one.mdxl", "OEBPS/mdxl/00-About.mdxl", "OEBPS/images/cover.png"] {
                    assert!(listing.contains(name), "{name} missing:\n{listing}");
                }
                assert!(listing.contains("<dc:title>My &lt;book&gt;</dc:title>"));
                assert!(listing.contains("<meta property=\"nexora:format\">epub-mxl 1</meta>"));
                assert!(listing.contains("<dc:creator>Me</dc:creator>"));
            }
        }
        let mut file = fs::File::open(&out).unwrap();
        let mut all = Vec::new();
        file.read_to_end(&mut all).unwrap();
        assert!(all.windows(4).any(|w| w == b"PK\x05\x06"));
        let _ = fs::remove_dir_all(&book);
    }

    #[test]
    fn refuses_sources_outside_the_book() {
        let book = temp("escape");
        let request = Pack {
            out: book.join("x.epub-mxl"), book: book.clone(), title: "x".into(), author: String::new(),
            language: "en".into(), css: String::new(),
            chapters: vec![Chapter { title: "x".into(), source: "../secret".into(), body: String::new() }],
        };
        assert!(pack(&request).is_err());
        let _ = fs::remove_dir_all(&book);
    }
}
