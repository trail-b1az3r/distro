// The writer: documents, notes and books in MDXL, and an EPUB reader.
#include <QFileInfo>
#include <QGuiApplication>
#include <QUrl>
#include <QIcon>
#include <QQmlApplicationEngine>
#include <QQmlContext>
#include <QQuickStyle>
#include <QQuickWindow>
#include <QtWebEngineQuick/qtwebenginequickglobal.h>
#include <cstdio>

#include "files.h"

int main(int argc, char *argv[])
{
    // Request an alpha-capable backing surface for translucent QML panels.
    QQuickWindow::setDefaultAlphaBuffer(true);
    QtWebEngineQuick::initialize();
    // EPUB-MXL from the command line, without a window:
    //   --export-epub-mxl BOOK_FOLDER OUT.epub-mxl [AUTHOR]   a book folder to an EPUB-MXL book
    //   --import-epub-mxl BOOK.epub-mxl                       an EPUB-MXL book back into a book folder (printed)
    if (argc >= 3 && (qstrcmp(argv[1], "--export-epub-mxl") == 0 || qstrcmp(argv[1], "--import-epub-mxl") == 0)) {
        QCoreApplication core(argc, argv);
        QCoreApplication::setApplicationName(QStringLiteral(APP_ID));
        const QStringList args = core.arguments();
        Files files;
        if (args[1] == QLatin1String("--export-epub-mxl")) {
            if (args.size() < 4) {
                std::fputs("usage: --export-epub-mxl BOOK_FOLDER OUT.epub-mxl [AUTHOR]\n", stderr);
                return 2;
            }
            const QString error = files.exportEpubMxl(QFileInfo(args[2]).absoluteFilePath(),
                                                      QFileInfo(args[3]).absoluteFilePath(), args.value(4));
            if (!error.isEmpty()) {
                std::fprintf(stderr, "%s\n", qPrintable(error));
                return 1;
            }
            return 0;
        }
        const QString dir = files.importEpubMxl(QFileInfo(args[2]).absoluteFilePath());
        if (dir.isEmpty()) {
            std::fputs("not an EPUB-MXL book (no MDXL sources inside)\n", stderr);
            return 1;
        }
        std::printf("%s\n", qPrintable(dir));
        return 0;
    }

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
