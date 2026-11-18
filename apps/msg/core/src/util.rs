//! Small conversions shared by the importers and the store.

/// Seconds between 1970-01-01 and 2001-01-01 (Apple's reference date).
pub const APPLE_EPOCH: i64 = 978_307_200;

/// A message date from sms.db as Unix milliseconds. iOS 11 and later store nanoseconds since 2001; older
/// backups store seconds.
pub fn apple_date_ms(value: i64) -> i64 {
    if value == 0 {
        return 0;
    }
    if value.abs() > 100_000_000_000 {
        value / 1_000_000 + APPLE_EPOCH * 1000
    } else {
        (value + APPLE_EPOCH) * 1000
    }
}

/// The key a handle is matched on: an email in lower case, or a phone number's last ten digits (so "+1 (555)
/// 010-2030", "5550102030" and "001 555 010 2030" are one person).
pub fn handle_key(handle: &str) -> String {
    let h = handle.trim();
    if h.contains('@') {
        return h.to_lowercase();
    }
    let digits: String = h.chars().filter(|c| c.is_ascii_digit()).collect();
    if digits.is_empty() {
        return h.to_lowercase();
    }
    let n = digits.len();
    digits[n.saturating_sub(10)..].to_string()
}

/// The file an iPhone backup keeps for a domain and path: its SHA-1, in a folder named after its first two hex digits.
pub fn backup_file_id(domain: &str, relative: &str) -> String {
    sha1_smol::Sha1::from(format!("{domain}-{relative}")).digest().to_string()
}

/// An attachment path as sms.db records it ("~/Library/SMS/Attachments/ab/11/GUID/IMG_1.HEIC") as the backup's
/// (domain, relative path).
pub fn attachment_backup_path(filename: &str) -> Option<(String, String)> {
    let f = filename.trim();
    let rel = f
        .strip_prefix("~/")
        .or_else(|| f.strip_prefix("/var/mobile/"))
        .or_else(|| f.split_once("/var/mobile/").map(|(_, r)| r))?;
    Some(("MediaDomain".to_string(), rel.to_string()))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn dates() {
        // 2023-01-01T00:00:00Z: 694224000 s after 2001.
        assert_eq!(apple_date_ms(694_224_000), 1_672_531_200_000);
        assert_eq!(apple_date_ms(694_224_000_000_000_000), 1_672_531_200_000);
        assert_eq!(apple_date_ms(0), 0);
    }

    #[test]
    fn handles() {
        assert_eq!(handle_key("+1 (555) 010-2030"), "5550102030");
        assert_eq!(handle_key("5550102030"), "5550102030");
        assert_eq!(handle_key("Ann@Example.COM"), "ann@example.com");
    }

    #[test]
    fn backup_ids() {
        // Well known: every tool that reads iPhone backups looks for these two.
        assert_eq!(backup_file_id("HomeDomain", "Library/SMS/sms.db"), "3d0d7e5fb2ce288813306e4d4636395e047a3d28");
        assert_eq!(
            backup_file_id("HomeDomain", "Library/AddressBook/AddressBook.sqlitedb"),
            "31bb7ba8914766d4ba40d6dfb6113c8b614be442"
        );
        assert_eq!(
            attachment_backup_path("~/Library/SMS/Attachments/ab/11/X/IMG_1.HEIC"),
            Some(("MediaDomain".into(), "Library/SMS/Attachments/ab/11/X/IMG_1.HEIC".into()))
        );
    }
}
