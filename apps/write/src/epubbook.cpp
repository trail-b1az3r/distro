#include "epubbook.h"

#include <archive.h>
#include <archive_entry.h>

#include <QCryptographicHash>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QHash>
#include <QSettings>
#include <QStandardPaths>
#include <QXmlStreamReader>

EpubBook::EpubBook(QObject *parent) : QObject(parent) {}

static QString cacheDirFor(const QString &path)
{
    const QFileInfo fi(path);
    const QByteArray key = (fi.absoluteFilePath() + u'|' + QString::number(fi.lastModified().toSecsSinceEpoch())
                            + u'|' + QString::number(fi.size())).toUtf8();
    return QStandardPaths::writableLocation(QStandardPaths::CacheLocation) + QStringLiteral("/books/")
        + QString::fromLatin1(QCryptographicHash::hash(key, QCryptographicHash::Sha1).toHex());
}

void EpubBook::setPath(const QString &path)
{
    if (path == m_path)
        return;
    m_path = path;
    m_title.clear();
    m_author.clear();
    m_files.clear();
    m_titles.clear();
    m_error.clear();
    m_current = 0;
    if (!path.isEmpty()) {
        const QString root = cacheDirFor(path);
        const bool ready = QFileInfo::exists(root + QStringLiteral("/.unpacked")) || unpack(root);
        if (ready && parse(root)) {
            if (m_title.isEmpty())
                m_title = QFileInfo(path).completeBaseName();
            m_current = qBound(0, QSettings().value(QStringLiteral("position/") + path, 0).toInt(),
                               qMax(0, int(m_files.size()) - 1));
        } else if (m_error.isEmpty()) {
            m_error = tr("This is not an EPUB book that can be read.");
        }
    }
    emit loaded();
    emit currentChanged();
}

bool EpubBook::unpack(const QString &dest)
{
    QDir(dest).removeRecursively();
    QDir().mkpath(dest);
    archive *a = archive_read_new();
    archive_read_support_format_zip(a);
    archive_read_support_filter_all(a);
    if (archive_read_open_filename(a, QFile::encodeName(m_path).constData(), 64 * 1024) != ARCHIVE_OK) {
        m_error = QString::fromUtf8(archive_error_string(a));
        archive_read_free(a);
        return false;
    }
    const QString base = QDir(dest).canonicalPath() + u'/';
    archive_entry *entry;
    bool ok = true;
    while (archive_read_next_header(a, &entry) == ARCHIVE_OK) {
        const QString name = QString::fromUtf8(archive_entry_pathname_utf8(entry)
                                                   ? archive_entry_pathname_utf8(entry)
                                                   : archive_entry_pathname(entry));
        const QString target = QDir::cleanPath(base + name);
        // Only regular files, and only inside the book's folder.
        if (archive_entry_filetype(entry) != AE_IFREG || name.startsWith(u'/') || !target.startsWith(base)) {
            archive_read_data_skip(a);
            continue;
        }
        QDir().mkpath(QFileInfo(target).absolutePath());
        QFile out(target);
        if (!out.open(QIODevice::WriteOnly)) {
            ok = false;
            break;
        }
        const void *buf;
        size_t size;
        la_int64_t offset;
        int r;
        while ((r = archive_read_data_block(a, &buf, &size, &offset)) == ARCHIVE_OK)
            out.write(static_cast<const char *>(buf), qint64(size));
        if (r != ARCHIVE_EOF) {
            m_error = QString::fromUtf8(archive_error_string(a));
            ok = false;
            break;
        }
    }
    archive_read_free(a);
    if (ok) {  // marks a complete unpacking, reused next time
        QFile marker(dest + QStringLiteral("/.unpacked"));
        ok = marker.open(QIODevice::WriteOnly);
    }
    return ok;
}

static QString attr(const QXmlStreamReader &x, const char *name)
{
    return x.attributes().value(QLatin1String(name)).toString();
}

// href -> title from the EPUB 3 navigation document or the EPUB 2 NCX.
static QHash<QString, QString> tocTitles(const QString &file, const QString &dir)
{
    QHash<QString, QString> titles;
    QFile f(file);
    if (!f.open(QIODevice::ReadOnly))
        return titles;
    QXmlStreamReader x(&f);
    QString href, text;
    bool inLink = false, inNavText = false;
    auto add = [&](const QString &h, const QString &t) {
        const QString key = QDir::cleanPath(dir + u'/' + h.section(u'#', 0, 0));
        if (!titles.contains(key) && !t.simplified().isEmpty())
            titles.insert(key, t.simplified());
    };
    while (!x.atEnd()) {
        x.readNext();
        const auto n = x.name();
        if (x.isStartElement()) {
            if (n == u"a") { href = attr(x, "href"); text.clear(); inLink = true; }
            else if (n == u"navLabel") { text.clear(); }
            else if (n == u"text") { inNavText = true; }
            else if (n == u"content") { add(attr(x, "src"), text); }
        } else if (x.isEndElement()) {
            if (n == u"a" && inLink) { add(href, text); inLink = false; }
            else if (n == u"text") { inNavText = false; }
        } else if (x.isCharacters() && (inLink || inNavText)) {
            text += x.text();
        }
    }
    return titles;
}

bool EpubBook::parse(const QString &root)
{
    // META-INF/container.xml names the package document (OPF).
    QFile container(root + QStringLiteral("/META-INF/container.xml"));
    if (!container.open(QIODevice::ReadOnly))
        return false;
    QString opfPath;
    for (QXmlStreamReader x(&container); !x.atEnd() && opfPath.isEmpty();)
        if (x.readNext() == QXmlStreamReader::StartElement && x.name() == u"rootfile")
            opfPath = attr(x, "full-path");
    if (opfPath.isEmpty())
        return false;
    const QString opfFile = QDir::cleanPath(root + u'/' + opfPath);
    const QString opfDir = QFileInfo(opfFile).absolutePath();
    QFile opf(opfFile);
    if (!opf.open(QIODevice::ReadOnly))
        return false;

    QHash<QString, QString> manifest;  // id -> path
    QStringList spine;
    QString navFile, ncxId;
    for (QXmlStreamReader x(&opf); !x.atEnd();) {
        if (x.readNext() != QXmlStreamReader::StartElement)
            continue;
        const auto n = x.name();
        if (n == u"title" && m_title.isEmpty())
            m_title = x.readElementText().simplified();
        else if (n == u"creator" && m_author.isEmpty())
            m_author = x.readElementText().simplified();
        else if (n == u"item") {
            const QString path = QDir::cleanPath(opfDir + u'/' + QUrl::fromPercentEncoding(attr(x, "href").toUtf8()));
            manifest.insert(attr(x, "id"), path);
            if (attr(x, "properties").split(u' ').contains(QStringLiteral("nav")))
                navFile = path;
        } else if (n == u"spine")
            ncxId = attr(x, "toc");
        else if (n == u"itemref" && attr(x, "linear") != QLatin1String("no"))
            spine << attr(x, "idref");
    }
    QHash<QString, QString> titles;
    if (!navFile.isEmpty())
        titles = tocTitles(navFile, QFileInfo(navFile).absolutePath());
    if (titles.isEmpty() && manifest.contains(ncxId))
        titles = tocTitles(manifest.value(ncxId), QFileInfo(manifest.value(ncxId)).absolutePath());

    for (const QString &id : std::as_const(spine)) {
        const QString file = manifest.value(id);
        if (file.isEmpty() || !QFileInfo::exists(file))
            continue;
        m_files << file;
        m_titles << titles.value(file, tr("Section %1").arg(m_files.size()));
    }
    return !m_files.isEmpty();
}

void EpubBook::setCurrent(int index)
{
    index = qBound(0, index, qMax(0, int(m_files.size()) - 1));
    if (index == m_current)
        return;
    m_current = index;
    if (!m_path.isEmpty())
        QSettings().setValue(QStringLiteral("position/") + m_path, index);
    emit currentChanged();
}

QUrl EpubBook::currentUrl() const
{
    return m_files.isEmpty() ? QUrl() : QUrl::fromLocalFile(m_files.value(m_current));
}
