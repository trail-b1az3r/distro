#pragma once
// An EPUB book for reading: unpacked (libarchive) into the cache, its
// chapters in reading order (the OPF spine) with titles from the table of
// contents, and the chapter last read remembered.
#include <QObject>
#include <QStringList>
#include <QUrl>
#include <QVariantList>
#include <QtQml/qqmlregistration.h>

class EpubBook : public QObject
{
    Q_OBJECT
    QML_ELEMENT
    Q_PROPERTY(QString path READ path WRITE setPath NOTIFY loaded)
    Q_PROPERTY(QString title READ title NOTIFY loaded)
    Q_PROPERTY(QString author READ author NOTIFY loaded)
    Q_PROPERTY(QStringList chapterTitles READ chapterTitles NOTIFY loaded)
    Q_PROPERTY(int count READ count NOTIFY loaded)
    Q_PROPERTY(int current READ current WRITE setCurrent NOTIFY currentChanged)
    Q_PROPERTY(QUrl currentUrl READ currentUrl NOTIFY currentChanged)
    Q_PROPERTY(QString error READ error NOTIFY loaded)

public:
    explicit EpubBook(QObject *parent = nullptr);
    QString path() const { return m_path; }
    void setPath(const QString &path);
    QString title() const { return m_title; }
    QString author() const { return m_author; }
    QStringList chapterTitles() const { return m_titles; }
    int count() const { return int(m_files.size()); }
    int current() const { return m_current; }
    void setCurrent(int index);
    QUrl currentUrl() const;
    QString error() const { return m_error; }

signals:
    void loaded();
    void currentChanged();

private:
    bool unpack(const QString &dest);
    bool parse(const QString &root);
    QString m_path;
    QString m_title;
    QString m_author;
    QStringList m_files;
    QStringList m_titles;
    int m_current = 0;
    QString m_error;
};
