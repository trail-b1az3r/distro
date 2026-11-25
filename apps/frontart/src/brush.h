#pragma once

#include <QList>
#include <QString>

// A brush: what one dab looks like and how the pen's pressure and speed change it.
struct Brush {
    enum Kind { Round, Pencil, Airbrush, Marker, Ink, Eraser };

    QString name;
    Kind kind = Round;
    qreal size = 12;           // diameter in canvas pixels, at full pressure
    qreal opacity = 1.0;       // the most a stroke covers (a stroke never darkens itself past this)
    qreal flow = 0.8;          // how much each dab adds
    qreal hardness = 0.8;      // 1: a hard edge; 0: soft all the way from the middle
    qreal spacing = 0.12;      // dab distance, as a fraction of the size
    bool pressureSize = true;
    bool pressureOpacity = false;
    qreal minSize = 0.15;      // the size at no pressure, as a fraction of `size`
    bool buildsUp = false;     // the airbrush keeps adding while it moves over the same place

    static QList<Brush> presets();
};

// The pen's pressure as the brush feels it: a curve from soft (more with less) to firm (needs pressing).
qreal pressureCurve(qreal pressure, qreal softness);
