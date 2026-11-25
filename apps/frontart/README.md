# FrontArt

Frontline's painting program (packaged as `<id>-frontart`), in Qt Widgets and C++.

* **Brushes**: brush, pencil, ink pen, marker, airbrush, soft round and eraser. Each has size, opacity, flow and
  hardness. A stroke never darkens itself past its opacity: dabs collect in a stroke buffer, which is merged when the
  pen lifts. The airbrush keeps spraying while the pen rests.
* **Pen**: pressure changes size and/or strength (per brush), the **Pen pressure** slider bends the curve (a light
  touch or a firm one), and the pen's eraser end erases. Every pen sample is used (tablet events are not compressed);
  the mouse paints at full pressure. Shift-click draws a straight line from where the last stroke ended.
* **Layers**: add, duplicate, delete, reorder, merge down, hide, rename (double-click), lock transparency, opacity and
  twelve blend modes (multiply, screen, overlay...).
* **Fill** finds the area in the whole picture (so line art on its own layer holds the paint in) and fills on the
  current layer, a pixel past the edge so anti-aliased lines leave no pale fringe. **Pick colour** (or Alt-click).
* **Mirror painting** paints every dab mirrored across the middle, too.
* **View**: zoom with the wheel (around the pointer), rotate with Shift+wheel or 4 / 6, mirror the view with M, pan
  with the middle button, space+drag or H, fit with Ctrl+0.
* **Undo** keeps only the area a step changed, 80 steps back.
* **Files**: OpenRaster (`.ora`), with every layer, its opacity, blend mode and visibility, plus the merged picture and
  a thumbnail; Krita, GIMP and MyPaint open it. PNG, JPEG, WebP and other pictures open as one layer, and **Export**
  writes a flat PNG, JPEG or WebP.
* **Look**: the desktop's Halcyon colours (`~/.local/state/quickshell/user/generated/colors.json`), else a dark
  default.

| Key | Action |
|---|---|
| B / E / G / I / H | Paint / erase / fill / pick colour / move the view |
| [ and ] | Smaller / bigger brush |
| Ctrl+Z, Ctrl+Shift+Z | Undo, redo |
| Ctrl+0, Ctrl+1 | Fit, actual size |
| 4, 6, 5, M | Rotate left, right, reset the view, mirror the view |
| Delete | Clear the layer |

`frontline-frontart --self-test` paints with pressure, fills, undoes and redoes, and round-trips OpenRaster without a
screen; the package's `check()` runs it.
