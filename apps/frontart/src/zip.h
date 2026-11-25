#pragma once

// A small ZIP reader and writer, enough for OpenRaster (.ora): entries are stored or deflated (zlib), with no
// encryption, spanning or ZIP64. The first entry of an .ora, "mimetype", must be stored; writeZip keeps the order.

#include <QByteArray>
#include <QList>
#include <QMap>
#include <QString>

namespace Zip {

struct Entry {
    QString name;
    QByteArray data;
    bool store = false;   // true: no compression (the .ora mimetype, and data that is compressed already)
};

bool write(const QString &path, const QList<Entry> &entries, QString *error = nullptr);
// Every entry by name; empty with an error when the file is not a ZIP this can read.
QMap<QString, QByteArray> read(const QString &path, QString *error = nullptr);

} // namespace Zip
