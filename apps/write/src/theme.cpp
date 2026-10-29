#include "theme.h"

#include <QColor>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QFontDatabase>
#include <QJsonDocument>
#include <QJsonObject>
#include <QStandardPaths>

static QVariantMap fallback()
{
    return {
        {"background", "#16130f"}, {"onBackground", "#ece0d4"},
        {"surface", "#16130f"}, {"surfaceContainerLow", "#1e1a15"},
        {"surfaceContainer", "#231e19"}, {"surfaceContainerHigh", "#2d2823"},
        {"surfaceContainerHighest", "#38322d"}, {"onSurface", "#ece0d4"},
        {"onSurfaceVariant", "#d5c4b4"}, {"primary", "#f0bc8b"}, {"onPrimary", "#4a2800"},
        {"primaryContainer", "#693c0d"}, {"onPrimaryContainer", "#ffdcc2"},
        {"secondaryContainer", "#5a4232"}, {"onSecondaryContainer", "#fcdcc6"},
        {"tertiary", "#c9c88f"}, {"outline", "#9e8e80"}, {"outlineVariant", "#51443a"},
        {"error", "#ffb4ab"},
    };
}

static QString camel(const QString &snake)
{
    QString out;
    bool up = false;
    for (QChar ch : snake) {
        if (ch == u'_') { up = true; continue; }
        out += up ? ch.toUpper() : ch;
        up = false;
    }
    return out;
}

Theme::Theme(QObject *parent) : QObject(parent)
{
    QString state = qEnvironmentVariable("XDG_STATE_HOME");
    if (state.isEmpty())
        state = QDir::homePath() + QStringLiteral("/.local/state");
    m_path = state + QStringLiteral("/quickshell/user/generated/colors.json");
    // Watch the directory too: the theme switcher replaces the file.
    QDir().mkpath(QFileInfo(m_path).absolutePath());
    m_watcher.addPath(QFileInfo(m_path).absolutePath());
    connect(&m_watcher, &QFileSystemWatcher::fileChanged, this, &Theme::reload);
    connect(&m_watcher, &QFileSystemWatcher::directoryChanged, this, &Theme::reload);
    reload();
}

void Theme::reload()
{
    QVariantMap colors = fallback();
    bool fromDesktop = false;
    QFile f(m_path);
    if (f.open(QIODevice::ReadOnly)) {
        const QJsonObject json = QJsonDocument::fromJson(f.readAll()).object();
        for (auto it = json.begin(); it != json.end(); ++it) {
            const QColor c(it.value().toString());
            if (c.isValid()) {
                colors.insert(camel(it.key()), c.name());
                fromDesktop = true;
            }
        }
        if (!m_watcher.files().contains(m_path))
            m_watcher.addPath(m_path);
    }
    m_colors = colors;
    m_fromDesktop = fromDesktop;
    m_dark = QColor(colors.value("background").toString()).lightnessF() < 0.5;
    emit changed();
}

static QString firstInstalled(const QStringList &families, const QString &fallbackName)
{
    const QStringList installed = QFontDatabase::families();
    for (const QString &f : families)
        if (installed.contains(f))
            return f;
    return fallbackName;
}

QString Theme::font() const
{
    return firstInstalled({"Google Sans Flex", "Rubik", "Noto Sans"}, QStringLiteral("sans-serif"));
}

QString Theme::mono() const
{
    return firstInstalled({"JetBrains Mono", "JetBrainsMono Nerd Font", "Noto Sans Mono"},
                          QStringLiteral("monospace"));
}

QString Theme::css(qreal fontScale) const
{
    auto c = [this](const char *key) { return m_colors.value(QLatin1String(key)).toString(); };
    // MDXL's preview stylesheet is built on these variables; the reader uses
    // the page rules.
    return QStringLiteral(
               ":root{color-scheme:%1;--bg:%2;--panel:%3;--text:%4;--muted:%5;--line:%6;"
               "--lime:%7;--accent:%7}"
               "html,body{background:%2!important;color:%4!important;font-family:'%8',sans-serif;"
               "font-size:%9%;line-height:1.65}"
               "a{color:%7}pre,code{font-family:'%10',monospace}"
               "img,svg{max-width:100%;height:auto}"
               "::selection{background:%11;color:%12}")
        .arg(m_dark ? "dark" : "light", c("surface"), c("surfaceContainer"), c("onSurface"),
             c("onSurfaceVariant"), c("outlineVariant"), c("primary"), font())
        .arg(qRound(fontScale * 100))
        .arg(mono(), c("primaryContainer"), c("onPrimaryContainer"));
}
