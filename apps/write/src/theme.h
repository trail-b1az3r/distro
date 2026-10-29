#pragma once
// Colours from Halcyon's current theme (the Material You palette the
// desktop writes to ~/.local/state/quickshell/user/generated/colors.json),
// followed live; a dark copper palette when there is none.
#include <QFileSystemWatcher>
#include <QObject>
#include <QVariantMap>
#include <QtQml/qqmlregistration.h>

class Theme : public QObject
{
    Q_OBJECT
    QML_ELEMENT
    QML_SINGLETON
    Q_PROPERTY(QVariantMap c READ colors NOTIFY changed)
    Q_PROPERTY(bool dark READ dark NOTIFY changed)
    Q_PROPERTY(bool fromDesktop READ fromDesktop NOTIFY changed)
    Q_PROPERTY(QString font READ font CONSTANT)
    Q_PROPERTY(QString mono READ mono CONSTANT)

public:
    explicit Theme(QObject *parent = nullptr);
    QVariantMap colors() const { return m_colors; }
    bool dark() const { return m_dark; }
    bool fromDesktop() const { return m_fromDesktop; }
    QString font() const;
    QString mono() const;
    // CSS custom properties and page colours for the preview and the reader.
    Q_INVOKABLE QString css(qreal fontScale = 1.0) const;

signals:
    void changed();

private:
    void reload();
    QString m_path;
    QVariantMap m_colors;
    bool m_dark = true;
    bool m_fromDesktop = false;
    QFileSystemWatcher m_watcher;
};
