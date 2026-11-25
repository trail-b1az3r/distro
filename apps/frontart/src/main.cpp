#include "mainwindow.h"

#include <QApplication>
#include <QCommandLineParser>
#include <QDir>
#include <QFileInfo>
#include <QIcon>
#include <QTemporaryDir>
#include <QUndoStack>

#include <cstdio>

// Paints, fills, undoes and saves without a screen, and checks each step (the package's check() runs it).
static int selfTest(MainWindow &w)
{
    auto fail = [](const char *what) {
        std::fprintf(stderr, "self-test failed: %s\n", what);
        return 1;
    };
    Document *doc = w.document();
    Canvas *canvas = w.canvas();
    doc->reset(QSize(400, 300));
    canvas->setColor(QColor(200, 30, 30));

    // A pressure-sensitive stroke across the middle of layer 1, light on the left and full on the right.
    Brush brush = Brush::presets().first();
    brush.size = 20;
    canvas->setBrush(brush);
    // Edge to edge, so it divides the page in two (the fill below stops at it).
    canvas->strokeBegin(QPointF(-10, 150), 0.35);
    for (int x = 0; x <= 410; x += 10)
        canvas->strokeTo(QPointF(x, 150), 0.35 + 0.65 * x / 410.0);
    canvas->strokeEnd();
    const QColor painted = doc->layers()[1].image.pixelColor(340, 150);
    if (painted.alpha() < 200 || painted.red() < 150)
        return fail("the stroke did not paint");
    if (doc->layers()[1].image.pixelColor(200, 100).alpha() != 0)
        return fail("the stroke painted outside itself");
    // Light pressure makes a thinner line than full pressure.
    auto thickness = [&](int x) {
        int n = 0;
        for (int y = 120; y < 180; ++y)
            n += doc->layers()[1].image.pixelColor(x, y).alpha() > 60;
        return n;
    };
    if (thickness(80) >= thickness(330))
        return fail("pressure did not change the size");

    // Undo and redo.
    doc->undo()->undo();
    if (doc->layers()[1].image.pixelColor(340, 150).alpha() != 0)
        return fail("undo left the stroke");
    doc->undo()->redo();
    if (doc->layers()[1].image.pixelColor(340, 150).alpha() < 200)
        return fail("redo did not bring it back");

    // A fill on a new layer stops at the stroke (it sees the picture as a whole).
    doc->addLayer();
    canvas->setColor(QColor(30, 60, 220));
    canvas->fill(QPoint(200, 40));
    if (doc->currentLayer().image.pixelColor(200, 40).blue() < 200)
        return fail("the fill did not fill");
    if (doc->currentLayer().image.pixelColor(200, 260).alpha() != 0)
        return fail("the fill crossed the line");

    // Layers: blend mode and opacity, then OpenRaster there and back.
    doc->setLayerProperty(doc->current(), QStringLiteral("opacity"), 0.5);
    doc->setLayerProperty(doc->current(), QStringLiteral("mode"), int(QPainter::CompositionMode_Multiply));
    QTemporaryDir dir;
    const QString ora = dir.filePath(QStringLiteral("test.ora"));
    QString error;
    if (!doc->saveOra(ora, &error))
        return fail(qPrintable(error));
    const QImage before = doc->composite();
    Document again;
    if (!again.load(ora, &error))
        return fail(qPrintable(error));
    if (again.layers().size() != doc->layers().size() || again.layers().last().mode != QPainter::CompositionMode_Multiply
        || qAbs(again.layers().last().opacity - 0.5) > 0.01)
        return fail("the layers did not come back from OpenRaster");
    const QImage after = again.composite();
    for (const QPoint p : {QPoint(200, 40), QPoint(340, 150), QPoint(10, 290)})
        if (before.pixel(p) != after.pixel(p))
            return fail("the picture changed going through OpenRaster");
    if (!doc->exportImage(dir.filePath(QStringLiteral("flat.png")), &error) || QImage(dir.filePath(QStringLiteral("flat.png"))).isNull())
        return fail("export failed");
    std::fprintf(stdout, "self-test passed\n");
    return 0;
}

int main(int argc, char *argv[])
{
    QApplication::setAttribute(Qt::AA_CompressTabletEvents, false);   // every pen sample counts
    QApplication app(argc, argv);
    QApplication::setApplicationName(QStringLiteral(APP_ID));
    QApplication::setApplicationDisplayName(QStringLiteral(APP_NAME));
    QApplication::setApplicationVersion(QStringLiteral(APP_VERSION));
    QApplication::setDesktopFileName(QStringLiteral(APP_ID));
    QApplication::setWindowIcon(QIcon::fromTheme(QStringLiteral(APP_ID)));

    QCommandLineParser parser;
    parser.setApplicationDescription(QStringLiteral("Paint and draw, with layers and pen pressure."));
    parser.addHelpOption();
    parser.addVersionOption();
    QCommandLineOption test(QStringLiteral("self-test"), QStringLiteral("Check painting, undo and files, then quit."));
    parser.addOption(test);
    parser.addPositionalArgument(QStringLiteral("picture"), QStringLiteral("A picture to open (.ora, .png, .jpg, ...)."));
    parser.process(app);

    applyDesktopPalette();
    MainWindow window;
    if (parser.isSet(test))
        return selfTest(window);
    const QStringList files = parser.positionalArguments();
    if (!files.isEmpty())
        window.openFile(QFileInfo(files.first()).absoluteFilePath());
    window.show();
    return app.exec();
}
