# Write

The distribution's writer and e-book reader (packaged as `<id>-write`): Qt Quick/QML frontend with a Rust application backend.

* **Write**: MDXL documents with KDE syntax highlighting and a live preview rendered by MDXL itself. Choose Edit, Both, Preview, or Document layout. The formatting ribbon inserts headings, bold, italic, strike-through, links, quotes, bullet and numbered lists, checklists, inline/block code and tables. Undo/redo and autosave are included.
* **Document view**: an A4-sized paper layout with print-oriented page dimensions. The application chrome continues to use the active Halcyon color theme.
* **Word documents**: import `.docx` into an editable MDXL note and export notes as `.docx`, including paragraphs, headings, basic tables and explicit page breaks. The new review/header/footer markers are Write-native MDXL metadata; full Microsoft Word interoperability for comments and tracked-revision history is still pending.
* **PDF export**: export the current rendered document from the paper layout to a PDF.
* **Headers and footers**: add document-level header/footer text from the ribbon; the metadata is stored in MDXL and shown in Document preview.\n* **Review tools**: mark selected text as an insertion or deletion, then accept or reject all pending marks. Add comments anchored to selected text; comments appear in the preview review panel and remain in the MDXL source.\n* **Email**: the Email command is disabled unless the `betterbird` executable is installed. When enabled, it opens a prefilled message in Betterbird for review and sending; Write does not silently send mail.\n* **Page breaks**: insert a page break from the formatting ribbon; the marker remains in MDXL, renders as a page break in Document view, and exports as a Word page break.
* **Notes**: `~/Documents/Notes`, newest first, searchable. Ctrl+N starts one.
* **Books**: a book is a folder of MDXL chapters in `~/Documents/Books` (`01-…`, `02-…`); **Reading** opens EPUB books a chapter at a time with their table of contents, remembers where you were, and sizes the text.
* **Theme and interface**: translucent, rounded Material 3 Expressive surfaces inspired by Loaf's visual language; desktop Halcyon colours (`~/.local/state/quickshell/user/generated/colors.json`, followed live), dark copper without one, Google Sans Flex and JetBrains Mono.
* **Book tiles and reading**: tile-based note/book libraries, a collapsible contents sidebar, immersive full-page reading, keyboard navigation and edge-drag page turns (with chapter transitions at section boundaries). Both EPUBs and native MDXL book folders can be read.
* **MDXL books and images**: MDXL books render through the MDXL renderer with their book folder as the asset base URL. Standard Markdown image syntax (for example `![Cover](images/cover.png)`) and MDXL true-color text (for example `/col//Signal /col#B7F77A//`) are rendered as formatted content. Keep referenced images inside the book folder so relative paths resolve.

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


## Architecture migration

The UI remains Qt Quick/QML. Application operations are being moved into the standalone Rust backend in `backend/`, built and installed beside the UI as `nexora-write-backend`. The current migration is still in progress; the Rust service is not yet the sole backend. Its newline-delimited JSON protocol keeps Qt concerns out of the Rust core. The Rust implementation currently handles file reads and writes, word counts, library listing, notes, books, chapters and safe image-asset imports. The existing C++ implementations remain compatibility paths during migration; EPUB, DOCX, PDF, MDXL rendering, autosave and settings are not considered migrated until equivalent Rust implementations are wired in and covered by tests. No existing feature is intentionally removed during this transition.
