#pragma once

#include <QImage>
#include <QList>
#include <QObject>
#include <QPainter>
#include <QString>
#include <QUndoStack>

struct Layer {
    QString name;
    QImage image;               // ARGB32_Premultiplied, the document's size
    qreal opacity = 1.0;
    bool visible = true;
    bool locked = false;        // alpha locked: painting keeps what is transparent transparent
    QPainter::CompositionMode mode = QPainter::CompositionMode_SourceOver;
};

// Blend modes offered, with their OpenRaster names (svg:...).
struct BlendMode {
    const char *label;
    const char *ora;
    QPainter::CompositionMode mode;
};
const QList<BlendMode> &blendModes();

class Document : public QObject {
    Q_OBJECT
public:
    explicit Document(QObject *parent = nullptr);

    void reset(QSize size, const QColor &paper = Qt::white);
    QSize size() const { return m_size; }
    QRect rect() const { return QRect(QPoint(0, 0), m_size); }

    QList<Layer> &layers() { return m_layers; }
    const QList<Layer> &layers() const { return m_layers; }
    int current() const { return m_current; }
    void setCurrent(int index);
    Layer &currentLayer() { return m_layers[m_current]; }

    // The picture as it looks: every visible layer, bottom first, in its blend mode and opacity.
    QImage composite(const QRect &area = {}) const;

    // Layers (each change is one undo step).
    void addLayer(const QString &name = {});
    void duplicateLayer();
    void removeLayer();
    void moveLayer(int delta);
    void mergeDown();
    void setLayerProperty(int index, const QString &what, const QVariant &value);

    // A change to one layer's pixels inside `area`, for undo: `before` is that area as it was.
    void pixelsChanged(int layer, const QRect &area, const QImage &before, const QString &label);
    void flipHorizontal();

    QUndoStack *undo() { return &m_undo; }

    QString path() const { return m_path; }
    bool isModified() const { return !m_undo.isClean(); }

    // OpenRaster (.ora, layered; Krita, GIMP and MyPaint read it) or any image Qt reads (one layer).
    bool load(const QString &path, QString *error = nullptr);
    bool saveOra(const QString &path, QString *error = nullptr);
    bool exportImage(const QString &path, QString *error = nullptr) const;

    // Undo needs to put a whole list of layers back.
    void restoreLayers(const QList<Layer> &layers, int current);

signals:
    void changed(const QRect &area);   // pixels in `area` (an empty rect: everything)
    void layersChanged();
    void sizeChanged();

private:
    void snapshot(const QString &label, const std::function<void()> &change);

    QSize m_size;
    QList<Layer> m_layers;
    int m_current = 0;
    QUndoStack m_undo;
    QString m_path;
};
