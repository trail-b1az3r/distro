//! The text of a message whose `text` column is empty (iOS 16 and later): it is only in `attributedBody`, an
//! NSAttributedString archived with NeXTSTEP's typedstream. The string is the first NSString's contents: after the
//! class name comes a '+' (0x2B, "an inline C string follows"), its length (one byte; 0x81 then two bytes; 0x82 then
//! four; little-endian) and the UTF-8 bytes.

pub fn attributed_text(blob: &[u8]) -> Option<String> {
    let marker = b"NSString";
    let start = blob.windows(marker.len()).position(|w| w == marker)? + marker.len();
    let rest = &blob[start..];
    let plus = rest.iter().take(16).position(|&b| b == 0x2B)?;
    let mut i = plus + 1;
    let first = *rest.get(i)?;
    i += 1;
    let len = match first {
        0x81 => {
            let v = u16::from_le_bytes([*rest.get(i)?, *rest.get(i + 1)?]) as usize;
            i += 2;
            v
        }
        0x82 => {
            let v = u32::from_le_bytes([*rest.get(i)?, *rest.get(i + 1)?, *rest.get(i + 2)?, *rest.get(i + 3)?])
                as usize;
            i += 4;
            v
        }
        n if n < 0x80 => n as usize,
        _ => return None,
    };
    let bytes = rest.get(i..i + len)?;
    Some(String::from_utf8_lossy(bytes).into_owned())
}

/// A typedstream blob holding `text`, as iOS writes it (enough of one for the tests).
#[cfg(test)]
pub fn sample(text: &str) -> Vec<u8> {
    let mut out = b"\x04\x0bstreamtyped\x81\xe8\x03\x84\x01@\x84\x84\x84\x12NSAttributedString\x00\x84\x84\x08NSObject\x00\x85\x92\x84\x84\x84\x08NSString\x01\x94\x84\x01+".to_vec();
    let b = text.as_bytes();
    if b.len() < 0x80 {
        out.push(b.len() as u8);
    } else {
        out.push(0x81);
        out.extend_from_slice(&(b.len() as u16).to_le_bytes());
    }
    out.extend_from_slice(b);
    out.extend_from_slice(b"\x86\x84\x02iI\x01");
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn short_and_long() {
        assert_eq!(attributed_text(&sample("hi there 👋")).as_deref(), Some("hi there 👋"));
        let long = "x".repeat(300);
        assert_eq!(attributed_text(&sample(&long)), Some(long));
        assert_eq!(attributed_text(b"nothing"), None);
    }
}
