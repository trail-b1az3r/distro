# Nexora Write Rust backend

The Qt Quick frontend remains responsible for rendering and interaction. This
process owns application operations and communicates over newline-delimited
JSON on stdin/stdout. One request produces exactly one JSON reply; diagnostics
must go to stderr so the protocol remains machine-readable.

The backend is intentionally independent of Qt. The initial command set covers
atomic document writes, reads, word counts, library listing, note/book creation,
and chapter creation. EPUB parsing, DOCX conversion, MDXL rendering, autosave,
and settings are migration targets; they must not be removed from the existing
frontend until their Rust replacements are implemented and tested.

Build and test:

```sh
cargo test --manifest-path apps/write/backend/Cargo.toml
cargo build --release --manifest-path apps/write/backend/Cargo.toml
```
