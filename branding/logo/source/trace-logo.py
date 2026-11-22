import re, subprocess, sys
from PIL import Image, ImageFilter
import numpy as np

src = Image.open("src.png").convert("RGB")
X0, Y0, X1, Y1 = 300, 380, 1860, 1530          # the sheet, without the stray tick at the top left
im = np.asarray(src.crop((X0, Y0, X1, Y1))).astype(float)
H, W = im.shape[:2]
L = im.mean(axis=2)
BG = 143.0

def blur(a, r):
    k = np.exp(-0.5 * (np.arange(-int(3 * r), int(3 * r) + 1) / r) ** 2); k /= k.sum()
    a = np.apply_along_axis(lambda v: np.convolve(np.pad(v, len(k) // 2, mode="edge"), k, mode="valid"), 0, a)
    return np.apply_along_axis(lambda v: np.convolve(np.pad(v, len(k) // 2, mode="edge"), k, mode="valid"), 1, a)

def morph(mask, f):
    return np.asarray(Image.fromarray(mask.astype(np.uint8) * 255).filter(f)) > 0
# Ink: the drawn lines, which are thin. Dark smudges (thick) are wash, not ink.
dark = L < 92
blob = morph(morph(dark, ImageFilter.MinFilter(9)), ImageFilter.MaxFilter(11)) & (L < 110)
ink = dark & ((L < blur(L, 8) - 16) | ~blob)
# Specks of grain in the dark smudge are not lines: keep only pieces at least 30 px long.
from scipy import ndimage
lab, n = ndimage.label(ink, structure=np.ones((3, 3)))
keep = np.zeros(n + 1, bool)
for i, sl in enumerate(ndimage.find_objects(lab), 1):
    keep[i] = max(sl[0].stop - sl[0].start, sl[1].stop - sl[1].start) >= 30
ink = keep[lab]
# Pencil: the softer grey lines drawn over the washes (darker than what is around them, and thin).
local = (L < blur(L, 4) - 9) & (L < 132) & ~morph(ink, ImageFilter.MaxFilter(5))
pencil = local & ~morph(morph(local, ImageFilter.MinFilter(5)), ImageFilter.MaxFilter(7))
# Washes: everything that is neither paper nor line, with the lines filled in from around them.
near_ink = morph((L < 110) & ~blob & morph(ink, ImageFilter.MaxFilter(5)), ImageFilter.MaxFilter(7))
w = (~near_ink).astype(float)
fill = {}
for c in range(3):
    num = blur(im[:, :, c] * w, 6); den = blur(w, 6)
    fill[c] = np.where(near_ink, num / np.maximum(den, 1e-3), im[:, :, c])
wash = np.dstack([blur(fill[c], 2.5) for c in range(3)])
WL = wash.mean(axis=2)

def trace(mask, name, turd=40, alpha=1.0):
    Image.fromarray(np.where(mask, 0, 255).astype(np.uint8)).convert("1").save(f"{name}.bmp")
    subprocess.run(["potrace", "-b", "svg", "--flat", "-t", str(turd), "-a", str(alpha), "-O", "0.6", "-u", "4",
                    "-o", f"{name}.svg", f"{name}.bmp"], check=True)
    t = open(f"{name}.svg").read()
    g = re.search(r'<g transform="([^"]+)"', t).group(1)
    d = " ".join(re.findall(r'<path d="([^"]+)"', t, re.S))
    return g, re.sub(r"\s+", " ", d).strip()

def colour(mask):
    if mask.sum() == 0:
        return "#808080"
    r, g, b = (int(im[:, :, c][mask & ~near_ink].mean()) if (mask & ~near_ink).sum() else int(wash[:, :, c][mask].mean()) for c in range(3))
    return f"#{r:02X}{g:02X}{b:02X}"

layers = []
# Light washes, least light first (the snow last, on top); dark washes, least dark first.
for name, lo, hi in [("light1", 149, 999), ("light2", 160, 999), ("light3", 180, 999), ("light4", 205, 999)]:
    m = (WL >= lo) & (WL < hi)
    layers.append((name, m, colour(m & (WL < [160,180,205,999][["light1","light2","light3","light4"].index(name)]))))
for name, hi in [("dark1", 137), ("dark2", 127), ("dark3", 115), ("dark4", 100)]:
    m = WL < hi
    nxt = {"dark1": 127, "dark2": 115, "dark3": 100, "dark4": -1}[name]
    layers.append((name, m, {"dark1": "#86888B", "dark2": "#78797D", "dark3": "#67686B", "dark4": "#535357"}[name]))
# The faint blue and green tints of the washes.
tint_b = (wash[:, :, 2] - wash[:, :, 0] > 5) & (WL > 120)
tint_g = (wash[:, :, 1] - wash[:, :, 0] > 4) & (WL > 125)

out = []
for name, m, col in layers:
    if m.sum() < 200: continue
    g, d = trace(m, name, turd=80, alpha=1.2)
    out.append((name, col, g, d))
tints = []
for name, m in [("tintb", tint_b), ("tintg", tint_g)]:
    if m.sum() < 200: continue
    g, d = trace(m, name, turd=80, alpha=1.2)
    tints.append((name, colour(m), g, d))
ig, idd = trace(ink, "ink", turd=6, alpha=0.9)
pg, pd = trace(pencil, "pencil", turd=45, alpha=1.0)

# The sheet's corners (where its four edges would meet), in crop coordinates.
corners = [(984 - X0, 413 - Y0), (1831 - X0, 941 - Y0), (965 - X0, 1503 - Y0), (332 - X0, 893 - Y0)]
pts = " ".join(f"{x},{y}" for x, y in corners)

# Square: the sheet was drawn at an angle, so it is clipped away a little inside its edges (its edge lines go with
# it) and the drawing stands upright on a square tile of the sheet's grey, centred on what is drawn.
cx, cy = sum(x for x, _ in corners) / 4, sum(y for _, y in corners) / 4
inner = " ".join(f"{cx + (x - cx) * 0.93:.0f},{cy + (y - cy) * 0.93:.0f}" for x, y in corners)
SIDE, TILE_X, TILE_Y = 1180, 137, -59          # around the drawing (946 x 692 of it), in the group's coordinates
shift = (W - H) / 2
svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" '
       f'viewBox="{TILE_X} {TILE_Y + shift:.0f} {SIDE} {SIDE}">',
       f'<g transform="translate(0,{shift:.0f})">',
       '<defs><filter id="wet" x="-5%" y="-5%" width="110%" height="110%"><feGaussianBlur stdDeviation="5"/></filter></defs>',
       f'<clipPath id="sheet"><polygon points="{inner}"/></clipPath>',
       f'<rect x="{TILE_X}" y="{TILE_Y}" width="{SIDE}" height="{SIDE}" rx="72" fill="#8F8F8F"/>',
       '<g clip-path="url(#sheet)">',
       '<g filter="url(#wet)">']
for name, col, g, d in out:
    svg.append(f'<g transform="{g}"><path fill="{col}" d="{d}"/></g>')
for name, col, g, d in tints:
    svg.append(f'<g transform="{g}" opacity="0.55"><path fill="{col}" d="{d}"/></g>')
svg.append('</g>')
svg.append(f'<g transform="{pg}" opacity="0.8"><path fill="#4B4B50" d="{pd}"/></g>')
svg.append(f'<g transform="{ig}"><path fill="#141414" d="{idd}"/></g>')
svg.append('</g></g></svg>')
open("mark.svg", "w").write("\n".join(svg) + "\n")
print(W, H, [(n, c) for n, c, *_ in out], [(n, c) for n, c, *_ in tints])
