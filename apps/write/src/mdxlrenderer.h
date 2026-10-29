#pragma once
// Live MDXL preview: text goes to the mdxl-render helper (MDXL's own
// renderer, kept running), HTML comes back with the theme's stylesheet.
#include <QObject>
#include <QProcess>
#include <QTimer>
#include <QtQml/qqmlregistration.h>

class MdxlRenderer : public QObject
{
    Q_OBJECT
    QML_ELEMENT
    Q_PROPERTY(QString html READ html NOTIFY htmlChanged)
    Q_PROPERTY(QString css READ css WRITE setCss NOTIFY htmlChanged)
    Q_PROPERTY(QString error READ error NOTIFY errorChanged)

public:
    explicit MdxlRenderer(QObject *parent = nullptr);
    ~MdxlRenderer() override;
    QString html() const;
    QString css() const { return m_css; }
    void setCss(const QString &css);
    QString error() const { return m_error; }

    // Render after a short pause in typing (or at once).
    Q_INVOKABLE void render(const QString &text, bool now = false);

signals:
    void htmlChanged();
    void errorChanged();

private:
    void start();
    void send();
    void readAnswers();
    void setError(const QString &e);

    QProcess m_proc;
    QTimer m_debounce;
    QString m_pending;
    QString m_raw;
    QString m_css;
    QString m_error;
    QByteArray m_buffer;
    qint64 m_id = 0;
};
