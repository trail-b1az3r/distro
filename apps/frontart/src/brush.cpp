#include "brush.h"

#include <QtMath>

QList<Brush> Brush::presets()
{
    QList<Brush> list;
    Brush b;

    b = {}; b.name = QStringLiteral("Brush"); b.kind = Round; b.size = 18; b.flow = 0.7; b.hardness = 0.7;
    b.pressureSize = true; b.pressureOpacity = true;
    list << b;

    b = {}; b.name = QStringLiteral("Pencil"); b.kind = Pencil; b.size = 4; b.flow = 0.9; b.hardness = 1.0;
    b.spacing = 0.08; b.minSize = 0.5; b.pressureOpacity = true;
    list << b;

    b = {}; b.name = QStringLiteral("Ink pen"); b.kind = Ink; b.size = 6; b.flow = 1.0; b.hardness = 0.95;
    b.spacing = 0.06; b.minSize = 0.05;
    list << b;

    b = {}; b.name = QStringLiteral("Marker"); b.kind = Marker; b.size = 24; b.opacity = 0.55; b.flow = 1.0;
    b.hardness = 0.9; b.pressureSize = false;
    list << b;

    b = {}; b.name = QStringLiteral("Airbrush"); b.kind = Airbrush; b.size = 80; b.flow = 0.06; b.hardness = 0.0;
    b.spacing = 0.05; b.pressureSize = false; b.pressureOpacity = true; b.buildsUp = true;
    list << b;

    b = {}; b.name = QStringLiteral("Soft round"); b.kind = Round; b.size = 60; b.flow = 0.25; b.hardness = 0.1;
    b.spacing = 0.08; b.pressureOpacity = true; b.minSize = 0.4;
    list << b;

    b = {}; b.name = QStringLiteral("Eraser"); b.kind = Eraser; b.size = 30; b.flow = 1.0; b.hardness = 0.8;
    b.pressureSize = true; b.minSize = 0.3;
    list << b;

    return list;
}

qreal pressureCurve(qreal pressure, qreal softness)
{
    // softness 0.5 is linear; below it needs more pressure, above it less (a power curve, gamma 4 .. 1/4).
    const qreal p = qBound<qreal>(0.0, pressure, 1.0);
    const qreal gamma = qPow(4.0, (0.5 - qBound<qreal>(0.0, softness, 1.0)) * 2.0);
    return qPow(p, gamma);
}
