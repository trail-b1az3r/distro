#include "colorpicker.h"

#include <QLinearGradient>
#include <QMouseEvent>
#include <QPainter>
#include <QPainterPath>

#include <cmath>

static constexpr int kSwatches = 16;

ColorPicker::ColorPicker(QWidget *parent) : QWidget(parent)
{
    setMinimumSize(180, 230);
    m_recent = {Qt::black, Qt::white, QColor("#e23d3d"), QColor("#f29a2e"), QColor("#f2d22e"), QColor("#3dbb5a"),
                QColor("#2e8bf2"), QColor("#7a4df2")};
}

QRect ColorPicker::squareRect() const
{
    const int w = width() - 8;
    return QRect(4, 4, w, qMin(w, height() - 90));
}

QRect ColorPicker::hueRect() const
{
    const QRect sq = squareRect();
    return QRect(sq.left(), sq.bottom() + 10, sq.width(), 18);
}

QRect ColorPicker::swatchRect(int index) const
{
    const QRect hue = hueRect();
    const int size = (hue.width() - 7 * 4) / 8;
    return QRect(hue.left() + (index % 8) * (size + 4), hue.bottom() + 10 + (index / 8) * (size + 4), size, size);
}

void ColorPicker::setColor(const QColor &color)
{
    if (!color.isValid())
        return;
    m_color = color.toHsv();
    if (m_color.hsvHueF() >= 0)
        m_hue = m_color.hsvHueF();
    update();
}

void ColorPicker::remember(const QColor &color)
{
    m_recent.removeAll(color);
    m_recent.prepend(color);
    while (m_recent.size() > kSwatches)
        m_recent.removeLast();
    update();
}

void ColorPicker::paintEvent(QPaintEvent *)
{
    QPainter p(this);
    p.setRenderHint(QPainter::Antialiasing);
    const QRect sq = squareRect();

    // Saturation left to right over the hue, value bottom to top.
    QLinearGradient across(sq.topLeft(), sq.topRight());
    across.setColorAt(0, Qt::white);
    across.setColorAt(1, QColor::fromHsvF(m_hue, 1, 1));
    QLinearGradient down(sq.topLeft(), sq.bottomLeft());
    down.setColorAt(0, QColor(0, 0, 0, 0));
    down.setColorAt(1, Qt::black);
    QPainterPath rounded;
    rounded.addRoundedRect(sq, 8, 8);
    p.setClipPath(rounded);
    p.fillRect(sq, across);
    p.fillRect(sq, down);
    p.setClipping(false);

    const QPointF mark(sq.left() + m_color.hsvSaturationF() * sq.width(), sq.top() + (1 - m_color.valueF()) * sq.height());
    p.setBrush(Qt::NoBrush);
    p.setPen(QPen(Qt::white, 2));
    p.drawEllipse(mark, 6, 6);
    p.setPen(QPen(QColor(0, 0, 0, 120), 1));
    p.drawEllipse(mark, 7.5, 7.5);

    const QRect hue = hueRect();
    QLinearGradient hues(hue.topLeft(), hue.topRight());
    for (int i = 0; i <= 6; ++i)
        hues.setColorAt(i / 6.0, QColor::fromHsvF(std::fmod(i / 6.0, 1.0), 1, 1));
    p.setPen(Qt::NoPen);
    p.setBrush(hues);
    p.drawRoundedRect(hue, 9, 9);
    const qreal hx = hue.left() + m_hue * hue.width();
    p.setBrush(Qt::NoBrush);
    p.setPen(QPen(Qt::white, 2.5));
    p.drawRoundedRect(QRectF(hx - 4, hue.top() - 2, 8, hue.height() + 4), 3, 3);

    for (int i = 0; i < m_recent.size(); ++i) {
        const QRect r = swatchRect(i);
        p.setPen(QPen(palette().color(QPalette::Mid), 1));
        p.setBrush(m_recent[i]);
        p.drawRoundedRect(r, 5, 5);
    }
}

void ColorPicker::pickAt(QPoint pos, bool start)
{
    const QRect sq = squareRect(), hue = hueRect();
    if (start)
        m_dragging = sq.contains(pos) ? Square : hue.adjusted(0, -4, 0, 4).contains(pos) ? Hue : None;
    if (m_dragging == Square) {
        const qreal s = qBound(0.0, (pos.x() - sq.left()) / qreal(sq.width()), 1.0);
        const qreal v = qBound(0.0, 1 - (pos.y() - sq.top()) / qreal(sq.height()), 1.0);
        m_color = QColor::fromHsvF(m_hue, s, v);
    } else if (m_dragging == Hue) {
        m_hue = qBound(0.0, (pos.x() - hue.left()) / qreal(hue.width()), 0.9999);
        m_color = QColor::fromHsvF(m_hue, m_color.hsvSaturationF(), m_color.valueF());
    } else if (start) {
        for (int i = 0; i < m_recent.size(); ++i)
            if (swatchRect(i).contains(pos)) {
                setColor(m_recent[i]);
                emit colorChanged(m_color);
            }
        return;
    } else {
        return;
    }
    update();
    emit colorChanged(m_color);
}

void ColorPicker::mousePressEvent(QMouseEvent *event) { pickAt(event->position().toPoint(), true); }
void ColorPicker::mouseMoveEvent(QMouseEvent *event)
{
    if (event->buttons() & Qt::LeftButton)
        pickAt(event->position().toPoint(), false);
}
