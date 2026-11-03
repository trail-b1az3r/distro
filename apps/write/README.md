# Write

The distribution's writer and e-book reader (packaged as `<id>-write`): Qt Quick and C++.

* **Write**: MDXL documents with KDE syntax highlighting and a live preview rendered by MDXL itself. Choose Edit, Both, Preview, or Document layout. The formatting ribbon inserts headings, bold, italic, strike-through, links, quotes, bullet and numbered lists, checklists, inline/block code and tables. Undo/redo and autosave are included.
* **Document view**: a centered, paper-like reading layout. The application chrome continues to use the active Halcyon color theme.
* **Notes**: `~/Documents/Notes`, newest first, searchable. Ctrl+N starts one.
* **Books**: a book is a folder of MDXL chapters in `~/Documents/Books` (`01-…`, `02-…`); **Reading** opens EPUB books a chapter at a time with their table of contents, remembers where you were, and sizes the text.
* **Theme**: the colours of the desktop's current Halcyon theme (`~/.local/state/quickshell/user/generated/colors.json`, followed live), dark copper without one; Material controls, Google Sans Flex and JetBrains Mono.

## Keyboard shortcuts

| Shortcut | Action |
|---|---|
| Ctrl+N | New note |
| Ctrl+O | Open a document or EPUB |
| Ctrl+S | Save the current document |
| Ctrl+Shift+S | Save as |
| Ctrl+1 / 2 / 3 / 4 | Write / Notes / Books / Reading |
| Ctrl+E | Cycle Edit, Both, Preview and Document |
| Ctrl+Shift+E | Toggle Preview and Both |
| Ctrl+PageUp / PageDown | Previous / next section |
| Ctrl+Alt+1 / 2 / 3 / 4 | Alternate navigation shortcuts |

Reading shortcuts are available when an EPUB is open. Ctrl+4 and Ctrl+Alt+4 are ignored when there is no open book.

```bash
cmake -S apps/write -B build/write -G Ninja && cmake --build build/write
WRITE_MDXL_RENDER=apps/write/data/mdxl-render.py MDXL_LIB=/path/to/mdxl build/write/nexora-write
build/write/nexora-write --self-test book.epub note.mdxl
```

Needs Qt 6.5+ (Quick, Quick Controls, WebEngine), KF6 SyntaxHighlighting and libarchive.
