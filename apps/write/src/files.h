#pragma once
// Files for QML: reading and saving documents, the notes and books folders,
// and the recently read books.
#include <QObject>
#include <QStringList>
#include <QUrl>
#include <QVariantList>
#include <QtQml/qqmlregistration.h>

class Files : public QObject
{
    Q_OBJECT
    QML_ELEMENT
    QML_SINGLETON
    Q_PROPERTY(QString notesDir READ notesDir CONSTANT)
    Q_PROPERTY(QString booksDir READ booksDir CONSTANT)
    Q_PROPERTY(QVariantList recentBooks READ recentBooks NOTIFY recentBooksChanged)

public:
    explicit Files(QObject *parent = nullptr);
    QString notesDir() const;
    QString booksDir() const;

    Q_INVOKABLE QString read(const QString &path) const;
    Q_INVOKABLE bool write(const QString &path, const QString &text) const;
    Q_INVOKABLE QString toPath(const QUrl &url) const { return url.isLocalFile() ? url.toLocalFile() : url.toString(); }
    Q_INVOKABLE QUrl toUrl(const QString &path) const { return QUrl::fromLocalFile(path); }
    Q_INVOKABLE QString baseName(const QString &path) const;
    Q_INVOKABLE QString dirOf(const QString &path) const;
    Q_INVOKABLE bool exists(const QString &path) const;

    // A new, empty note: "<title>.mdxl" in the notes folder (numbered if taken).
    Q_INVOKABLE QString newNote(const QString &title) const;
    // A new book: a folder in the books folder with a first chapter.
    Q_INVOKABLE QString newBook(const QString &title) const;
    // Chapters of a book folder, in order (file names sort them: 01-..., 02-...).
    Q_INVOKABLE QStringList chapters(const QString &bookDir) const;
    Q_INVOKABLE QString newChapter(const QString &bookDir, const QString &title) const;
    Q_INVOKABLE QStringList books() const;

    Q_INVOKABLE void addRecentBook(const QString &path, const QString &title);
    QVariantList recentBooks() const;

    Q_INVOKABLE int words(const QString &text) const;

signals:
    void recentBooksChanged();

private:
    static QString slug(const QString &title);
};
