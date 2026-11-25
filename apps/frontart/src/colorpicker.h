#pragma once

#include <QColor>
#include <QList>
#include <QWidget>

// A colour square (saturation across, value up) over a hue strip, and the colours used lately underneath.
class ColorPicker : public QWidget {
    Q_OBJECT
public:
    explicit ColorPicker(QWidget *parent = nullptr);
    QColor color() const { return m_color; }
    void setColor(const QColor &color);
    void remember(const QColor &color);   // into the recent colours
    QSize sizeHint() const override { return {240, 300}; }

signals:
    void colorChanged(const QColor &color);

protected:
    void paintEvent(QPaintEvent *) override;
    void mousePressEvent(QMouseEvent *event) override;
    void mouseMoveEvent(QMouseEvent *event) override;

private:
    QRect squareRect() const;
    QRect hueRect() const;
    QRect swatchRect(int index) const;
    void pickAt(QPoint pos, bool start);

    QColor m_color = Qt::black;
    qreal m_hue = 0;            // kept apart, so greys don't lose it
    QList<QColor> m_recent;
    enum { None, Square, Hue } m_dragging = None;
};
