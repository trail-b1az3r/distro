# Write

The distribution's writer and e-book reader (packaged as `<id>-write`): Qt
Quick and C++.

* **Write**: MDXL documents with syntax colours (KDE's "Markdown Extended
  Logic" definition from the `mdxl` package) and a live preview rendered by
  MDXL itself (`data/mdxl-render.py` keeps `mdxl_preview.render_mdxl`
  running), so every MDXL feature shows as `mdxl-preview` shows it. Edit,
  both side by side, or preview only (Ctrl+E). Saved automatically.
* **Notes**: `~/Documents/Notes`, newest first, searchable. Ctrl+N starts one.
* **Books**: a book is a folder of MDXL chapters in `~/Documents/Books`
  (`01-…`, `02-…`); **Reading** opens EPUB books a chapter at a time with
  their table of contents, remembers where you were, and sizes the text.
* **Theme**: the colours of the desktop's current Halcyon theme
  (`~/.local/state/quickshell/user/generated/colors.json`, followed live),
  dark copper without one; Material style, Google Sans Flex and JetBrains Mono.

## Keyboard shortcuts

| Shortcut | Action |
|---|---|
| Ctrl+N | New note |
| Ctrl+O | Open a document or EPUB |
| Ctrl+S | Save the current document |
| Ctrl+Shift+S | Save as |
| Ctrl+1 / 2 / 3 / 4 | Write / Notes / Books / Reading |
| Ctrl+E | Cycle Edit, Both and Preview |
| Ctrl+Shift+E | Toggle Preview and Both |
| Ctrl+PageUp / PageDown | Previous / next section |
| Ctrl+Alt+1 / 2 / 3 / 4 | Alternate navigation shortcuts |

Reading shortcuts are available when an EPUB is open. Ctrl+4 and Ctrl+Alt+4
are ignored when there is no open book.

```bash
cmake -S apps/write -B build/write -G Ninja && cmake --build build/write
WRITE_MDXL_RENDER=apps/write/data/mdxl-render.py MDXL_LIB=/path/to/mdxl build/write/nexora-write
build/write/nexora-write --self-test book.epub note.mdxl   # loads them headless, prints what loaded
```

Needs Qt 6.5+ (Quick, Quick Controls, WebEngine), KF6 SyntaxHighlighting and
libarchive.
