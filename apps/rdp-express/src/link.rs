//! The connection: a plaintext hello, then encrypted frames. Each frame is a 4-byte big-endian length followed by
//! ChaCha20-Poly1305 ciphertext and tag. The nonce is a 4-byte direction ("C2S\0" or "S2C\0") plus an 8-byte
//! counter, so a replayed, reordered or altered frame is refused.
//!
//! Keys: each side has an X25519 key. For a client the server already knows, the session key is
//! HKDF-SHA256(shared secret, salt = client nonce || server nonce, info "rdp-express v1 key"). A new client must
//! give the pairing code that `rdp-express pair` shows on the server. It is mixed into the key (info
//! "rdp-express v1 pair", input shared secret || code), so a wrong code, or a machine in the middle, fails the
//! first frame's check.

use std::io::{self, Read, Write};
use std::net::TcpStream;

use chacha20poly1305::aead::{Aead, KeyInit};
use chacha20poly1305::{ChaCha20Poly1305, Key, Nonce};
use hkdf::Hkdf;
use sha2::Sha256;

pub const MAX_FRAME: usize = 64 * 1024 * 1024;

pub fn derive(shared: &[u8], code: Option<&str>, client_nonce: &[u8], server_nonce: &[u8]) -> [u8; 32] {
    let mut ikm = shared.to_vec();
    let info: &[u8] = match code {
        Some(c) => {
            ikm.extend_from_slice(c.as_bytes());
            b"rdp-express v1 pair"
        }
        None => b"rdp-express v1 key",
    };
    let mut salt = client_nonce.to_vec();
    salt.extend_from_slice(server_nonce);
    let mut out = [0u8; 32];
    Hkdf::<Sha256>::new(Some(&salt), &ikm).expand(info, &mut out).expect("32 bytes");
    out
}

fn nonce(direction: &[u8; 4], counter: u64) -> [u8; 12] {
    let mut n = [0u8; 12];
    n[..4].copy_from_slice(direction);
    n[4..].copy_from_slice(&counter.to_be_bytes());
    n
}

pub fn read_frame(stream: &mut impl Read) -> io::Result<Vec<u8>> {
    let mut head = [0u8; 4];
    stream.read_exact(&mut head)?;
    let len = u32::from_be_bytes(head) as usize;
    if len > MAX_FRAME {
        return Err(io::Error::new(io::ErrorKind::InvalidData, "frame too large"));
    }
    let mut body = vec![0u8; len];
    stream.read_exact(&mut body)?;
    Ok(body)
}

pub fn write_frame(stream: &mut impl Write, body: &[u8]) -> io::Result<()> {
    let mut out = Vec::with_capacity(body.len() + 4);
    out.extend_from_slice(&(body.len() as u32).to_be_bytes());
    out.extend_from_slice(body);
    stream.write_all(&out)
}

/// One direction of an encrypted connection.
pub struct Sealer {
    aead: ChaCha20Poly1305,
    direction: [u8; 4],
    counter: u64,
}

impl Sealer {
    pub fn new(key: &[u8; 32], direction: &[u8; 4]) -> Sealer {
        Sealer { aead: ChaCha20Poly1305::new(Key::from_slice(key)), direction: *direction, counter: 0 }
    }

    pub fn seal(&mut self, plain: &[u8]) -> Vec<u8> {
        let n = nonce(&self.direction, self.counter);
        self.counter += 1;
        self.aead.encrypt(Nonce::from_slice(&n), plain).expect("encryption does not fail")
    }

    pub fn open(&mut self, sealed: &[u8]) -> io::Result<Vec<u8>> {
        let n = nonce(&self.direction, self.counter);
        let plain = self
            .aead
            .decrypt(Nonce::from_slice(&n), sealed)
            .map_err(|_| io::Error::new(io::ErrorKind::InvalidData, "a frame failed its check"))?;
        self.counter += 1;
        Ok(plain)
    }
}

pub struct Writer {
    pub stream: TcpStream,
    pub sealer: Sealer,
}

impl Writer {
    pub fn send(&mut self, plain: &[u8]) -> io::Result<()> {
        let sealed = self.sealer.seal(plain);
        write_frame(&mut self.stream, &sealed)
    }
}

pub fn random<const N: usize>() -> [u8; N] {
    let mut out = [0u8; N];
    getrandom::fill(&mut out).expect("the system's random source");
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn round_trip_and_replay() {
        let key = [7u8; 32];
        let mut a = Sealer::new(&key, b"C2S\0");
        let mut b = Sealer::new(&key, b"C2S\0");
        let one = a.seal(b"hello");
        let two = a.seal(b"again");
        assert_eq!(b.open(&one).unwrap(), b"hello");
        assert!(b.open(&one).is_err(), "a replay is refused");
        assert_eq!(b.open(&two).unwrap(), b"again");
    }

    #[test]
    fn same_keys_as_the_python_viewer() {
        // nexora_msg/rdp.py's derive() gives these (tests/test_rdp.py checks the same values).
        let hex = |k: [u8; 32]| k.iter().map(|b| format!("{b:02x}")).collect::<String>();
        assert_eq!(hex(derive(b"shared", Some("12345678"), b"c", b"s")),
                   "17d548fba1169b2bad12ddd1f3733f39b64d63ac19ff4c93a127a7e04ab02c65");
        assert_eq!(hex(derive(b"shared", None, b"c", b"s")),
                   "2f2fd7dd402a5d18c0749184a8c3763cc0afee8d39631efbcdecbb80661f7e68");
    }

    #[test]
    fn the_code_changes_the_key() {
        let k1 = derive(b"shared", Some("12345678"), b"c", b"s");
        let k2 = derive(b"shared", Some("12345679"), b"c", b"s");
        assert_ne!(k1, k2);
        assert_ne!(derive(b"shared", None, b"c", b"s"), k1);
    }
}
