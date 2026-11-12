#include "files.h"

#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QRegularExpression>
#include <QSaveFile>
#include <QSettings>
#include <QStandardPaths>
#include <QProcess>
#include <QJsonDocument>
#include <QJsonObject>
#include <QJsonArray>
#include <algorithm>
#include <QXmlStreamReader>
#include <archive.h>
#include <archive_entry.h>

static QString documents()
{
    const QString docs = QStandardPaths::writableLocation(QStandardPaths::DocumentsLocation);
    return docs.isEmpty() ? QDir::homePath() + QStringLiteral("/Documents") : docs;
}

static bool rustRequest(const QJsonObject &request, QJsonValue *result)
{
    QString program = qEnvironmentVariable("NEXORA_WRITE_BACKEND");
    if (program.isEmpty())
        program = QString::fromUtf8(HELPER_DIR) + QStringLiteral("/nexora-write-backend");
    if (!QFileInfo(program).isExecutable())
        return false;

    // Keep one Rust worker alive: QML calls are serialized on the GUI thread,
    // and JSON-lines gives us one request/reply without repeatedly spawning it.
    static QProcess process;
    static QByteArray buffer;
    if (process.state() == QProcess::NotRunning) {
        buffer.clear();
        process.setProgram(program);
        process.setProcessChannelMode(QProcess::SeparateChannels);
        process.start();
        if (!process.waitForStarted(1500))
            return false;
    }

    const QByteArray payload = QJsonDocument(request).toJson(QJsonDocument::Compact) + '\n';
    if (process.write(payload) != payload.size())
        return false;
    process.waitForBytesWritten(1500);

    int newline = buffer.indexOf('\n');
    while (newline < 0) {
        if (!process.waitForReadyRead(6000)) {
            if (process.state() == QProcess::NotRunning)
                buffer.clear();
            return false;
        }
        buffer += process.readAllStandardOutput();
        newline = buffer.indexOf('\n');
    }

    const QByteArray line = buffer.left(newline);
    buffer.remove(0, newline + 1);
    const QJsonObject response = QJsonDocument::fromJson(line).object();
    if (!response.value("ok").toBool())
        return false;
    if (result)
        *result = response.value("result");
    return true;
}

Files::Files(QObject *parent) : QObject(parent)
{
    QDir().mkpath(notesDir());
    QDir().mkpath(booksDir());
}

QString Files::notesDir() const { return documents() + QStringLiteral("/Notes"); }
QString Files::booksDir() const { return documents() + QStringLiteral("/Books"); }

QString Files::read(const QString &path) const
{
    QJsonValue result;
    if (rustRequest({{"op", "read"}, {"path", path}}, &result))
        return result.toString();
    QFile f(path);
    if (!f.open(QIODevice::ReadOnly))
        return {};
    return QString::fromUtf8(f.readAll());
}

bool Files::write(const QString &path, const QString &text) const
{
    QJsonValue result;
    if (rustRequest({{"op", "write"}, {"path", path}, {"content", text}}, &result))
        return result.toBool();
    QDir().mkpath(QFileInfo(path).absolutePath());
    QSaveFile f(path);  // written whole or not at all
    if (!f.open(QIODevice::WriteOnly))
        return false;
    f.write(text.toUtf8());
    return f.commit();
}

QString Files::baseName(const QString &path) const { return QFileInfo(path).completeBaseName(); }
QString Files::dirOf(const QString &path) const { return QFileInfo(path).absolutePath(); }
bool Files::exists(const QString &path) const { return QFileInfo::exists(path); }

QString Files::slug(const QString &title)
{
    QString s = title.trimmed();
    s.replace(QRegularExpression(QStringLiteral(R"([/\\:*?"<>|\x00-\x1f]+)")), QStringLiteral(" "));
    s = s.simplified();
    return s.isEmpty() ? QStringLiteral("Untitled") : s.left(80);
}

static QString unique(const QString &dir, const QString &name, const QString &suffix)
{
    QString path = dir + u'/' + name + suffix;
    for (int n = 2; QFileInfo::exists(path); ++n)
        path = dir + u'/' + name + QStringLiteral(" %1").arg(n) + suffix;
    return path;
}

QString Files::newNote(const QString &title) const
{
    QJsonValue result;
    if (rustRequest({{"op", "create_note"}, {"root", notesDir()}, {"title", title}}, &result))
        return result.toString();
    const QString name = slug(title);
    const QString path = unique(notesDir(), name, QStringLiteral(".mdxl"));
    write(path, QStringLiteral("# %1\n\n").arg(name));
    return path;
}

QString Files::newBook(const QString &title) const
{
    QJsonValue result;
    if (rustRequest({{"op", "create_book"}, {"root", booksDir()}, {"title", title}}, &result))
        return result.toString();
    const QString name = slug(title);
    const QString dir = unique(booksDir(), name, QString());
    QDir().mkpath(dir);
    write(dir + QStringLiteral("/00-About.mdxl"),
          QStringLiteral("# %1\n\n-# A book written in MDXL. Each chapter is a file in this folder.\n").arg(name));
    newChapter(dir, QStringLiteral("Chapter one"));
    return dir;
}

QStringList Files::chapters(const QString &bookDir) const
{
    QStringList out;
    QJsonValue listed;
    if (rustRequest({{"op", "list"}, {"path", bookDir}}, &listed)) {
        for (const QJsonValue &entry : listed.toArray()) {
            const QString name = entry.toObject().value("name").toString();
            if ((name.endsWith(".mdxl") || name.endsWith(".md"))
                    && name.compare("00-About.mdxl", Qt::CaseInsensitive) != 0)
                out << entry.toObject().value("path").toString();
        }
        return out;
    }
    const auto entries = QDir(bookDir).entryInfoList({"*.mdxl", "*.md"}, QDir::Files, QDir::Name);
    for (const QFileInfo &fi : entries)
        if (fi.fileName().compare(QStringLiteral("00-About.mdxl"), Qt::CaseInsensitive) != 0)
            out << fi.absoluteFilePath();
    return out;
}

QString Files::newChapter(const QString &bookDir, const QString &title) const
{
    QJsonValue result;
    if (rustRequest({{"op", "create_chapter"}, {"book", bookDir}, {"title", title}}, &result))
        return result.toString();
    const int next = chapters(bookDir).size();
    const QString name = QStringLiteral("%1-%2").arg(next, 2, 10, QLatin1Char('0')).arg(slug(title));
    const QString path = unique(bookDir, name, QStringLiteral(".mdxl"));
    write(path, QStringLiteral("## %1\n\n").arg(slug(title)));
    return path;
}

QStringList Files::books() const
{
    QStringList out;
    QJsonValue listed;
    if (rustRequest({{"op", "list"}, {"path", booksDir()}}, &listed)) {
        for (const QJsonValue &entry : listed.toArray())
            if (entry.toObject().value("directory").toBool())
                out << entry.toObject().value("path").toString();
        return out;
    }
    const auto entries = QDir(booksDir()).entryInfoList(QDir::Dirs | QDir::NoDotAndDotDot, QDir::Name);
    for (const QFileInfo &fi : entries)
        out << fi.absoluteFilePath();
    return out;
}

void Files::addRecentBook(const QString &path, const QString &title)
{
    QSettings s;
    QVariantList list = s.value(QStringLiteral("recentBooks")).toList();
    for (int i = list.size() - 1; i >= 0; --i)
        if (list[i].toMap().value("path").toString() == path)
            list.removeAt(i);
    list.prepend(QVariantMap{{"path", path}, {"title", title}});
    while (list.size() > 12)
        list.removeLast();
    s.setValue(QStringLiteral("recentBooks"), list);
    emit recentBooksChanged();
}

QVariantList Files::recentBooks() const
{
    QVariantList out;
    for (const QVariant &v : QSettings().value(QStringLiteral("recentBooks")).toList())
        if (QFileInfo::exists(v.toMap().value("path").toString()))
            out << v;
    return out;
}


static QString escapeXml(QString s)
{
    s.replace("&", "&amp;");
    s.replace("<", "&lt;");
    s.replace(">", "&gt;");
    return s;
}

QString Files::importDocx(const QString &path) const
{
    archive *a = archive_read_new();
    archive_read_support_format_zip(a);
    archive_read_support_filter_all(a);
    if (archive_read_open_filename(a, QFile::encodeName(path).constData(), 65536) != ARCHIVE_OK) {
        archive_read_free(a);
        return {};
    }
    QByteArray xml;
    archive_entry *entry = nullptr;
    while (archive_read_next_header(a, &entry) == ARCHIVE_OK) {
        if (QString::fromUtf8(archive_entry_pathname(entry)) == "word/document.xml") {
            char buf[32768];
            la_ssize_t n;
            while ((n = archive_read_data(a, buf, sizeof(buf))) > 0)
                xml.append(buf, qsizetype(n));
            break;
        }
        archive_read_data_skip(a);
    }
    archive_read_free(a);
    if (xml.isEmpty())
        return {};

    QXmlStreamReader x(xml);
    QString out, paragraph, cell;
    QStringList cells;
    int tableRows = 0;
    bool inParagraph = false, inTable = false, inRow = false, inCell = false;
    while (!x.atEnd()) {
        x.readNext();
        if (x.isStartElement()) {
            const QString n = x.name().toString();
            if (n == "tbl") { inTable = true; tableRows = 0; out += '\n'; }
            else if (n == "tr" && inTable) { inRow = true; cells.clear(); }
            else if (n == "tc" && inRow) { inCell = true; cell.clear(); }
            else if (n == "p") { inParagraph = true; paragraph.clear(); }
            else if (n == "t" && inParagraph) paragraph += x.readElementText();
            else if (n == "tab" && inParagraph) paragraph += '\t';
            else if (n == "br" && inParagraph) {
                if (x.attributes().value("type") == "page")
                    paragraph += "\n\n<!-- WRITE_PAGE_BREAK -->\n\n";
                else paragraph += '\n';
            }
        } else if (x.isEndElement()) {
            const QString n = x.name().toString();
            if (n == "p") {
                if (inCell) cell += paragraph.trimmed() + ' ';
                else if (!paragraph.trimmed().isEmpty()) out += paragraph.trimmed() + "\n\n";
                inParagraph = false;
            } else if (n == "tc" && inCell) {
                cells << cell.simplified();
                inCell = false;
            } else if (n == "tr" && inRow) {
                out += "| " + cells.join(" | ") + " |\n";
                if (tableRows == 0)
                    out += "| " + QStringList(cells.size(), "---").join(" | ") + " |\n";
                ++tableRows;
                inRow = false;
            } else if (n == "tbl") {
                out += '\n';
                inTable = false;
            }
        }
    }
    if (x.hasError())
        return {};
    return out.trimmed() + '\n';
}

bool Files::exportDocx(const QString &path, const QString &text) const
{
    QString body;
    const QStringList lines = text.split('\n');
    for (qsizetype i = 0; i < lines.size(); ++i) {
        const QString line = lines[i];
        if (line.trimmed() == "<!-- WRITE_PAGE_BREAK -->") {
            body += "<w:p><w:r><w:br w:type=\"page\"/></w:r></w:p>";
            continue;
        }
        if (line.trimmed().startsWith('|') && line.trimmed().endsWith('|')) {
            QStringList tableRows;
            while (i < lines.size() && lines[i].trimmed().startsWith('|') && lines[i].trimmed().endsWith('|')) {
                QStringList cells = lines[i].trimmed().mid(1, lines[i].trimmed().size() - 2).split('|');
                for (QString &cell : cells) cell = cell.trimmed();
                const bool separator = std::all_of(cells.cbegin(), cells.cend(), [](const QString &v) {
                    QString normalized = v;
                    normalized.remove('-');
                    normalized.remove(':');
                    return !v.isEmpty() && normalized.trimmed().isEmpty();
                });
                if (!separator) {
                    QString row = "<w:tr>";
                    for (const QString &cell : cells)
                        row += "<w:tc><w:tcPr><w:tcW w:w=\"2400\" w:type=\"dxa\"/></w:tcPr><w:p><w:r><w:t xml:space=\"preserve\">"
                            + escapeXml(cell) + "</w:t></w:r></w:p></w:tc>";
                    row += "</w:tr>";
                    tableRows << row;
                }
                ++i;
            }
            --i;
            if (!tableRows.isEmpty())
                body += "<w:tbl><w:tblPr><w:tblBorders>"
                    "<w:top w:val=\"single\" w:sz=\"4\"/><w:left w:val=\"single\" w:sz=\"4\"/>"
                    "<w:bottom w:val=\"single\" w:sz=\"4\"/><w:right w:val=\"single\" w:sz=\"4\"/>"
                    "<w:insideH w:val=\"single\" w:sz=\"4\"/><w:insideV w:val=\"single\" w:sz=\"4\"/>"
                    "</w:tblBorders></w:tblPr>" + tableRows.join(QString()) + "</w:tbl>";
            continue;
        }
        QString value = line;
        int level = 0;
        while (level < value.size() && level < 6 && value[level] == '#') ++level;
        if (level && level < value.size() && value[level] == ' ')
            value = value.mid(level + 1);
        else level = 0;
        const QString style = level ? QString("<w:pPr><w:pStyle w:val=\"Heading%1\"/></w:pPr>").arg(level) : QString();
        body += QString("<w:p>%1<w:r><w:t xml:space=\"preserve\">%2</w:t></w:r></w:p>")
                    .arg(style, escapeXml(value));
    }
    const QByteArray doc = QString(
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
        "<w:document xmlns:w=\"http://schemas.openxmlformats.org/wordprocessingml/2006/main\">"
        "<w:body>%1<w:sectPr><w:pgSz w:w=\"11906\" w:h=\"16838\"/>"
        "<w:pgMar w:top=\"1440\" w:right=\"1440\" w:bottom=\"1440\" w:left=\"1440\"/>"
        "</w:sectPr></w:body></w:document>").arg(body).toUtf8();
    const QList<QPair<QString, QByteArray>> files = {
        {"[Content_Types].xml", "<?xml version=\"1.0\"?><Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\"><Default Extension=\"rels\" ContentType=\"application/vnd.openxmlformats-package.relationships+xml\"/><Default Extension=\"xml\" ContentType=\"application/xml\"/><Override PartName=\"/word/document.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml\"/></Types>"},
        {"_rels/.rels", "<?xml version=\"1.0\"?><Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\"><Relationship Id=\"rId1\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument\" Target=\"word/document.xml\"/></Relationships>"},
        {"word/document.xml", doc}
    };
    archive *a = archive_write_new();
    archive_write_set_format_zip(a);
    if (archive_write_open_filename(a, QFile::encodeName(path).constData()) != ARCHIVE_OK) {
        archive_write_free(a);
        return false;
    }
    bool ok = true;
    for (const auto &file : files) {
        archive_entry *e = archive_entry_new();
        archive_entry_set_pathname(e, file.first.toUtf8().constData());
        archive_entry_set_filetype(e, AE_IFREG);
        archive_entry_set_perm(e, 0644);
        archive_entry_set_size(e, file.second.size());
        if (archive_write_header(a, e) != ARCHIVE_OK ||
            archive_write_data(a, file.second.constData(), size_t(file.second.size())) != file.second.size())
            ok = false;
        archive_entry_free(e);
        if (!ok) break;
    }
    if (archive_write_close(a) != ARCHIVE_OK) ok = false;
    archive_write_free(a);
    return ok;
}

QString Files::importImage(const QString &source, const QString &documentDir) const
{
    QJsonValue result;
    if (rustRequest({{"op", "import_image"}, {"source", source}, {"book", documentDir}}, &result))
        return result.toString();

    const QFileInfo input(source);
    const QString extension = input.suffix().toLower();
    if (!QStringList{"png", "jpg", "jpeg", "webp", "gif", "svg", "avif", "bmp"}.contains(extension))
        return {};
    const QString images = documentDir + QStringLiteral("/images");
    QDir().mkpath(images);
    const QString stem = slug(input.completeBaseName());
    QString name = stem + u'.' + extension;
    QString target = images + u'/' + name;
    for (int index = 2; QFileInfo::exists(target); ++index) {
        name = stem + QStringLiteral("-%1.").arg(index) + extension;
        target = images + u'/' + name;
    }
    if (!QFile::copy(source, target))
        return {};
    return QStringLiteral("images/") + name;
}

bool Files::betterbirdInstalled() const
{
    return !QStandardPaths::findExecutable(QStringLiteral("betterbird")).isEmpty();
}

int Files::words(const QString &text) const
{
    QJsonValue result;
    if (rustRequest({{"op", "word_count"}, {"text", text}}, &result))
        return result.toInt();
    static const QRegularExpression word(QStringLiteral(R"(\w[\w'’-]*)"),
                                         QRegularExpression::UseUnicodePropertiesOption);
    int n = 0;
    for (auto it = word.globalMatch(text); it.hasNext(); it.next())
        ++n;
    return n;
}
