#pragma once
// Syntax colours in the editor from KDE's syntax definitions: MDXL's own
// ("Markdown Extended Logic", installed by the mdxl package), Markdown
// otherwise.
#include <QObject>
#include <QPointer>
#include <QQuickTextDocument>
#include <QtQml/qqmlregistration.h>

namespace KSyntaxHighlighting { class Repository; class SyntaxHighlighter; }

class Highlighter : public QObject
{
    Q_OBJECT
    QML_ELEMENT
    Q_PROPERTY(QQuickTextDocument *document READ document WRITE setDocument NOTIFY changed)
    Q_PROPERTY(bool dark READ dark WRITE setDark NOTIFY changed)
    Q_PROPERTY(QString fileName READ fileName WRITE setFileName NOTIFY changed)
    Q_PROPERTY(QString definition READ definition NOTIFY changed)

public:
    explicit Highlighter(QObject *parent = nullptr);
    ~Highlighter() override;
    QQuickTextDocument *document() const { return m_document; }
    void setDocument(QQuickTextDocument *d);
    bool dark() const { return m_dark; }
    void setDark(bool d);
    QString fileName() const { return m_fileName; }
    void setFileName(const QString &f);
    QString definition() const { return m_definition; }

signals:
    void changed();

private:
    void apply();
    static KSyntaxHighlighting::Repository &repository();
    QPointer<QQuickTextDocument> m_document;
    KSyntaxHighlighting::SyntaxHighlighter *m_highlighter = nullptr;
    bool m_dark = true;
    QString m_fileName;
    QString m_definition;
};
