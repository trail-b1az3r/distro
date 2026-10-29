// The writer: documents, notes and books in MDXL, and an EPUB reader.
#include <QFileInfo>
#include <QGuiApplication>
#include <QUrl>
#include <QIcon>
#include <QQmlApplicationEngine>
#include <QQmlContext>
#include <QQuickStyle>
#include <QtWebEngineQuick/qtwebenginequickglobal.h>

int main(int argc, char *argv[])
{
    QtWebEngineQuick::initialize();
    QGuiApplication app(argc, argv);
    QGuiApplication::setApplicationName(QStringLiteral(APP_ID));
    QGuiApplication::setApplicationDisplayName(QStringLiteral(APP_NAME));
    QGuiApplication::setApplicationVersion(QStringLiteral(APP_VERSION));
    QGuiApplication::setDesktopFileName(QStringLiteral(APP_ID));
    QGuiApplication::setWindowIcon(QIcon::fromTheme(QStringLiteral(APP_ID)));
    QQuickStyle::setStyle(QStringLiteral("Material"));

    QQmlApplicationEngine engine;
    QStringList files = app.arguments().mid(1);
    const bool selfTest = files.removeAll(QStringLiteral("--self-test")) > 0;
    for (QString &f : files) {
        const QUrl url(f);
        f = url.isLocalFile() ? url.toLocalFile() : QFileInfo(f).absoluteFilePath();
    }
    engine.rootContext()->setContextProperty(QStringLiteral("startupFiles"), files);
    engine.rootContext()->setContextProperty(QStringLiteral("appName"), QStringLiteral(APP_NAME));
    // --self-test: open the files given, report what loaded, and quit.
    engine.rootContext()->setContextProperty(QStringLiteral("selfTest"), selfTest);
    QObject::connect(&engine, &QQmlApplicationEngine::objectCreationFailed, &app,
                     [] { QCoreApplication::exit(1); }, Qt::QueuedConnection);
    engine.loadFromModule("Write", "Main");
    if (engine.rootObjects().isEmpty())
        return 1;
    return app.exec();
}
