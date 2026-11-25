#pragma once

#include "brush.h"
#include "document.h"

#include <QElapsedTimer>
#include <QImage>
#include <QPointF>
#include <QTransform>
#include <QWidget>

// The drawing surface: shows the document through a view (zoom, pan, rotation, a mirrored view) and paints into the
// current layer with the pen (pressure and tilt from a tablet) or the mouse.
class Canvas : public QWidget {
    Q_OBJECT
public:
    enum Tool { Paint, Fill, Picker, Pan };

    explicit Canvas(Document *doc, QWidget *parent = nullptr);

    void setBrush(const Brush &brush) { m_brush = brush; update(); }
    const Brush &brush() const { return m_brush; }
    void setColor(const QColor &c) { m_color = c; }
    QColor color() const { return m_color; }
    void setTool(Tool tool);
    Tool tool() const { return m_tool; }
    void setPressureSoftness(qreal s) { m_softness = s; }
    void setMirror(bool on) { m_mirror = on; update(); }
    bool mirror() const { return m_mirror; }
    void setFillTolerance(int t) { m_tolerance = t; }

    // The view.
    void zoomBy(qreal factor, QPointF around = {});
    void setZoom(qreal zoom);
    qreal zoom() const { return m_zoom; }
    void rotateBy(qreal degrees);
    void flipView();
    void fit();
    void resetView();

    // Painting from code (the self-test, and the line tool): a stroke through points with pressures.
    void strokeBegin(QPointF docPoint, qreal pressure);
    void strokeTo(QPointF docPoint, qreal pressure);
    void strokeEnd();
    void fill(QPoint docPoint);
    QColor pick(QPoint docPoint) const;

signals:
    void colorPicked(const QColor &color);
    void zoomChanged(qreal zoom);
    void cursorAt(QPoint docPoint);

protected:
    void paintEvent(QPaintEvent *) override;
    void tabletEvent(QTabletEvent *event) override;
    void mousePressEvent(QMouseEvent *event) override;
    void mouseMoveEvent(QMouseEvent *event) override;
    void mouseReleaseEvent(QMouseEvent *event) override;
    void wheelEvent(QWheelEvent *event) override;
    void keyPressEvent(QKeyEvent *event) override;
    void keyReleaseEvent(QKeyEvent *event) override;
    void resizeEvent(QResizeEvent *event) override;

private:
    void press(QPointF widgetPos, qreal pressure, Qt::MouseButton button, Qt::KeyboardModifiers mods);
    void move(QPointF widgetPos, qreal pressure, Qt::MouseButtons buttons);
    void release();
    void dab(QPointF at, qreal pressure);
    void dabOnce(QPointF at, qreal size, qreal alpha);
    QTransform view() const;
    QPointF toDoc(QPointF widgetPos) const { return view().inverted().map(widgetPos); }
    void updateDoc(const QRectF &docRect);
    void commitStroke();
    void rebuildCache(const QRect &area = {});

    Document *m_doc;
    Brush m_brush;
    QColor m_color = Qt::black;
    Tool m_tool = Paint;
    qreal m_softness = 0.5;
    bool m_mirror = false;
    int m_tolerance = 32;

    // The view: the document is drawn scaled by m_zoom, rotated, and its centre placed at m_center + widget centre.
    qreal m_zoom = 1.0;
    qreal m_rotation = 0.0;
    bool m_flipped = false;
    QPointF m_offset;

    // A stroke: dabs go into m_stroke (a layer-sized buffer), shown over the layer, and merged into it at the end at
    // the brush's opacity, so a stroke never darkens itself beyond that. The airbrush and the eraser work directly.
    bool m_stroking = false;
    QImage m_stroke;
    QImage m_before;         // the layer as it was, for undo
    QRect m_dirty;
    QPointF m_last;
    qreal m_lastPressure = 1;
    qreal m_carry = 0;       // distance left over from the last segment, so dabs stay evenly spaced
    QPointF m_lineAnchor;
    bool m_hasLineAnchor = false;

    // The composite of every layer below and above the current one, so a stroke only redraws its own layer.
    QImage m_below, m_above;
    bool m_cacheValid = false;

    bool m_panning = false;
    bool m_spaceHeld = false;
    QPointF m_panFrom;
    bool m_tabletActive = false;
    Brush m_eraserSaved;        // the brush, while the pen's eraser end is in use
    bool m_eraserActive = false;
    QPointF m_hover;
    bool m_hovering = false;
};
