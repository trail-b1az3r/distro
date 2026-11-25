#include "canvas.h"

#include <QKeyEvent>
#include <QMouseEvent>
#include <QPainter>
#include <QPainterPath>
#include <QRadialGradient>
#include <QTabletEvent>
#include <QTimer>
#include <QWheelEvent>
#include <QtMath>

#include <cmath>
#include <stack>

Canvas::Canvas(Document *doc, QWidget *parent) : QWidget(parent), m_doc(doc)
{
    setAttribute(Qt::WA_OpaquePaintEvent);
    setAttribute(Qt::WA_TabletTracking);
    setMouseTracking(true);
    setFocusPolicy(Qt::StrongFocus);
    setCursor(Qt::BlankCursor);
    connect(doc, &Document::changed, this, [this](const QRect &) { m_cacheValid = false; update(); });
    connect(doc, &Document::layersChanged, this, [this] { m_cacheValid = false; update(); });
    connect(doc, &Document::sizeChanged, this, [this] { m_stroke = {}; fit(); });

    // The airbrush keeps spraying while the pen rests.
    auto *spray = new QTimer(this);
    spray->setInterval(33);
    connect(spray, &QTimer::timeout, this, [this] {
        if (m_stroking && m_brush.buildsUp)
            dab(m_last, m_lastPressure);
    });
    spray->start();
}

// ── The view ────────────────────────────────────────────────────────────────────────────────────────────────────────

QTransform Canvas::view() const
{
    QTransform t;
    t.translate(width() / 2.0 + m_offset.x(), height() / 2.0 + m_offset.y());
    t.rotate(m_rotation);
    t.scale(m_flipped ? -m_zoom : m_zoom, m_zoom);
    t.translate(-m_doc->size().width() / 2.0, -m_doc->size().height() / 2.0);
    return t;
}

void Canvas::setZoom(qreal zoom)
{
    m_zoom = qBound(0.02, zoom, 64.0);
    emit zoomChanged(m_zoom);
    update();
}

void Canvas::zoomBy(qreal factor, QPointF around)
{
    if (around.isNull())
        around = QPointF(width() / 2.0, height() / 2.0);
    const QPointF docPoint = toDoc(around);
    setZoom(m_zoom * factor);
    // Keep the point under the cursor where it was.
    m_offset += around - view().map(docPoint);
    update();
}

void Canvas::rotateBy(qreal degrees)
{
    m_rotation = std::fmod(m_rotation + degrees, 360.0);
    update();
}

void Canvas::flipView()
{
    m_flipped = !m_flipped;
    update();
}

void Canvas::fit()
{
    const QSize s = m_doc->size();
    if (s.isEmpty() || width() < 10)
        return;
    m_offset = {};
    m_rotation = 0;
    setZoom(qMin((width() - 48.0) / s.width(), (height() - 48.0) / s.height()));
}

void Canvas::resetView()
{
    m_offset = {};
    m_rotation = 0;
    m_flipped = false;
    setZoom(1.0);
}

void Canvas::setTool(Tool tool)
{
    m_tool = tool;
    setCursor(tool == Paint ? Qt::BlankCursor : tool == Pan ? Qt::OpenHandCursor : Qt::CrossCursor);
    update();
}

// ── Drawing the canvas ──────────────────────────────────────────────────────────────────────────────────────────────

void Canvas::rebuildCache(const QRect &)
{
    const auto &layers = m_doc->layers();
    const int current = m_doc->current();
    m_below = QImage(m_doc->size(), QImage::Format_ARGB32_Premultiplied);
    m_below.fill(Qt::transparent);
    QPainter p(&m_below);
    for (int i = 0; i < current && i < layers.size(); ++i) {
        if (!layers[i].visible)
            continue;
        p.setCompositionMode(layers[i].mode);
        p.setOpacity(layers[i].opacity);
        p.drawImage(0, 0, layers[i].image);
    }
    m_cacheValid = true;
}

void Canvas::paintEvent(QPaintEvent *event)
{
    QPainter p(this);
    const QColor back = palette().color(QPalette::Window).darker(118);
    p.fillRect(event->rect(), back);
    if (m_doc->layers().isEmpty())
        return;
    if (!m_cacheValid)
        rebuildCache();

    const QTransform t = view();
    // The part of the document this repaint shows.
    const QRect area = t.inverted().mapRect(QRectF(event->rect())).toAlignedRect().adjusted(-2, -2, 2, 2)
                           .intersected(m_doc->rect());
    if (area.isEmpty())
        return;

    // Transparent parts show a checkerboard.
    QImage picture(area.size(), QImage::Format_ARGB32_Premultiplied);
    {
        QPainter c(&picture);
        static QPixmap checker = [] {
            QPixmap pm(16, 16);
            pm.fill(QColor(200, 200, 200));
            QPainter cp(&pm);
            cp.fillRect(0, 0, 8, 8, QColor(235, 235, 235));
            cp.fillRect(8, 8, 8, 8, QColor(235, 235, 235));
            return pm;
        }();
        c.drawTiledPixmap(picture.rect(), checker, area.topLeft());
        c.drawImage(QPoint(0, 0), m_below, area);

        const auto &layers = m_doc->layers();
        const int current = m_doc->current();
        for (int i = current; i < layers.size(); ++i) {
            const Layer &layer = layers[i];
            if (!layer.visible)
                continue;
            c.setCompositionMode(layer.mode);
            c.setOpacity(layer.opacity);
            if (i == current && m_stroking && !m_stroke.isNull()) {
                // The layer as it will be when the stroke is merged.
                QImage live = layer.image.copy(area);
                QPainter lp(&live);
                lp.setOpacity(m_brush.opacity);
                lp.setCompositionMode(m_brush.kind == Brush::Eraser ? QPainter::CompositionMode_DestinationOut
                                      : layer.locked ? QPainter::CompositionMode_SourceAtop
                                                     : QPainter::CompositionMode_SourceOver);
                lp.drawImage(QPoint(0, 0), m_stroke, area);
                lp.end();
                c.drawImage(QPoint(0, 0), live);
            } else {
                c.drawImage(QPoint(0, 0), layer.image, area);
            }
        }
    }

    p.setTransform(t);
    p.setRenderHint(QPainter::SmoothPixmapTransform, m_zoom < 2.0);
    p.drawImage(area.topLeft(), picture);
    // A thin frame around the page.
    p.setPen(QPen(QColor(0, 0, 0, 60), 0));
    p.setBrush(Qt::NoBrush);
    p.drawRect(QRectF(m_doc->rect()));
    if (m_mirror) {
        p.setPen(QPen(QColor(80, 140, 255, 140), 0, Qt::DashLine));
        p.drawLine(QPointF(m_doc->size().width() / 2.0, 0), QPointF(m_doc->size().width() / 2.0, m_doc->size().height()));
    }

    // The brush outline where the pen is.
    if (m_hovering && m_tool == Paint) {
        p.resetTransform();
        const qreal r = qMax(1.5, m_brush.size * m_zoom / 2.0);
        p.setRenderHint(QPainter::Antialiasing);
        p.setPen(QPen(QColor(255, 255, 255, 200), 1.5));
        p.drawEllipse(m_hover, r, r);
        p.setPen(QPen(QColor(0, 0, 0, 160), 1.0));
        p.drawEllipse(m_hover, r + 1.2, r + 1.2);
        if (r < 4) {
            p.drawLine(m_hover - QPointF(8, 0), m_hover - QPointF(4, 0));
            p.drawLine(m_hover + QPointF(4, 0), m_hover + QPointF(8, 0));
        }
    }
}

void Canvas::updateDoc(const QRectF &docRect)
{
    update(view().mapRect(docRect).toAlignedRect().adjusted(-3, -3, 3, 3));
}

// ── Strokes ─────────────────────────────────────────────────────────────────────────────────────────────────────────

void Canvas::strokeBegin(QPointF docPoint, qreal pressure)
{
    if (m_doc->layers().isEmpty())
        return;
    Layer &layer = m_doc->currentLayer();
    if (!layer.visible)
        return;    // painting on a hidden layer would be invisible work
    if (m_stroke.size() != m_doc->size()) {
        m_stroke = QImage(m_doc->size(), QImage::Format_ARGB32_Premultiplied);
        m_stroke.fill(Qt::transparent);
    }
    m_before = layer.image;   // shared until the layer is written
    m_dirty = {};
    m_stroking = true;
    m_carry = 0;
    m_last = docPoint;
    m_lastPressure = pressure;
    dab(docPoint, pressure);
}

void Canvas::strokeTo(QPointF docPoint, qreal pressure)
{
    if (!m_stroking)
        return;
    const QPointF from = m_last;
    const qreal fromPressure = m_lastPressure;
    const qreal distance = QLineF(from, docPoint).length();
    // Dabs every `spacing` of the brush's size at that pressure, carried over from the last segment.
    qreal travelled = 0;
    while (true) {
        const qreal t = distance > 0 ? travelled / distance : 1;
        const qreal p = fromPressure + (pressure - fromPressure) * qMin(t, 1.0);
        const qreal size = m_brush.size * (m_brush.pressureSize ? m_brush.minSize + (1 - m_brush.minSize) * pressureCurve(p, m_softness) : 1.0);
        const qreal step = qMax(0.5, size * m_brush.spacing);
        const qreal next = travelled + (step - m_carry);
        if (next > distance) {
            m_carry += distance - travelled;
            break;
        }
        travelled = next;
        m_carry = 0;
        const qreal at = distance > 0 ? travelled / distance : 1;
        dab(from + (docPoint - from) * at, fromPressure + (pressure - fromPressure) * at);
    }
    m_last = docPoint;
    m_lastPressure = pressure;
}

void Canvas::dab(QPointF at, qreal pressure)
{
    const qreal curve = pressureCurve(pressure, m_softness);
    const qreal size = m_brush.size * (m_brush.pressureSize ? m_brush.minSize + (1 - m_brush.minSize) * curve : 1.0);
    const qreal alpha = m_brush.flow * (m_brush.pressureOpacity ? qMax(0.05, curve) : 1.0);
    dabOnce(at, size, alpha);
    if (m_mirror)
        dabOnce(QPointF(m_doc->size().width() - at.x(), at.y()), size, alpha);
}

void Canvas::dabOnce(QPointF at, qreal size, qreal alpha)
{
    size = qMax(0.6, size);
    const qreal r = size / 2.0;
    const QRectF box(at.x() - r, at.y() - r, size, size);
    QPainter p(&m_stroke);
    p.setRenderHint(QPainter::Antialiasing);
    QColor c = m_brush.kind == Brush::Eraser ? QColor(Qt::black) : m_color;
    c.setAlphaF(qBound(0.0, alpha, 1.0) * c.alphaF());
    if (m_brush.hardness >= 0.99 || size < 2.5) {
        p.setPen(Qt::NoPen);
        p.setBrush(c);
        p.drawEllipse(box);
    } else {
        QRadialGradient g(at, r);
        QColor clear = c;
        clear.setAlpha(0);
        g.setColorAt(0, c);
        g.setColorAt(qBound(0.0, m_brush.hardness, 0.98), c);
        g.setColorAt(1, clear);
        p.setPen(Qt::NoPen);
        p.setBrush(g);
        p.drawEllipse(box);
    }
    p.end();
    const QRect touched = box.toAlignedRect().adjusted(-1, -1, 1, 1);
    m_dirty = m_dirty.united(touched);
    updateDoc(touched);
}

void Canvas::strokeEnd()
{
    if (!m_stroking)
        return;
    commitStroke();
    m_stroking = false;
    m_lineAnchor = m_last;
    m_hasLineAnchor = true;
}

void Canvas::commitStroke()
{
    const QRect area = m_dirty.intersected(m_doc->rect());
    if (area.isEmpty())
        return;
    const int index = m_doc->current();
    Layer &layer = m_doc->currentLayer();
    {
        QPainter p(&layer.image);
        p.setOpacity(m_brush.opacity);
        p.setCompositionMode(m_brush.kind == Brush::Eraser ? QPainter::CompositionMode_DestinationOut
                             : layer.locked ? QPainter::CompositionMode_SourceAtop : QPainter::CompositionMode_SourceOver);
        p.drawImage(area.topLeft(), m_stroke, area);
    }
    {
        QPainter clear(&m_stroke);
        clear.setCompositionMode(QPainter::CompositionMode_Clear);
        clear.fillRect(area, Qt::transparent);
    }
    m_doc->pixelsChanged(index, area, m_before.copy(area), m_brush.kind == Brush::Eraser ? tr("Erase") : tr("Paint"));
    m_before = {};
    updateDoc(area);
}

// ── Fill and picker ─────────────────────────────────────────────────────────────────────────────────────────────────

QColor Canvas::pick(QPoint docPoint) const
{
    if (!m_doc->rect().contains(docPoint))
        return m_color;
    const QImage one = m_doc->composite(QRect(docPoint, QSize(1, 1)));
    QColor c = QColor::fromRgba(one.convertToFormat(QImage::Format_ARGB32).pixel(0, 0));
    if (c.alpha() == 0)
        return m_color;
    c.setAlpha(255);
    return c;
}

void Canvas::fill(QPoint docPoint)
{
    if (!m_doc->rect().contains(docPoint))
        return;
    // The area is found in the picture as it looks (so line art on another layer holds the paint in), and filled on
    // the current layer.
    const QImage seen = m_doc->composite().convertToFormat(QImage::Format_ARGB32);
    const int w = seen.width(), h = seen.height();
    const QRgb seed = seen.pixel(docPoint);
    const int tol = m_tolerance * m_tolerance * 4;
    auto similar = [&](QRgb c) {
        const int dr = qRed(c) - qRed(seed), dg = qGreen(c) - qGreen(seed), db = qBlue(c) - qBlue(seed), da = qAlpha(c) - qAlpha(seed);
        return dr * dr + dg * dg + db * db + da * da <= tol;
    };
    QImage mask(w, h, QImage::Format_Alpha8);
    mask.fill(0);
    std::stack<QPoint> todo;
    todo.push(docPoint);
    QRect bounds;
    while (!todo.empty()) {
        QPoint pt = todo.top();
        todo.pop();
        int x = pt.x();
        const int y = pt.y();
        uchar *row = mask.scanLine(y);
        const QRgb *src = reinterpret_cast<const QRgb *>(seen.constScanLine(y));
        while (x > 0 && !row[x - 1] && similar(src[x - 1]))
            --x;
        bool up = false, down = false;
        const int start = x;
        for (; x < w && !row[x] && similar(src[x]); ++x) {
            row[x] = 255;
            if (y > 0) {
                const bool fits = !mask.constScanLine(y - 1)[x] && similar(reinterpret_cast<const QRgb *>(seen.constScanLine(y - 1))[x]);
                if (fits && !up) todo.push(QPoint(x, y - 1));
                up = fits;
            }
            if (y < h - 1) {
                const bool fits = !mask.constScanLine(y + 1)[x] && similar(reinterpret_cast<const QRgb *>(seen.constScanLine(y + 1))[x]);
                if (fits && !down) todo.push(QPoint(x, y + 1));
                down = fits;
            }
        }
        bounds = bounds.united(QRect(start, y, x - start, 1));
    }
    if (bounds.isEmpty())
        return;
    // One pixel more all round, so the paint meets anti-aliased lines without a pale fringe.
    bounds = bounds.adjusted(-1, -1, 1, 1).intersected(m_doc->rect());
    QImage colour(w, h, QImage::Format_ARGB32_Premultiplied);
    colour.fill(Qt::transparent);
    {
        QImage grown = mask.copy();
        for (int y = bounds.top(); y <= bounds.bottom(); ++y)
            for (int x = bounds.left(); x <= bounds.right(); ++x)
                if (!mask.constScanLine(y)[x])
                    for (int dy = -1; dy <= 1 && !grown.constScanLine(y)[x]; ++dy)
                        for (int dx = -1; dx <= 1; ++dx) {
                            const int nx = x + dx, ny = y + dy;
                            if (nx >= 0 && ny >= 0 && nx < w && ny < h && mask.constScanLine(ny)[nx]) {
                                grown.scanLine(y)[x] = 255;
                                break;
                            }
                        }
        QPainter cp(&colour);
        cp.fillRect(bounds, m_color);
        cp.setCompositionMode(QPainter::CompositionMode_DestinationIn);
        cp.drawImage(0, 0, grown);
    }
    const int index = m_doc->current();
    Layer &layer = m_doc->currentLayer();
    const QImage before = layer.image.copy(bounds);
    {
        QPainter p(&layer.image);
        p.setCompositionMode(layer.locked ? QPainter::CompositionMode_SourceAtop : QPainter::CompositionMode_SourceOver);
        p.drawImage(bounds.topLeft(), colour, bounds);
    }
    m_doc->pixelsChanged(index, bounds, before, tr("Fill"));
    emit m_doc->changed(bounds);
}

// ── Input ───────────────────────────────────────────────────────────────────────────────────────────────────────────

void Canvas::press(QPointF pos, qreal pressure, Qt::MouseButton button, Qt::KeyboardModifiers mods)
{
    setFocus();
    if (button == Qt::MiddleButton || m_spaceHeld || m_tool == Pan) {
        m_panning = true;
        m_panFrom = pos;
        setCursor(Qt::ClosedHandCursor);
        return;
    }
    if (button != Qt::LeftButton)
        return;
    const QPointF d = toDoc(pos);
    if (m_tool == Picker || (mods & Qt::AltModifier)) {
        m_color = pick(d.toPoint());
        emit colorPicked(m_color);
        return;
    }
    if (m_tool == Fill) {
        fill(d.toPoint());
        return;
    }
    if ((mods & Qt::ShiftModifier) && m_hasLineAnchor) {
        // Shift: a straight line from where the last stroke ended.
        strokeBegin(m_lineAnchor, pressure);
        strokeTo(d, pressure);
        strokeEnd();
        return;
    }
    strokeBegin(d, pressure);
}

void Canvas::move(QPointF pos, qreal pressure, Qt::MouseButtons)
{
    const QPointF before = m_hover;
    m_hover = pos;
    m_hovering = true;
    if (m_panning) {
        m_offset += pos - m_panFrom;
        m_panFrom = pos;
        update();
        return;
    }
    if (m_stroking)
        strokeTo(toDoc(pos), pressure);
    emit cursorAt(toDoc(pos).toPoint());
    // Repaint where the brush outline was and is.
    const qreal r = m_brush.size * m_zoom / 2.0 + 4;
    update(QRectF(before - QPointF(r, r), QSizeF(2 * r, 2 * r)).toAlignedRect());
    update(QRectF(pos - QPointF(r, r), QSizeF(2 * r, 2 * r)).toAlignedRect());
}

void Canvas::release()
{
    if (m_panning) {
        m_panning = false;
        setCursor(m_tool == Paint ? Qt::BlankCursor : m_tool == Pan ? Qt::OpenHandCursor : Qt::CrossCursor);
        return;
    }
    strokeEnd();
}

void Canvas::tabletEvent(QTabletEvent *event)
{
    event->accept();
    const qreal pressure = event->pressure();
    switch (event->type()) {
    case QEvent::TabletPress: {
        m_tabletActive = true;
        // The pen's eraser end erases, whatever brush is chosen; the brush comes back when the stroke ends.
        if (event->pointerType() == QPointingDevice::PointerType::Eraser && m_brush.kind != Brush::Eraser) {
            m_eraserSaved = m_brush;
            m_eraserActive = true;
            for (const Brush &b : Brush::presets())
                if (b.kind == Brush::Eraser)
                    m_brush = b;
            m_brush.size = m_eraserSaved.size * 1.5;
        }
        press(event->position(), pressure, event->button(), event->modifiers());
        break;
    }
    case QEvent::TabletMove:
        move(event->position(), pressure, event->buttons());
        break;
    case QEvent::TabletRelease:
        release();
        if (m_eraserActive) {
            m_brush = m_eraserSaved;
            m_eraserActive = false;
        }
        m_tabletActive = false;
        break;
    default:
        break;
    }
}

void Canvas::mousePressEvent(QMouseEvent *event)
{
    if (m_tabletActive || event->source() == Qt::MouseEventSynthesizedBySystem)
        return;   // the tablet event did it already
    press(event->position(), 1.0, event->button(), event->modifiers());
}

void Canvas::mouseMoveEvent(QMouseEvent *event)
{
    if (m_tabletActive)
        return;
    move(event->position(), 1.0, event->buttons());
}

void Canvas::mouseReleaseEvent(QMouseEvent *event)
{
    if (m_tabletActive)
        return;
    Q_UNUSED(event);
    release();
}

void Canvas::wheelEvent(QWheelEvent *event)
{
    const qreal steps = event->angleDelta().y() / 120.0;
    if (event->modifiers() & Qt::ShiftModifier)
        rotateBy(steps * 15);
    else
        zoomBy(qPow(1.2, steps), event->position());
    event->accept();
}

void Canvas::keyPressEvent(QKeyEvent *event)
{
    if (event->key() == Qt::Key_Space && !event->isAutoRepeat()) {
        m_spaceHeld = true;
        setCursor(Qt::OpenHandCursor);
        return;
    }
    QWidget::keyPressEvent(event);
}

void Canvas::keyReleaseEvent(QKeyEvent *event)
{
    if (event->key() == Qt::Key_Space && !event->isAutoRepeat()) {
        m_spaceHeld = false;
        setCursor(m_tool == Paint ? Qt::BlankCursor : m_tool == Pan ? Qt::OpenHandCursor : Qt::CrossCursor);
        return;
    }
    QWidget::keyReleaseEvent(event);
}

void Canvas::resizeEvent(QResizeEvent *)
{
    update();
}
