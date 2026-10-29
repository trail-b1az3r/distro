#include "files.h"

#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QRegularExpression>
#include <QSaveFile>
#include <QSettings>
#include <QStandardPaths>

static QString documents()
{
    const QString docs = QStandardPaths::writableLocation(QStandardPaths::DocumentsLocation);
    return docs.isEmpty() ? QDir::homePath() + QStringLiteral("/Documents") : docs;
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
    QFile f(path);
    if (!f.open(QIODevice::ReadOnly))
        return {};
    return QString::fromUtf8(f.readAll());
}

bool Files::write(const QString &path, const QString &text) const
{
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
    const QString name = slug(title);
    const QString path = unique(notesDir(), name, QStringLiteral(".mdxl"));
    write(path, QStringLiteral("# %1\n\n").arg(name));
    return path;
}

QString Files::newBook(const QString &title) const
{
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
    const auto entries = QDir(bookDir).entryInfoList({"*.mdxl", "*.md"}, QDir::Files, QDir::Name);
    for (const QFileInfo &fi : entries)
        out << fi.absoluteFilePath();
    return out;
}

QString Files::newChapter(const QString &bookDir, const QString &title) const
{
    const int next = chapters(bookDir).size();
    const QString name = QStringLiteral("%1-%2").arg(next, 2, 10, QLatin1Char('0')).arg(slug(title));
    const QString path = unique(bookDir, name, QStringLiteral(".mdxl"));
    write(path, QStringLiteral("## %1\n\n").arg(slug(title)));
    return path;
}

QStringList Files::books() const
{
    QStringList out;
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

int Files::words(const QString &text) const
{
    static const QRegularExpression word(QStringLiteral(R"(\w[\w'’-]*)"),
                                         QRegularExpression::UseUnicodePropertiesOption);
    int n = 0;
    for (auto it = word.globalMatch(text); it.hasNext(); it.next())
        ++n;
    return n;
}
