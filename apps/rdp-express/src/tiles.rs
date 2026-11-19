//! What changed since the last picture, as JPEG rectangles: the screen is cut into 64-pixel tiles, an unchanged
//! tile is not sent, and the changed tiles of a row are joined into runs (one JPEG each).

use crate::desktop::Picture;

pub const TILE: u32 = 64;

pub struct Rect {
    pub x: u32,
    pub y: u32,
    pub w: u32,
    pub h: u32,
    pub jpeg: Vec<u8>,
}

fn tile_changed(a: &Picture, b: &Picture, x: u32, y: u32, w: u32, h: u32) -> bool {
    let row = (a.width * 4) as usize;
    let (x0, x1) = ((x * 4) as usize, ((x + w) * 4) as usize);
    (y..y + h).any(|yy| {
        let off = yy as usize * row;
        a.pixels[off + x0..off + x1] != b.pixels[off + x0..off + x1]
    })
}

fn encode(p: &Picture, x: u32, y: u32, w: u32, h: u32, quality: u8) -> Vec<u8> {
    let row = (p.width * 4) as usize;
    let mut rect = Vec::with_capacity((w * h * 4) as usize);
    for yy in y..y + h {
        let off = yy as usize * row + (x * 4) as usize;
        rect.extend_from_slice(&p.pixels[off..off + (w * 4) as usize]);
    }
    let mut out = Vec::new();
    let color = if p.bgr { jpeg_encoder::ColorType::Bgra } else { jpeg_encoder::ColorType::Rgba };
    jpeg_encoder::Encoder::new(&mut out, quality)
        .encode(&rect, w as u16, h as u16, color)
        .expect("in-memory JPEG");
    out
}

/// The rectangles to send: everything when there is no previous picture (or its size changed).
pub fn changes(prev: Option<&Picture>, cur: &Picture, quality: u8) -> Vec<Rect> {
    let full = prev.map_or(true, |p| p.width != cur.width || p.height != cur.height || p.bgr != cur.bgr);
    let mut out = vec![];
    let mut y = 0;
    while y < cur.height {
        let h = TILE.min(cur.height - y);
        let mut x = 0;
        while x < cur.width {
            let w = TILE.min(cur.width - x);
            if full || tile_changed(prev.unwrap(), cur, x, y, w, h) {
                // Join the changed tiles that follow on this row.
                let mut end = x + w;
                while end < cur.width {
                    let w2 = TILE.min(cur.width - end);
                    if full || tile_changed(prev.unwrap(), cur, end, y, w2, h) {
                        end += w2;
                    } else {
                        break;
                    }
                }
                out.push(Rect { x, y, w: end - x, h, jpeg: encode(cur, x, y, end - x, h, quality) });
                x = end;
            } else {
                x += w;
            }
        }
        y += h;
    }
    out
}

/// The frame message (type 2): frame number, the screen's size, then each rectangle and its JPEG.
pub fn frame_message(number: u32, cur: &Picture, rects: &[Rect]) -> Vec<u8> {
    let mut m = Vec::with_capacity(16 + rects.iter().map(|r| r.jpeg.len() + 12).sum::<usize>());
    m.push(2u8);
    m.extend_from_slice(&number.to_be_bytes());
    m.extend_from_slice(&(cur.width as u16).to_be_bytes());
    m.extend_from_slice(&(cur.height as u16).to_be_bytes());
    m.extend_from_slice(&(rects.len() as u16).to_be_bytes());
    for r in rects {
        for v in [r.x, r.y, r.w, r.h] {
            m.extend_from_slice(&(v as u16).to_be_bytes());
        }
        m.extend_from_slice(&(r.jpeg.len() as u32).to_be_bytes());
        m.extend_from_slice(&r.jpeg);
    }
    m
}

#[cfg(test)]
mod tests {
    use super::*;

    fn pic(w: u32, h: u32, fill: u8) -> Picture {
        Picture { width: w, height: h, bgr: true, pixels: vec![fill; (w * h * 4) as usize] }
    }

    #[test]
    fn only_what_changed() {
        let a = pic(200, 130, 10);
        assert_eq!(changes(None, &a, 80).len(), 3, "one run per tile row at first");
        let mut b = pic(200, 130, 10);
        assert!(changes(Some(&a), &b, 80).is_empty());
        // A pixel in the second tile of the second row.
        let off = ((70 * 200 + 100) * 4) as usize;
        b.pixels[off] = 200;
        let r = changes(Some(&a), &b, 80);
        assert_eq!(r.len(), 1);
        assert_eq!((r[0].x, r[0].y, r[0].w, r[0].h), (64, 64, 64, 64));
        assert_eq!(&r[0].jpeg[..2], &[0xFF, 0xD8]);
        let m = frame_message(7, &b, &r);
        assert_eq!(m[0], 2);
        assert_eq!(u16::from_be_bytes([m[9], m[10]]), 1);
    }
}
