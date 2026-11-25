#include "document.h"

#include "zip.h"

#include <QBuffer>
#include <QFileInfo>
#include <QImageReader>
#include <QImageWriter>
#include <QUndoCommand>
#include <QXmlStreamReader>
#include <QXmlStreamWriter>

const QList<BlendMode> &blendModes()
{
    static const QList<BlendMode> modes = {
        {"Normal", "svg:src-over", QPainter::CompositionMode_SourceOver},
        {"Multiply", "svg:multiply", QPainter::CompositionMode_Multiply},
        {"Screen", "svg:screen", QPainter::CompositionMode_Screen},
        {"Overlay", "svg:overlay", QPainter::CompositionMode_Overlay},
        {"Darken", "svg:darken", QPainter::CompositionMode_Darken},
        {"Lighten", "svg:lighten", QPainter::CompositionMode_Lighten},
        {"Colour dodge", "svg:color-dodge", QPainter::CompositionMode_ColorDodge},
        {"Colour burn", "svg:color-burn", QPainter::CompositionMode_ColorBurn},
        {"Hard light", "svg:hard-light", QPainter::CompositionMode_HardLight},
        {"Soft light", "svg:soft-light", QPainter::CompositionMode_SoftLight},
        {"Difference", "svg:difference", QPainter::CompositionMode_Difference},
        {"Add", "svg:plus", QPainter::CompositionMode_Plus},
    };
    return modes;
}

namespace {

// Undo for a change to pixels: the area before and after.
class PixelsCommand : public QUndoCommand {
public:
    PixelsCommand(Document *doc, int layer, QRect area, QImage before, QImage after, const QString &label)
        : QUndoCommand(label), m_doc(doc), m_layer(layer), m_area(area), m_before(std::move(before)), m_after(std::move(after)) {}
    void undo() override { put(m_before); }
    void redo() override
    {
        if (m_first) { m_first = false; return; }   // the canvas has painted it already
        put(m_after);
    }

private:
    void put(const QImage &pixels)
    {
        if (m_layer >= m_doc->layers().size())
            return;
        QPainter p(&m_doc->layers()[m_layer].image);
        p.setCompositionMode(QPainter::CompositionMode_Source);
        p.drawImage(m_area.topLeft(), pixels);
        p.end();
        emit m_doc->changed(m_area);
    }
    Document *m_doc;
    int m_layer;
    QRect m_area;
    QImage m_before, m_after;
    bool m_first = true;
};

// Undo for a change to the list of layers: the whole list before and after (QImage shares pixels until written).
class LayersCommand : public QUndoCommand {
public:
    LayersCommand(Document *doc, QList<Layer> before, int beforeCurrent, const QString &label)
        : QUndoCommand(label), m_doc(doc), m_before(std::move(before)), m_beforeCurrent(beforeCurrent),
          m_after(doc->layers()), m_afterCurrent(doc->current()) {}
    void undo() override { m_doc->restoreLayers(m_before, m_beforeCurrent); }
    void redo() override
    {
        if (m_first) { m_first = false; return; }
        m_doc->restoreLayers(m_after, m_afterCurrent);
    }

private:
    Document *m_doc;
    QList<Layer> m_before;
    int m_beforeCurrent;
    QList<Layer> m_after;
    int m_afterCurrent;
    bool m_first = true;
};

QImage blank(QSize size)
{
    QImage image(size, QImage::Format_ARGB32_Premultiplied);
    image.fill(Qt::transparent);
    return image;
}

} // namespace

Document::Document(QObject *parent) : QObject(parent)
{
    m_undo.setUndoLimit(80);
}

void Document::reset(QSize size, const QColor &paper)
{
    m_size = size;
    m_layers.clear();
    Layer background{QStringLiteral("Background"), blank(size)};
    if (paper.alpha() > 0)
        background.image.fill(paper);
    m_layers.append(background);
    m_layers.append(Layer{QStringLiteral("Layer 1"), blank(size)});
    m_current = 1;
    m_path.clear();
    m_undo.clear();
    emit sizeChanged();
    emit layersChanged();
    emit changed({});
}

void Document::setCurrent(int index)
{
    if (index < 0 || index >= m_layers.size() || index == m_current)
        return;
    m_current = index;
    emit layersChanged();
}

QImage Document::composite(const QRect &area) const
{
    const QRect r = area.isEmpty() ? rect() : area.intersected(rect());
    QImage out(r.size(), QImage::Format_ARGB32_Premultiplied);
    out.fill(Qt::transparent);
    QPainter p(&out);
    for (const Layer &layer : m_layers) {
        if (!layer.visible || layer.opacity <= 0)
            continue;
        p.setCompositionMode(layer.mode);
        p.setOpacity(layer.opacity);
        p.drawImage(QPoint(0, 0), layer.image, r);
    }
    return out;
}

void Document::snapshot(const QString &label, const std::function<void()> &change)
{
    const QList<Layer> before = m_layers;
    const int beforeCurrent = m_current;
    change();
    m_undo.push(new LayersCommand(this, before, beforeCurrent, label));
    emit layersChanged();
    emit changed({});
}

void Document::restoreLayers(const QList<Layer> &layers, int current)
{
    m_layers = layers;
    m_current = qBound(0, current, int(m_layers.size()) - 1);
    emit layersChanged();
    emit changed({});
}

void Document::addLayer(const QString &name)
{
    snapshot(tr("New layer"), [&] {
        int n = int(m_layers.size());
        m_layers.insert(m_current + 1, Layer{name.isEmpty() ? tr("Layer %1").arg(n) : name, blank(m_size)});
        ++m_current;
    });
}

void Document::duplicateLayer()
{
    snapshot(tr("Duplicate layer"), [&] {
        Layer copy = m_layers[m_current];
        copy.name = tr("%1 copy").arg(copy.name);
        copy.image = copy.image.copy();
        m_layers.insert(m_current + 1, copy);
        ++m_current;
    });
}

void Document::removeLayer()
{
    if (m_layers.size() <= 1)
        return;
    snapshot(tr("Delete layer"), [&] {
        m_layers.removeAt(m_current);
        m_current = qMin(m_current, int(m_layers.size()) - 1);
    });
}

void Document::moveLayer(int delta)
{
    const int to = m_current + delta;
    if (to < 0 || to >= m_layers.size())
        return;
    snapshot(delta > 0 ? tr("Raise layer") : tr("Lower layer"), [&] {
        m_layers.swapItemsAt(m_current, to);
        m_current = to;
    });
}

void Document::mergeDown()
{
    if (m_current == 0)
        return;
    snapshot(tr("Merge down"), [&] {
        Layer &below = m_layers[m_current - 1];
        const Layer &above = m_layers[m_current];
        below.image = below.image.copy();
        if (above.visible) {
            QPainter p(&below.image);
            p.setCompositionMode(above.mode);
            p.setOpacity(above.opacity);
            p.drawImage(0, 0, above.image);
        }
        m_layers.removeAt(m_current);
        --m_current;
    });
}

void Document::setLayerProperty(int index, const QString &what, const QVariant &value)
{
    if (index < 0 || index >= m_layers.size())
        return;
    snapshot(tr("Layer %1").arg(what), [&] {
        Layer &l = m_layers[index];
        if (what == QLatin1String("name")) l.name = value.toString();
        else if (what == QLatin1String("opacity")) l.opacity = qBound(0.0, value.toReal(), 1.0);
        else if (what == QLatin1String("visible")) l.visible = value.toBool();
        else if (what == QLatin1String("locked")) l.locked = value.toBool();
        else if (what == QLatin1String("mode")) l.mode = QPainter::CompositionMode(value.toInt());
    });
}

void Document::pixelsChanged(int layer, const QRect &area, const QImage &before, const QString &label)
{
    const QRect r = area.intersected(rect());
    if (r.isEmpty())
        return;
    m_undo.push(new PixelsCommand(this, layer, r, before, m_layers[layer].image.copy(r), label));
}

void Document::flipHorizontal()
{
    snapshot(tr("Flip canvas"), [&] {
        for (Layer &l : m_layers)
#if QT_VERSION >= QT_VERSION_CHECK(6, 9, 0)
            l.image = l.image.flipped(Qt::Horizontal);
#else
            l.image = l.image.mirrored(true, false);
#endif
    });
}

// ── Files ───────────────────────────────────────────────────────────────────────────────────────────────────────────

bool Document::load(const QString &path, QString *error)
{
    if (path.endsWith(QLatin1String(".ora"), Qt::CaseInsensitive)) {
        const QMap<QString, QByteArray> files = Zip::read(path, error);
        if (!files.contains(QStringLiteral("stack.xml"))) {
            if (error && error->isEmpty()) *error = tr("not an OpenRaster file (no stack.xml)");
            return false;
        }
        QXmlStreamReader xml(files.value(QStringLiteral("stack.xml")));
        QSize size;
        QList<Layer> layers;   // stack.xml lists the top layer first
        while (!xml.atEnd()) {
            xml.readNext();
            if (!xml.isStartElement())
                continue;
            const auto a = xml.attributes();
            if (xml.name() == QLatin1String("image")) {
                size = QSize(a.value(QLatin1String("w")).toInt(), a.value(QLatin1String("h")).toInt());
            } else if (xml.name() == QLatin1String("layer")) {
                Layer layer;
                layer.name = a.value(QLatin1String("name")).toString();
                layer.opacity = a.hasAttribute(QLatin1String("opacity")) ? a.value(QLatin1String("opacity")).toDouble() : 1.0;
                layer.visible = a.value(QLatin1String("visibility")) != QLatin1String("hidden");
                layer.locked = a.value(QLatin1String("alpha-preserve")) == QLatin1String("true");
                const QString op = a.value(QLatin1String("composite-op")).toString();
                for (const BlendMode &m : blendModes())
                    if (op == QLatin1String(m.ora)) layer.mode = m.mode;
                QImage png = QImage::fromData(files.value(a.value(QLatin1String("src")).toString()));
                layer.image = QImage(size, QImage::Format_ARGB32_Premultiplied);
                layer.image.fill(Qt::transparent);
                QPainter p(&layer.image);
                p.drawImage(a.value(QLatin1String("x")).toInt(), a.value(QLatin1String("y")).toInt(), png);
                p.end();
                layers.prepend(layer);
            }
        }
        if (size.isEmpty() || layers.isEmpty()) {
            if (error) *error = tr("the OpenRaster file has no layers");
            return false;
        }
        m_size = size;
        m_layers = layers;
    } else {
        QImageReader reader(path);
        reader.setAutoTransform(true);
        QImage image = reader.read();
        if (image.isNull()) {
            if (error) *error = reader.errorString();
            return false;
        }
        m_size = image.size();
        m_layers = {Layer{QFileInfo(path).completeBaseName(), image.convertToFormat(QImage::Format_ARGB32_Premultiplied)}};
    }
    m_current = int(m_layers.size()) - 1;
    m_path = path;
    m_undo.clear();
    emit sizeChanged();
    emit layersChanged();
    emit changed({});
    return true;
}

bool Document::saveOra(const QString &path, QString *error)
{
    QList<Zip::Entry> entries;
    entries.append({QStringLiteral("mimetype"), QByteArrayLiteral("image/openraster"), true});
    QByteArray stack;
    QXmlStreamWriter xml(&stack);
    xml.setAutoFormatting(true);
    xml.writeStartDocument();
    xml.writeStartElement(QStringLiteral("image"));
    xml.writeAttribute(QStringLiteral("version"), QStringLiteral("0.0.5"));
    xml.writeAttribute(QStringLiteral("w"), QString::number(m_size.width()));
    xml.writeAttribute(QStringLiteral("h"), QString::number(m_size.height()));
    xml.writeStartElement(QStringLiteral("stack"));
    for (int i = int(m_layers.size()) - 1; i >= 0; --i) {
        const Layer &l = m_layers[i];
        const QString src = QStringLiteral("data/layer%1.png").arg(i);
        QByteArray png;
        QBuffer buffer(&png);
        buffer.open(QIODevice::WriteOnly);
        l.image.convertToFormat(QImage::Format_ARGB32).save(&buffer, "PNG");
        entries.append({src, png, true});
        xml.writeStartElement(QStringLiteral("layer"));
        xml.writeAttribute(QStringLiteral("name"), l.name);
        xml.writeAttribute(QStringLiteral("src"), src);
        xml.writeAttribute(QStringLiteral("x"), QStringLiteral("0"));
        xml.writeAttribute(QStringLiteral("y"), QStringLiteral("0"));
        xml.writeAttribute(QStringLiteral("opacity"), QString::number(l.opacity, 'f', 3));
        xml.writeAttribute(QStringLiteral("visibility"), l.visible ? QStringLiteral("visible") : QStringLiteral("hidden"));
        if (l.locked)
            xml.writeAttribute(QStringLiteral("alpha-preserve"), QStringLiteral("true"));
        for (const BlendMode &m : blendModes())
            if (m.mode == l.mode)
                xml.writeAttribute(QStringLiteral("composite-op"), QLatin1String(m.ora));
        xml.writeEndElement();
    }
    xml.writeEndElement();
    xml.writeEndElement();
    xml.writeEndDocument();
    entries.insert(1, {QStringLiteral("stack.xml"), stack, false});

    // The merged picture and a thumbnail, which the format asks for (file managers show them).
    const QImage merged = composite().convertToFormat(QImage::Format_ARGB32);
    QByteArray png, thumb;
    QBuffer b1(&png), b2(&thumb);
    b1.open(QIODevice::WriteOnly);
    b2.open(QIODevice::WriteOnly);
    merged.save(&b1, "PNG");
    merged.scaled(256, 256, Qt::KeepAspectRatio, Qt::SmoothTransformation).save(&b2, "PNG");
    entries.append({QStringLiteral("mergedimage.png"), png, true});
    entries.append({QStringLiteral("Thumbnails/thumbnail.png"), thumb, true});

    if (!Zip::write(path, entries, error))
        return false;
    m_path = path;
    m_undo.setClean();
    return true;
}

bool Document::exportImage(const QString &path, QString *error) const
{
    QImage image = composite();
    const QString suffix = QFileInfo(path).suffix().toLower();
    if (suffix == QLatin1String("jpg") || suffix == QLatin1String("jpeg")) {
        // No transparency in JPEG: over white.
        QImage flat(image.size(), QImage::Format_RGB32);
        flat.fill(Qt::white);
        QPainter(&flat).drawImage(0, 0, image);
        image = flat;
    }
    QImageWriter writer(path);
    writer.setQuality(suffix == QLatin1String("png") ? -1 : 92);
    if (!writer.write(image.convertToFormat(image.hasAlphaChannel() ? QImage::Format_ARGB32 : QImage::Format_RGB32))) {
        if (error) *error = writer.errorString();
        return false;
    }
    return true;
}
