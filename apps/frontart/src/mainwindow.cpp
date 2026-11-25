#include "mainwindow.h"

#include <QAction>
#include <QActionGroup>
#include <QApplication>
#include <QCheckBox>
#include <QCloseEvent>
#include <QComboBox>
#include <QDialog>
#include <QDialogButtonBox>
#include <QDir>
#include <QDockWidget>
#include <QFile>
#include <QFileDialog>
#include <QFileInfo>
#include <QFormLayout>
#include <QHBoxLayout>
#include <QImageReader>
#include <QInputDialog>
#include <QJsonDocument>
#include <QJsonObject>
#include <QLabel>
#include <QListWidget>
#include <QMenuBar>
#include <QMessageBox>
#include <QPushButton>
#include <QSlider>
#include <QSpinBox>
#include <QStandardPaths>
#include <QStatusBar>
#include <QStyleFactory>
#include <QToolBar>
#include <QToolButton>
#include <QUndoStack>
#include <QVBoxLayout>

namespace {

QSlider *slider(int min, int max, int value)
{
    auto *s = new QSlider(Qt::Horizontal);
    s->setRange(min, max);
    s->setValue(value);
    return s;
}

QString filters()
{
    return QObject::tr("Pictures (*.ora *.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff);;OpenRaster (*.ora);;All files (*)");
}

} // namespace

void applyDesktopPalette()
{
    QString state = qEnvironmentVariable("XDG_STATE_HOME");
    if (state.isEmpty())
        state = QDir::homePath() + QStringLiteral("/.local/state");
    QJsonObject c;
    QFile f(state + QStringLiteral("/quickshell/user/generated/colors.json"));
    if (f.open(QIODevice::ReadOnly))
        c = QJsonDocument::fromJson(f.readAll()).object();
    auto colour = [&](const char *key, const char *fallback) {
        const QColor v(c.value(QLatin1String(key)).toString());
        return v.isValid() ? v : QColor(QLatin1String(fallback));
    };
    QApplication::setStyle(QStyleFactory::create(QStringLiteral("Fusion")));
    QPalette p;
    const QColor surface = colour("surface_container", "#1f1d22"), low = colour("surface_container_low", "#19171c");
    const QColor text = colour("on_surface", "#e7e0e8"), primary = colour("primary", "#cfbcff");
    p.setColor(QPalette::Window, surface);
    p.setColor(QPalette::WindowText, text);
    p.setColor(QPalette::Base, low);
    p.setColor(QPalette::AlternateBase, surface.lighter(110));
    p.setColor(QPalette::Text, text);
    p.setColor(QPalette::Button, colour("surface_container_high", "#2a2830"));
    p.setColor(QPalette::ButtonText, text);
    p.setColor(QPalette::Highlight, primary);
    p.setColor(QPalette::HighlightedText, colour("on_primary", "#381e72"));
    p.setColor(QPalette::ToolTipBase, colour("surface_container_highest", "#36343b"));
    p.setColor(QPalette::ToolTipText, text);
    p.setColor(QPalette::PlaceholderText, colour("on_surface_variant", "#cac4d0"));
    p.setColor(QPalette::Mid, colour("outline_variant", "#49454f"));
    p.setColor(QPalette::Disabled, QPalette::Text, colour("outline", "#938f99"));
    p.setColor(QPalette::Disabled, QPalette::ButtonText, colour("outline", "#938f99"));
    QApplication::setPalette(p);
    qApp->setStyleSheet(QStringLiteral(
        "QDockWidget::title{padding:6px 8px;font-weight:600}"
        "QToolBar{border:0;spacing:2px;padding:4px}"
        "QToolButton{border-radius:8px;padding:5px 8px}"
        "QToolButton:checked{background:%1;color:%2}"
        "QListWidget{border-radius:10px;padding:4px}"
        "QListWidget::item{border-radius:7px;padding:5px}"
        "QListWidget::item:selected{background:%1;color:%2}"
        "QListWidget::item:hover:!selected{background:%3}").arg(primary.name(), p.color(QPalette::HighlightedText).name(),
                                                               p.color(QPalette::AlternateBase).name()));
}

MainWindow::MainWindow(QWidget *parent) : QMainWindow(parent)
{
    m_presets = Brush::presets();
    m_doc.reset(QSize(2480, 1748));    // A5 landscape at 300 dpi
    m_canvas = new Canvas(&m_doc, this);
    setCentralWidget(m_canvas);

    auto *tools = new QDockWidget(tr("Brush"), this);
    tools->setObjectName(QStringLiteral("brush"));
    tools->setWidget(buildToolPanel());
    tools->setFeatures(QDockWidget::DockWidgetMovable | QDockWidget::DockWidgetFloatable);
    addDockWidget(Qt::LeftDockWidgetArea, tools);

    auto *layers = new QDockWidget(tr("Layers"), this);
    layers->setObjectName(QStringLiteral("layers"));
    layers->setWidget(buildLayerPanel());
    layers->setFeatures(QDockWidget::DockWidgetMovable | QDockWidget::DockWidgetFloatable);
    addDockWidget(Qt::RightDockWidgetArea, layers);

    buildMenus();
    m_status = new QLabel;
    statusBar()->addPermanentWidget(m_status);
    connect(m_canvas, &Canvas::zoomChanged, this, [this](qreal z) { m_status->setText(tr("%1%").arg(qRound(z * 100))); });
    connect(m_canvas, &Canvas::cursorAt, this, [this](QPoint p) {
        statusBar()->showMessage(tr("%1, %2   %3 × %4").arg(p.x()).arg(p.y()).arg(m_doc.size().width()).arg(m_doc.size().height()));
    });
    connect(m_canvas, &Canvas::colorPicked, this, [this](const QColor &c) { m_picker->setColor(c); });
    connect(&m_doc, &Document::layersChanged, this, &MainWindow::refreshLayers);
    connect(m_doc.undo(), &QUndoStack::cleanChanged, this, &MainWindow::updateTitle);

    choosePreset(0);
    refreshLayers();
    updateTitle();
    resize(1400, 900);
}

void MainWindow::showEvent(QShowEvent *event)
{
    QMainWindow::showEvent(event);
    if (m_firstShow) {
        m_firstShow = false;
        m_canvas->fit();
    }
}

// ── Panels ──────────────────────────────────────────────────────────────────────────────────────────────────────────

QWidget *MainWindow::buildToolPanel()
{
    auto *panel = new QWidget;
    auto *v = new QVBoxLayout(panel);
    m_picker = new ColorPicker;
    v->addWidget(m_picker);
    connect(m_picker, &ColorPicker::colorChanged, this, [this](const QColor &c) { m_canvas->setColor(c); });

    m_brushList = new QListWidget;
    for (const Brush &b : m_presets)
        m_brushList->addItem(b.name);
    m_brushList->setMaximumHeight(m_brushList->sizeHintForRow(0) * int(m_presets.size()) + 24);
    v->addWidget(m_brushList);
    connect(m_brushList, &QListWidget::currentRowChanged, this, &MainWindow::choosePreset);

    auto *form = new QFormLayout;
    m_size = slider(1, 500, 18);
    m_opacity = slider(1, 100, 100);
    m_flow = slider(1, 100, 70);
    m_hardness = slider(0, 100, 70);
    m_softness = slider(0, 100, 50);
    form->addRow(tr("Size"), m_size);
    form->addRow(tr("Opacity"), m_opacity);
    form->addRow(tr("Flow"), m_flow);
    form->addRow(tr("Hardness"), m_hardness);
    form->addRow(tr("Pen pressure"), m_softness);
    m_softness->setToolTip(tr("Left: press harder for full strength. Right: a light touch is enough."));
    v->addLayout(form);
    for (QSlider *s : {m_size, m_opacity, m_flow, m_hardness})
        connect(s, &QSlider::valueChanged, this, &MainWindow::brushEdited);
    connect(m_softness, &QSlider::valueChanged, this, [this](int value) { m_canvas->setPressureSoftness(value / 100.0); });

    auto *mirror = new QCheckBox(tr("Mirror painting"));
    connect(mirror, &QCheckBox::toggled, m_canvas, &Canvas::setMirror);
    v->addWidget(mirror);
    v->addStretch();
    return panel;
}

QWidget *MainWindow::buildLayerPanel()
{
    auto *panel = new QWidget;
    auto *v = new QVBoxLayout(panel);
    m_blend = new QComboBox;
    for (const BlendMode &m : blendModes())
        m_blend->addItem(tr(m.label), int(m.mode));
    m_layerOpacity = slider(0, 100, 100);
    auto *form = new QFormLayout;
    form->addRow(tr("Blend"), m_blend);
    form->addRow(tr("Opacity"), m_layerOpacity);
    v->addLayout(form);

    m_layerList = new QListWidget;
    v->addWidget(m_layerList, 1);
    // The list shows the top layer first.
    connect(m_layerList, &QListWidget::currentRowChanged, this, [this](int row) {
        if (!m_refreshing && row >= 0)
            m_doc.setCurrent(int(m_doc.layers().size()) - 1 - row);
    });
    connect(m_layerList, &QListWidget::itemChanged, this, [this](QListWidgetItem *item) {
        if (m_refreshing)
            return;
        const int index = int(m_doc.layers().size()) - 1 - m_layerList->row(item);
        const bool visible = item->checkState() == Qt::Checked;
        if (m_doc.layers()[index].visible != visible)
            m_doc.setLayerProperty(index, QStringLiteral("visible"), visible);
        if (m_doc.layers()[index].name != item->text())
            m_doc.setLayerProperty(index, QStringLiteral("name"), item->text());
    });
    connect(m_blend, &QComboBox::activated, this, [this](int i) {
        m_doc.setLayerProperty(m_doc.current(), QStringLiteral("mode"), m_blend->itemData(i));
    });
    // One undo step when the slider is let go, but the picture follows it while it moves.
    connect(m_layerOpacity, &QSlider::valueChanged, this, [this](int value) {
        if (m_refreshing)
            return;
        m_doc.currentLayer().opacity = value / 100.0;
        emit m_doc.changed({});
    });
    connect(m_layerOpacity, &QSlider::sliderReleased, this, [this] {
        const qreal value = m_layerOpacity->value() / 100.0;
        m_doc.currentLayer().opacity = m_layerOpacity->property("start").toReal();
        m_doc.setLayerProperty(m_doc.current(), QStringLiteral("opacity"), value);
    });
    connect(m_layerOpacity, &QSlider::sliderPressed, this, [this] {
        m_layerOpacity->setProperty("start", m_doc.currentLayer().opacity);
    });

    auto *buttons = new QHBoxLayout;
    auto button = [&](const QString &text, const QString &tip, auto slot) {
        auto *b = new QToolButton;
        b->setText(text);
        b->setToolTip(tip);
        connect(b, &QToolButton::clicked, this, slot);
        buttons->addWidget(b);
    };
    button(QStringLiteral("+"), tr("New layer"), [this] { m_doc.addLayer(); });
    button(QStringLiteral("⧉"), tr("Duplicate layer"), [this] { m_doc.duplicateLayer(); });
    button(QStringLiteral("↑"), tr("Raise layer"), [this] { m_doc.moveLayer(1); });
    button(QStringLiteral("↓"), tr("Lower layer"), [this] { m_doc.moveLayer(-1); });
    button(QStringLiteral("⤓"), tr("Merge down"), [this] { m_doc.mergeDown(); });
    button(QStringLiteral("🔒"), tr("Lock transparency"), [this] {
        m_doc.setLayerProperty(m_doc.current(), QStringLiteral("locked"), !m_doc.currentLayer().locked);
    });
    button(QStringLiteral("−"), tr("Delete layer"), [this] { m_doc.removeLayer(); });
    v->addLayout(buttons);
    return panel;
}

void MainWindow::refreshLayers()
{
    m_refreshing = true;
    m_layerList->clear();
    const auto &layers = m_doc.layers();
    for (int i = int(layers.size()) - 1; i >= 0; --i) {
        auto *item = new QListWidgetItem(layers[i].name);
        item->setFlags(item->flags() | Qt::ItemIsUserCheckable | Qt::ItemIsEditable);
        item->setCheckState(layers[i].visible ? Qt::Checked : Qt::Unchecked);
        if (layers[i].locked)
            item->setToolTip(tr("Transparency locked"));
        QImage thumb = layers[i].image.scaled(40, 40, Qt::KeepAspectRatio, Qt::SmoothTransformation);
        item->setIcon(QIcon(QPixmap::fromImage(thumb)));
        m_layerList->addItem(item);
    }
    m_layerList->setCurrentRow(int(layers.size()) - 1 - m_doc.current());
    if (!layers.isEmpty()) {
        const Layer &l = m_doc.layers()[m_doc.current()];
        m_layerOpacity->setValue(qRound(l.opacity * 100));
        m_blend->setCurrentIndex(m_blend->findData(int(l.mode)));
    }
    m_refreshing = false;
}

void MainWindow::choosePreset(int index)
{
    if (index < 0 || index >= m_presets.size())
        return;
    const Brush &b = m_presets[index];
    m_refreshing = true;
    m_size->setValue(qRound(b.size));
    m_opacity->setValue(qRound(b.opacity * 100));
    m_flow->setValue(qRound(b.flow * 100));
    m_hardness->setValue(qRound(b.hardness * 100));
    m_refreshing = false;
    if (m_brushList->currentRow() != index)
        m_brushList->setCurrentRow(index);
    m_canvas->setBrush(b);
    m_canvas->setTool(Canvas::Paint);
    if (m_tools && !m_tools->actions().isEmpty())
        m_tools->actions().first()->setChecked(true);
}

void MainWindow::brushEdited()
{
    if (m_refreshing)
        return;
    const int index = qMax(0, m_brushList->currentRow());
    Brush &b = m_presets[index];   // each preset keeps your settings for this session
    b.size = m_size->value();
    b.opacity = m_opacity->value() / 100.0;
    b.flow = m_flow->value() / 100.0;
    b.hardness = m_hardness->value() / 100.0;
    m_canvas->setBrush(b);
}

// ── Menus ───────────────────────────────────────────────────────────────────────────────────────────────────────────

void MainWindow::buildMenus()
{
    QMenu *file = menuBar()->addMenu(tr("&File"));
    file->addAction(tr("&New…"), QKeySequence::New, this, &MainWindow::newDocument);
    file->addAction(tr("&Open…"), QKeySequence::Open, this, &MainWindow::open);
    file->addAction(tr("&Save"), QKeySequence::Save, this, [this] { save(); });
    file->addAction(tr("Save &as…"), QKeySequence::SaveAs, this, [this] { saveAs(); });
    file->addAction(tr("&Export picture…"), QKeySequence(Qt::CTRL | Qt::Key_E), this, &MainWindow::exportImage);
    file->addSeparator();
    file->addAction(tr("&Quit"), QKeySequence::Quit, this, &QWidget::close);

    QMenu *edit = menuBar()->addMenu(tr("&Edit"));
    QAction *undo = m_doc.undo()->createUndoAction(this, tr("&Undo"));
    undo->setShortcut(QKeySequence::Undo);
    QAction *redo = m_doc.undo()->createRedoAction(this, tr("&Redo"));
    redo->setShortcuts({QKeySequence::Redo, QKeySequence(Qt::CTRL | Qt::Key_Y)});
    edit->addAction(undo);
    edit->addAction(redo);
    edit->addSeparator();
    edit->addAction(tr("&Clear layer"), QKeySequence::Delete, this, [this] {
        Layer &layer = m_doc.currentLayer();
        const QImage before = layer.image.copy();
        layer.image.fill(Qt::transparent);
        m_doc.pixelsChanged(m_doc.current(), m_doc.rect(), before, tr("Clear layer"));
        emit m_doc.changed({});
    });
    edit->addAction(tr("&Flip canvas"), this, [this] { m_doc.flipHorizontal(); });

    QMenu *view = menuBar()->addMenu(tr("&View"));
    view->addAction(tr("Zoom &in"), QKeySequence::ZoomIn, this, [this] { m_canvas->zoomBy(1.25); });
    view->addAction(tr("Zoom &out"), QKeySequence::ZoomOut, this, [this] { m_canvas->zoomBy(0.8); });
    view->addAction(tr("&Fit"), QKeySequence(Qt::CTRL | Qt::Key_0), this, [this] { m_canvas->fit(); });
    view->addAction(tr("&Actual size"), QKeySequence(Qt::CTRL | Qt::Key_1), this, [this] { m_canvas->setZoom(1.0); });
    view->addAction(tr("Rotate &left"), QKeySequence(Qt::Key_4), this, [this] { m_canvas->rotateBy(-15); });
    view->addAction(tr("Rotate &right"), QKeySequence(Qt::Key_6), this, [this] { m_canvas->rotateBy(15); });
    view->addAction(tr("&Mirror view"), QKeySequence(Qt::Key_M), this, [this] { m_canvas->flipView(); });
    view->addAction(tr("&Reset view"), QKeySequence(Qt::Key_5), this, [this] { m_canvas->resetView(); });

    // Tools, in a toolbar too.
    auto *bar = addToolBar(tr("Tools"));
    bar->setObjectName(QStringLiteral("tools"));
    bar->setMovable(false);
    m_tools = new QActionGroup(this);
    auto tool = [&](const QString &name, QKeySequence key, Canvas::Tool t, std::function<void()> extra = {}) {
        QAction *a = bar->addAction(name);
        a->setShortcut(key);
        a->setCheckable(true);
        a->setToolTip(QStringLiteral("%1 (%2)").arg(name, key.toString()));
        m_tools->addAction(a);
        connect(a, &QAction::triggered, this, [this, t, extra] {
            m_canvas->setTool(t);
            if (extra) extra();
        });
        return a;
    };
    tool(tr("Paint"), QKeySequence(Qt::Key_B), Canvas::Paint, [this] {
        if (m_canvas->brush().kind == Brush::Eraser) choosePreset(0);
    })->setChecked(true);
    tool(tr("Erase"), QKeySequence(Qt::Key_E), Canvas::Paint, [this] {
        for (int i = 0; i < m_presets.size(); ++i)
            if (m_presets[i].kind == Brush::Eraser) choosePreset(i);
        m_tools->actions()[1]->setChecked(true);
    });
    tool(tr("Fill"), QKeySequence(Qt::Key_G), Canvas::Fill);
    tool(tr("Pick colour"), QKeySequence(Qt::Key_I), Canvas::Picker);
    tool(tr("Move view"), QKeySequence(Qt::Key_H), Canvas::Pan);
    bar->addSeparator();
    bar->addAction(undo);
    bar->addAction(redo);

    // Brush size with [ and ], like most painting programs.
    auto *smaller = new QAction(this);
    smaller->setShortcut(QKeySequence(Qt::Key_BracketLeft));
    connect(smaller, &QAction::triggered, this, [this] { m_size->setValue(qMax(1, qRound(m_size->value() / 1.2))); });
    auto *bigger = new QAction(this);
    bigger->setShortcut(QKeySequence(Qt::Key_BracketRight));
    connect(bigger, &QAction::triggered, this, [this] { m_size->setValue(qMin(500, qRound(m_size->value() * 1.2) + 1)); });
    addActions({smaller, bigger});
    // The colour you paint with goes into the recent colours when a stroke ends.
    connect(m_doc.undo(), &QUndoStack::indexChanged, this, [this] { m_picker->remember(m_canvas->color()); });
}

// ── Files ───────────────────────────────────────────────────────────────────────────────────────────────────────────

void MainWindow::updateTitle()
{
    const QString name = m_doc.path().isEmpty() ? tr("Untitled") : QFileInfo(m_doc.path()).fileName();
    setWindowTitle(QStringLiteral("%1%2 — %3").arg(name, m_doc.isModified() ? QStringLiteral(" •") : QString(),
                                                  QApplication::applicationDisplayName()));
}

bool MainWindow::askToSave()
{
    if (!m_doc.isModified())
        return true;
    const auto answer = QMessageBox::question(this, tr("Save your picture?"), tr("It has changes that are not saved."),
                                              QMessageBox::Save | QMessageBox::Discard | QMessageBox::Cancel);
    if (answer == QMessageBox::Save)
        return save();
    return answer == QMessageBox::Discard;
}

void MainWindow::newDocument()
{
    if (!askToSave())
        return;
    QDialog dialog(this);
    dialog.setWindowTitle(tr("New picture"));
    auto *form = new QFormLayout(&dialog);
    auto *w = new QSpinBox, *h = new QSpinBox;
    w->setRange(16, 16384);
    h->setRange(16, 16384);
    w->setValue(m_doc.size().width());
    h->setValue(m_doc.size().height());
    auto *presets = new QComboBox;
    const QList<QPair<QString, QSize>> sizes = {
        {tr("Screen (1920 × 1080)"), {1920, 1080}}, {tr("4K (3840 × 2160)"), {3840, 2160}},
        {tr("A4 at 300 dpi"), {2480, 3508}}, {tr("A5 landscape at 300 dpi"), {2480, 1748}},
        {tr("Square (2048 × 2048)"), {2048, 2048}}, {tr("Icon (512 × 512)"), {512, 512}}};
    for (const auto &s : sizes)
        presets->addItem(s.first, s.second);
    connect(presets, &QComboBox::activated, &dialog, [=](int i) {
        w->setValue(presets->itemData(i).toSize().width());
        h->setValue(presets->itemData(i).toSize().height());
    });
    auto *paper = new QComboBox;
    paper->addItem(tr("White"), QColor(Qt::white));
    paper->addItem(tr("Transparent"), QColor(Qt::transparent));
    paper->addItem(tr("Black"), QColor(Qt::black));
    form->addRow(tr("Size"), presets);
    form->addRow(tr("Width"), w);
    form->addRow(tr("Height"), h);
    form->addRow(tr("Paper"), paper);
    auto *buttons = new QDialogButtonBox(QDialogButtonBox::Ok | QDialogButtonBox::Cancel);
    form->addRow(buttons);
    connect(buttons, &QDialogButtonBox::accepted, &dialog, &QDialog::accept);
    connect(buttons, &QDialogButtonBox::rejected, &dialog, &QDialog::reject);
    if (dialog.exec() != QDialog::Accepted)
        return;
    m_doc.reset(QSize(w->value(), h->value()), paper->currentData().value<QColor>());
    updateTitle();
}

bool MainWindow::openFile(const QString &path)
{
    QString error;
    if (!m_doc.load(path, &error)) {
        QMessageBox::warning(this, tr("Could not open"), tr("%1: %2").arg(QFileInfo(path).fileName(), error));
        return false;
    }
    updateTitle();
    m_canvas->fit();
    return true;
}

void MainWindow::open()
{
    if (!askToSave())
        return;
    const QString path = QFileDialog::getOpenFileName(this, tr("Open a picture"),
        QStandardPaths::writableLocation(QStandardPaths::PicturesLocation), filters());
    if (!path.isEmpty())
        openFile(path);
}

bool MainWindow::save()
{
    if (!m_doc.path().endsWith(QLatin1String(".ora"), Qt::CaseInsensitive))
        return saveAs();   // a PNG opened here is saved with its layers as .ora; Export makes a flat picture
    QString error;
    if (!m_doc.saveOra(m_doc.path(), &error)) {
        QMessageBox::warning(this, tr("Could not save"), error);
        return false;
    }
    updateTitle();
    return true;
}

bool MainWindow::saveAs()
{
    QString suggested = m_doc.path().isEmpty()
        ? QStandardPaths::writableLocation(QStandardPaths::PicturesLocation) + tr("/Untitled.ora")
        : QFileInfo(m_doc.path()).path() + QLatin1Char('/') + QFileInfo(m_doc.path()).completeBaseName() + QStringLiteral(".ora");
    QString path = QFileDialog::getSaveFileName(this, tr("Save with layers"), suggested, tr("OpenRaster (*.ora)"));
    if (path.isEmpty())
        return false;
    if (!path.endsWith(QLatin1String(".ora"), Qt::CaseInsensitive))
        path += QStringLiteral(".ora");
    QString error;
    if (!m_doc.saveOra(path, &error)) {
        QMessageBox::warning(this, tr("Could not save"), error);
        return false;
    }
    updateTitle();
    return true;
}

void MainWindow::exportImage()
{
    const QString base = m_doc.path().isEmpty() ? QStandardPaths::writableLocation(QStandardPaths::PicturesLocation) + tr("/Untitled")
                                                : QFileInfo(m_doc.path()).path() + QLatin1Char('/') + QFileInfo(m_doc.path()).completeBaseName();
    const QString path = QFileDialog::getSaveFileName(this, tr("Export a flat picture"), base + QStringLiteral(".png"),
                                                      tr("PNG (*.png);;JPEG (*.jpg);;WebP (*.webp)"));
    if (path.isEmpty())
        return;
    QString error;
    if (!m_doc.exportImage(path, &error))
        QMessageBox::warning(this, tr("Could not export"), error);
    else
        statusBar()->showMessage(tr("Exported %1").arg(QFileInfo(path).fileName()), 4000);
}

void MainWindow::closeEvent(QCloseEvent *event)
{
    if (askToSave())
        event->accept();
    else
        event->ignore();
}
