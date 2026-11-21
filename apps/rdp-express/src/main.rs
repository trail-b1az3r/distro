//! rdp-express: Frontline's remote desktop server. It shares the Wayland desktop (Hyprland, sway and other wlroots
//! compositors) with frontline-msg's remote desktop viewer, over an encrypted protocol of its own: JPEG tiles of what
//! changed, sent only as fast as the viewer takes them, and the viewer's pointer and keys back.
//!
//!   rdp-express serve [--port 47801] [--listen ADDR]... [--any] [--output NAME] [--quality 1-100] [--fps N]
//!   rdp-express pair [--minutes 10]      a one-time code for a new viewer
//!   rdp-express clients | revoke NAME    the viewers allowed in
//!   rdp-express outputs                  the monitors it can share
//!   rdp-express snapshot FILE.ppm        one picture (checks that sharing works)
//!
//! By default it listens on this machine (127.0.0.1) and on its Tailscale addresses only, so it is reachable from
//! your tailnet and nowhere else; --listen or --any widen that.

mod desktop;
mod link;
mod tiles;

use std::collections::BTreeMap;
use std::io;
use std::net::{SocketAddr, TcpListener, TcpStream};
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{mpsc, Arc};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use base64::engine::general_purpose::STANDARD as B64;
use base64::Engine;
use serde_json::{json, Value};
use x25519_dalek::{PublicKey, StaticSecret};

const PORT: u16 = 47801;
const VERSION: &str = env!("CARGO_PKG_VERSION");

fn log(msg: &str) {
    eprintln!("rdp-express: {msg}");
}

// ── where things are kept ──

fn config_dir() -> PathBuf {
    let base = std::env::var_os("XDG_CONFIG_HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from(std::env::var_os("HOME").unwrap_or_default()).join(".config"));
    let dir = base.join("rdp-express");
    let _ = std::fs::create_dir_all(&dir);
    dir
}

fn pairing_path() -> PathBuf {
    std::env::var_os("XDG_RUNTIME_DIR").map(|d| PathBuf::from(d).join("rdp-express-pairing.json")).unwrap_or_else(|| config_dir().join("pairing.json"))
}

fn write_private(path: &PathBuf, data: &[u8]) -> io::Result<()> {
    use std::os::unix::fs::OpenOptionsExt;
    let tmp = path.with_extension("tmp");
    {
        let mut f = std::fs::OpenOptions::new().write(true).create(true).truncate(true).mode(0o600).open(&tmp)?;
        io::Write::write_all(&mut f, data)?;
    }
    std::fs::rename(tmp, path)
}

fn identity() -> StaticSecret {
    let path = config_dir().join("identity.key");
    if let Ok(bytes) = std::fs::read(&path) {
        if let Ok(arr) = <[u8; 32]>::try_from(bytes.as_slice()) {
            return StaticSecret::from(arr);
        }
    }
    let key: [u8; 32] = link::random();
    write_private(&path, &key).expect("could not save the server's key");
    StaticSecret::from(key)
}

fn clients() -> BTreeMap<String, String> {
    std::fs::read(config_dir().join("clients.json")).ok().and_then(|b| serde_json::from_slice(&b).ok()).unwrap_or_default()
}

fn save_clients(c: &BTreeMap<String, String>) {
    let _ = write_private(&config_dir().join("clients.json"), serde_json::to_string_pretty(c).unwrap().as_bytes());
}

fn now() -> u64 {
    SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0)
}

/// The pairing code, while one is valid.
fn pairing_code() -> Option<String> {
    let v: Value = serde_json::from_slice(&std::fs::read(pairing_path()).ok()?).ok()?;
    if v["expires"].as_u64()? < now() || v["failures"].as_u64().unwrap_or(0) >= 5 {
        let _ = std::fs::remove_file(pairing_path());
        return None;
    }
    v["code"].as_str().map(String::from)
}

fn pairing_failed() {
    if let Some(mut v) = std::fs::read(pairing_path()).ok().and_then(|b| serde_json::from_slice::<Value>(&b).ok()) {
        v["failures"] = json!(v["failures"].as_u64().unwrap_or(0) + 1);
        let _ = write_private(&pairing_path(), v.to_string().as_bytes());
    }
}

fn hostname() -> String {
    std::fs::read_to_string("/etc/hostname").map(|s| s.trim().to_string()).ok().filter(|s| !s.is_empty()).unwrap_or_else(|| "this computer".into())
}

/// This machine's Tailscale addresses (none when Tailscale is not running).
fn tailscale_addresses() -> Vec<String> {
    std::process::Command::new("tailscale")
        .arg("ip")
        .output()
        .ok()
        .filter(|o| o.status.success())
        .map(|o| String::from_utf8_lossy(&o.stdout).lines().map(|l| l.trim().to_string()).filter(|l| !l.is_empty()).collect())
        .unwrap_or_default()
}

/// WAYLAND_DISPLAY, found in the runtime folder when a service started without it.
fn find_wayland() {
    if std::env::var_os("WAYLAND_DISPLAY").is_some() {
        return;
    }
    if let Some(dir) = std::env::var_os("XDG_RUNTIME_DIR") {
        let mut sockets: Vec<String> = std::fs::read_dir(dir)
            .into_iter()
            .flatten()
            .flatten()
            .filter_map(|e| e.file_name().into_string().ok())
            .filter(|n| n.starts_with("wayland-") && !n.ends_with(".lock"))
            .collect();
        sockets.sort();
        if let Some(s) = sockets.first() {
            std::env::set_var("WAYLAND_DISPLAY", s);
        }
    }
}

// ── a session ──

#[derive(Clone)]
struct Settings {
    output: Option<String>,
    quality: u8,
    fps: u32,
}

enum Input {
    Pointer(u16, u16),
    Button(u32, bool),
    Scroll(i16, i16),
    Key(u32, bool),
    Ack(u32),
    Refresh,
    Settings(Value),
}

fn parse_input(m: &[u8]) -> Option<Input> {
    let be16 = |i: usize| u16::from_be_bytes([m[i], m[i + 1]]);
    let be32 = |i: usize| u32::from_be_bytes([m[i], m[i + 1], m[i + 2], m[i + 3]]);
    Some(match (m.first()?, m.len()) {
        (0x11, 5) => Input::Pointer(be16(1), be16(3)),
        (0x12, 6) => Input::Button(be32(1), m[5] != 0),
        (0x13, 5) => Input::Scroll(be16(1) as i16, be16(3) as i16),
        (0x14, 6) => Input::Key(be32(1), m[5] != 0),
        (0x15, 5) => Input::Ack(be32(1)),
        (0x17, _) => Input::Refresh,
        (0x16, _) => Input::Settings(serde_json::from_slice(&m[1..]).ok()?),
        _ => return None,
    })
}

fn refuse(stream: &mut TcpStream, why: &str) {
    let _ = link::write_frame(stream, json!({"hello": "rdp-express-server", "v": 1, "error": why}).to_string().as_bytes());
}

fn session(mut stream: TcpStream, peer: SocketAddr, me: &StaticSecret, busy: &AtomicBool, settings: &Settings) -> io::Result<()> {
    stream.set_read_timeout(Some(Duration::from_secs(20)))?;
    stream.set_nodelay(true)?;
    let hello: Value = serde_json::from_slice(&link::read_frame(&mut stream)?).map_err(|_| io::Error::other("not a viewer"))?;
    if hello["hello"] != "rdp-express" {
        return Err(io::Error::other("not a viewer"));
    }
    let pub_b64 = hello["pub"].as_str().unwrap_or("").to_string();
    let peer_pub: [u8; 32] = B64.decode(&pub_b64).ok().and_then(|b| b.try_into().ok()).ok_or_else(|| io::Error::other("bad key"))?;
    let client_nonce = B64.decode(hello["nonce"].as_str().unwrap_or("")).unwrap_or_default();
    let name = hello["name"].as_str().unwrap_or("viewer").chars().take(64).collect::<String>();
    let known = clients().contains_key(&pub_b64);
    let code = if known { None } else { pairing_code() };
    if !known && code.is_none() {
        refuse(&mut stream, &format!("{} does not know this viewer yet: run `rdp-express pair` on it and enter the code", hostname()));
        return Ok(());
    }
    if busy.swap(true, Ordering::SeqCst) {
        refuse(&mut stream, "someone else is connected to this desktop");
        return Ok(());
    }
    struct Busy<'a>(&'a AtomicBool);
    impl Drop for Busy<'_> {
        fn drop(&mut self) {
            self.0.store(false, Ordering::SeqCst);
        }
    }
    let _busy = Busy(busy);

    let server_nonce: [u8; 16] = link::random();
    let shared = me.diffie_hellman(&PublicKey::from(peer_pub));
    link::write_frame(&mut stream, json!({"hello": "rdp-express-server", "v": 1, "known": known, "name": hostname(),
        "pub": B64.encode(PublicKey::from(me).as_bytes()), "nonce": B64.encode(server_nonce), "version": VERSION}).to_string().as_bytes())?;
    let key = link::derive(shared.as_bytes(), code.as_deref(), &client_nonce, &server_nonce);
    let mut opener = link::Sealer::new(&key, b"C2S\0");
    let first = link::read_frame(&mut stream)?;
    let first = match opener.open(&first) {
        Ok(m) => m,
        Err(e) => {
            if !known {
                pairing_failed();
                log(&format!("{peer}: wrong pairing code"));
            }
            return Err(e);
        }
    };
    if first.first() != Some(&0x10) {
        return Err(io::Error::other("expected the viewer's hello"));
    }
    if !known {
        let mut c = clients();
        c.insert(pub_b64.clone(), name.clone());
        save_clients(&c);
        let _ = std::fs::remove_file(pairing_path());
        log(&format!("paired with {name} ({peer})"));
    }
    log(&format!("{name} ({peer}) connected"));

    find_wayland();
    let mut desktop = match desktop::Desktop::connect(settings.output.as_deref()) {
        Ok(d) => d,
        Err(e) => {
            let mut w = link::Writer { stream: stream.try_clone()?, sealer: link::Sealer::new(&key, b"S2C\0") };
            let mut m = vec![3u8];
            m.extend_from_slice(json!({"error": e}).to_string().as_bytes());
            let _ = w.send(&m);
            return Err(io::Error::other(e));
        }
    };
    let mut writer = link::Writer { stream: stream.try_clone()?, sealer: link::Sealer::new(&key, b"S2C\0") };
    let (pointer, keyboard) = desktop.can_control();
    let out = desktop.output();
    let mut hello = vec![1u8];
    hello.extend_from_slice(json!({"name": hostname(), "output": out.name, "width": out.width, "height": out.height,
        "pointer": pointer, "keyboard": keyboard, "version": VERSION}).to_string().as_bytes());
    writer.send(&hello)?;

    // The viewer's input, read on its own thread.
    let (tx, rx) = mpsc::channel::<Input>();
    stream.set_read_timeout(None)?;
    let mut reader = stream.try_clone()?;
    std::thread::spawn(move || {
        loop {
            let Ok(frame) = link::read_frame(&mut reader) else { break };
            let Ok(m) = opener.open(&frame) else { break };
            if let Some(i) = parse_input(&m) {
                if tx.send(i).is_err() {
                    break;
                }
            }
        }
    });

    let mut quality = settings.quality;
    let mut interval = Duration::from_millis(1000 / settings.fps.max(1) as u64);
    let mut prev: Option<desktop::Picture> = None;
    let mut sent: u32 = 0;
    let mut acked: u32 = 0;
    let mut last = Instant::now() - interval;
    let mut size = (out.width.max(1) as u32, out.height.max(1) as u32);
    let result = loop {
        // Everything the viewer sent first: input never waits for a picture.
        let mut gone = false;
        loop {
            match rx.try_recv() {
                Ok(input) => match input {
                    Input::Pointer(x, y) => desktop.pointer_to(x as u32, y as u32, size.0, size.1),
                    Input::Button(b, p) => desktop.button(b, p),
                    Input::Scroll(v, h) => desktop.scroll(v as i32, h as i32),
                    Input::Key(k, p) => desktop.key(k, p),
                    Input::Ack(n) => acked = acked.max(n),
                    Input::Refresh => prev = None,
                    Input::Settings(v) => {
                        if let Some(q) = v["quality"].as_u64() {
                            quality = q.clamp(10, 95) as u8;
                        }
                        if let Some(f) = v["fps"].as_u64() {
                            interval = Duration::from_millis(1000 / f.clamp(1, 60));
                        }
                    }
                },
                Err(mpsc::TryRecvError::Empty) => break,
                Err(mpsc::TryRecvError::Disconnected) => {
                    gone = true;
                    break;
                }
            }
        }
        if gone {
            break Ok(());
        }
        // A picture when the viewer is ready for one (at most two on the way: a slow link gets fewer frames, not a
        // growing delay) and the frame rate allows; the compositor answers when the screen next changes.
        if sent.saturating_sub(acked) < 2 && last.elapsed() >= interval {
            desktop.begin();
        }
        let pic = match desktop.poll(Duration::from_millis(4)) {
            Ok(Some(p)) => p,
            Ok(None) => continue,
            Err(e) => break Err(io::Error::other(e)),
        };
        last = Instant::now();
        size = (pic.width, pic.height);
        let rects = tiles::changes(prev.as_ref(), &pic, quality);
        if !rects.is_empty() {
            sent += 1;
            if let Err(e) = writer.send(&tiles::frame_message(sent, &pic, &rects)) {
                break Err(e);
            }
        }
        prev = Some(pic);
    };
    desktop.release_all();
    log(&format!("{name} ({peer}) disconnected"));
    result
}

fn serve(args: &[String]) -> i32 {
    let mut port = PORT;
    let mut listen: Vec<String> = vec![];
    let mut any = false;
    let mut settings = Settings { output: None, quality: 70, fps: 30 };
    let mut it = args.iter();
    while let Some(a) = it.next() {
        match a.as_str() {
            "--port" => port = it.next().and_then(|v| v.parse().ok()).unwrap_or(PORT),
            "--listen" => listen.extend(it.next().cloned()),
            "--any" => any = true,
            "--output" => settings.output = it.next().cloned(),
            "--quality" => settings.quality = it.next().and_then(|v| v.parse().ok()).unwrap_or(70).clamp(10, 95),
            "--fps" => settings.fps = it.next().and_then(|v| v.parse().ok()).unwrap_or(30).clamp(1, 60),
            other => {
                log(&format!("unknown option {other}"));
                return 2;
            }
        }
    }
    if any {
        listen = vec!["0.0.0.0".into(), "::".into()];
    } else if listen.is_empty() {
        listen.push("127.0.0.1".into());
        let ts = tailscale_addresses();
        if ts.is_empty() {
            log("Tailscale is not running: listening on this machine only (--any, or --listen ADDR, to widen that)");
        }
        listen.extend(ts);
    }
    let me = Arc::new(identity());
    let busy = Arc::new(AtomicBool::new(false));
    let mut threads = vec![];
    for addr in &listen {
        let sock = if addr.contains(':') { format!("[{addr}]:{port}") } else { format!("{addr}:{port}") };
        let listener = match TcpListener::bind(&sock) {
            Ok(l) => l,
            Err(e) => {
                log(&format!("cannot listen on {sock}: {e}"));
                continue;
            }
        };
        log(&format!("listening on {sock}"));
        let (me, busy, settings) = (me.clone(), busy.clone(), settings.clone());
        threads.push(std::thread::spawn(move || {
            for conn in listener.incoming().flatten() {
                let peer = conn.peer_addr().unwrap_or_else(|_| SocketAddr::from(([0, 0, 0, 0], 0)));
                let (me, busy, settings) = (me.clone(), busy.clone(), settings.clone());
                std::thread::spawn(move || {
                    if let Err(e) = session(conn, peer, &me, &busy, &settings) {
                        log(&format!("{peer}: {e}"));
                    }
                });
            }
        }));
    }
    if threads.is_empty() {
        log("nowhere to listen");
        return 1;
    }
    for t in threads {
        let _ = t.join();
    }
    0
}

fn pair(args: &[String]) -> i32 {
    let minutes: u64 = args.iter().position(|a| a == "--minutes").and_then(|i| args.get(i + 1)).and_then(|v| v.parse().ok()).unwrap_or(10);
    let n = u32::from_be_bytes(link::random::<4>()) % 100_000_000;
    let code = format!("{n:08}");
    let data = json!({"code": code, "expires": now() + minutes * 60, "failures": 0});
    if let Err(e) = write_private(&pairing_path(), data.to_string().as_bytes()) {
        log(&format!("could not save the code: {e}"));
        return 1;
    }
    println!("Pairing code: {} {}", &code[..4], &code[4..]);
    println!("Enter it in the viewer (Messages > Remote desktop) within {minutes} minutes. It works once.");
    0
}

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let code = match args.first().map(String::as_str) {
        Some("serve") => serve(&args[1..]),
        Some("pair") => pair(&args[1..]),
        Some("clients") => {
            for (k, name) in clients() {
                println!("{name}\t{}…", &k[..12.min(k.len())]);
            }
            0
        }
        Some("revoke") => {
            let who = args.get(1).cloned().unwrap_or_default();
            let mut c = clients();
            let before = c.len();
            c.retain(|k, name| *name != who && !k.starts_with(&who));
            save_clients(&c);
            println!("{} viewer(s) removed", before - c.len());
            0
        }
        Some("outputs") => {
            find_wayland();
            match desktop::Desktop::connect(None) {
                Ok(_) => {
                    // Desktop::connect picks the first; list them all by asking for a name that is not there.
                    match desktop::Desktop::connect(Some("\u{0}")) {
                        Err(e) => println!("{}", e.rsplit("there are: ").next().unwrap_or("").trim_end_matches(')')),
                        Ok(_) => {}
                    }
                    0
                }
                Err(e) => {
                    log(&e);
                    1
                }
            }
        }
        Some("snapshot") => {
            // One picture of the shared output, as a PPM file: checks that sharing works here.
            find_wayland();
            let Some(path) = args.get(1) else {
                eprintln!("usage: rdp-express snapshot FILE.ppm [--output NAME]");
                std::process::exit(2);
            };
            let output = args.iter().position(|a| a == "--output").and_then(|i| args.get(i + 1)).map(String::as_str);
            let result = desktop::Desktop::connect(output).and_then(|mut d| {
                d.capture(Duration::from_secs(3))?.ok_or_else(|| "the compositor sent no picture".to_string())
            });
            match result {
                Ok(p) => {
                    let mut ppm = format!("P6\n{} {}\n255\n", p.width, p.height).into_bytes();
                    for px in p.pixels.chunks_exact(4) {
                        if p.bgr { ppm.extend_from_slice(&[px[2], px[1], px[0]]) } else { ppm.extend_from_slice(&px[..3]) }
                    }
                    match std::fs::write(path, ppm) {
                        Ok(()) => {
                            println!("{}x{} written to {path}", p.width, p.height);
                            0
                        }
                        Err(e) => {
                            log(&e.to_string());
                            1
                        }
                    }
                }
                Err(e) => {
                    log(&e);
                    1
                }
            }
        }
        Some("--version") => {
            println!("rdp-express {VERSION}");
            0
        }
        _ => {
            eprintln!("usage: rdp-express serve [--port N] [--listen ADDR]... [--any] [--output NAME] [--quality Q] [--fps N]\n       rdp-express pair [--minutes N] | clients | revoke NAME | outputs | snapshot FILE.ppm | --version");
            2
        }
    };
    std::process::exit(code);
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn input_messages() {
        assert!(matches!(parse_input(&[0x11, 0, 10, 0, 20]), Some(Input::Pointer(10, 20))));
        assert!(matches!(parse_input(&[0x12, 0, 0, 1, 0x10, 1]), Some(Input::Button(0x110, true))));
        assert!(matches!(parse_input(&[0x13, 0xFF, 0xFF, 0, 0]), Some(Input::Scroll(-1, 0))));
        assert!(matches!(parse_input(&[0x14, 0, 0, 0, 30, 0]), Some(Input::Key(30, false))));
        assert!(parse_input(&[0x11, 0]).is_none(), "a short message is ignored");
    }
}
