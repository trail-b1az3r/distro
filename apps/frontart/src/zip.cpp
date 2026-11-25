#include "zip.h"

#include <QFile>
#include <QSaveFile>

#include <zlib.h>

namespace {

void put16(QByteArray &out, quint16 v) { out.append(char(v & 0xff)).append(char(v >> 8)); }
void put32(QByteArray &out, quint32 v) { put16(out, quint16(v & 0xffff)); put16(out, quint16(v >> 16)); }
quint16 get16(const QByteArray &in, qsizetype at) { return quint16(uchar(in[at])) | quint16(uchar(in[at + 1])) << 8; }
quint32 get32(const QByteArray &in, qsizetype at) { return quint32(get16(in, at)) | quint32(get16(in, at + 2)) << 16; }

QByteArray deflateRaw(const QByteArray &data)
{
    z_stream z{};
    if (deflateInit2(&z, Z_DEFAULT_COMPRESSION, Z_DEFLATED, -MAX_WBITS, 8, Z_DEFAULT_STRATEGY) != Z_OK)
        return {};
    QByteArray out(int(deflateBound(&z, uLong(data.size()))), Qt::Uninitialized);
    z.next_in = reinterpret_cast<Bytef *>(const_cast<char *>(data.constData()));
    z.avail_in = uInt(data.size());
    z.next_out = reinterpret_cast<Bytef *>(out.data());
    z.avail_out = uInt(out.size());
    const int result = deflate(&z, Z_FINISH);
    out.resize(qsizetype(z.total_out));
    deflateEnd(&z);
    return result == Z_STREAM_END ? out : QByteArray();
}

QByteArray inflateRaw(const QByteArray &data, quint32 size)
{
    z_stream z{};
    if (inflateInit2(&z, -MAX_WBITS) != Z_OK)
        return {};
    QByteArray out(qsizetype(size), Qt::Uninitialized);
    z.next_in = reinterpret_cast<Bytef *>(const_cast<char *>(data.constData()));
    z.avail_in = uInt(data.size());
    z.next_out = reinterpret_cast<Bytef *>(out.data());
    z.avail_out = uInt(out.size());
    const int result = inflate(&z, Z_FINISH);
    inflateEnd(&z);
    return result == Z_STREAM_END && z.total_out == size ? out : QByteArray();
}

} // namespace

bool Zip::write(const QString &path, const QList<Entry> &entries, QString *error)
{
    QByteArray body, directory;
    for (const Entry &e : entries) {
        const QByteArray name = e.name.toUtf8();
        const quint32 crc = quint32(crc32(0, reinterpret_cast<const Bytef *>(e.data.constData()), uInt(e.data.size())));
        QByteArray packed = e.store ? e.data : deflateRaw(e.data);
        bool stored = e.store || packed.isEmpty() || packed.size() >= e.data.size();
        if (stored)
            packed = e.data;
        const quint16 method = stored ? 0 : 8;
        const quint32 offset = quint32(body.size());

        QByteArray local;
        put32(local, 0x04034b50);
        put16(local, 20);            // version needed
        put16(local, 0x0800);        // names are UTF-8
        put16(local, method);
        put16(local, 0); put16(local, 0x21);  // time, date (1980-01-01): reproducible files
        put32(local, crc);
        put32(local, quint32(packed.size()));
        put32(local, quint32(e.data.size()));
        put16(local, quint16(name.size()));
        put16(local, 0);
        body += local + name + packed;

        put32(directory, 0x02014b50);
        put16(directory, 20); put16(directory, 20);
        put16(directory, 0x0800);
        put16(directory, method);
        put16(directory, 0); put16(directory, 0x21);
        put32(directory, crc);
        put32(directory, quint32(packed.size()));
        put32(directory, quint32(e.data.size()));
        put16(directory, quint16(name.size()));
        put16(directory, 0); put16(directory, 0); put16(directory, 0); put16(directory, 0);
        put32(directory, 0);
        put32(directory, offset);
        directory += name;
    }
    QByteArray end;
    put32(end, 0x06054b50);
    put16(end, 0); put16(end, 0);
    put16(end, quint16(entries.size())); put16(end, quint16(entries.size()));
    put32(end, quint32(directory.size()));
    put32(end, quint32(body.size()));
    put16(end, 0);

    QSaveFile file(path);   // written whole or not at all
    if (!file.open(QIODevice::WriteOnly)) {
        if (error) *error = file.errorString();
        return false;
    }
    file.write(body);
    file.write(directory);
    file.write(end);
    if (!file.commit()) {
        if (error) *error = file.errorString();
        return false;
    }
    return true;
}

QMap<QString, QByteArray> Zip::read(const QString &path, QString *error)
{
    QMap<QString, QByteArray> out;
    QFile file(path);
    if (!file.open(QIODevice::ReadOnly)) {
        if (error) *error = file.errorString();
        return out;
    }
    const QByteArray all = file.readAll();
    // The end-of-directory record is in the last 64 KiB + 22 bytes (after an optional comment).
    qsizetype eocd = -1;
    for (qsizetype at = all.size() - 22; at >= 0 && at >= all.size() - 65557; --at) {
        if (get32(all, at) == 0x06054b50) { eocd = at; break; }
    }
    if (eocd < 0) {
        if (error) *error = QStringLiteral("not a ZIP file");
        return out;
    }
    const quint16 count = get16(all, eocd + 10);
    qsizetype at = qsizetype(get32(all, eocd + 16));
    for (int i = 0; i < count; ++i) {
        if (at + 46 > all.size() || get32(all, at) != 0x02014b50)
            break;
        const quint16 method = get16(all, at + 10);
        const quint32 packedSize = get32(all, at + 20), size = get32(all, at + 24);
        const quint16 nameLength = get16(all, at + 28), extra = get16(all, at + 30), comment = get16(all, at + 32);
        const quint32 local = get32(all, at + 42);
        const QString name = QString::fromUtf8(all.mid(at + 46, nameLength));
        at += 46 + nameLength + extra + comment;
        if (qsizetype(local) + 30 > all.size() || get32(all, local) != 0x04034b50)
            continue;
        const qsizetype data = qsizetype(local) + 30 + get16(all, local + 26) + get16(all, local + 28);
        const QByteArray packed = all.mid(data, packedSize);
        if (method == 0)
            out.insert(name, packed);
        else if (method == 8)
            out.insert(name, inflateRaw(packed, size));
    }
    if (out.isEmpty() && error)
        *error = QStringLiteral("no readable entries");
    return out;
}
