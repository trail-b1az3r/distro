#pragma once

#include "brush.h"
#include "canvas.h"
#include "colorpicker.h"
#include "document.h"

#include <QMainWindow>

class QComboBox;
class QLabel;
class QListWidget;
class QSlider;
class QActionGroup;

class MainWindow : public QMainWindow {
    Q_OBJECT
public:
    explicit MainWindow(QWidget *parent = nullptr);
    bool openFile(const QString &path);
    Document *document() { return &m_doc; }
    Canvas *canvas() { return m_canvas; }

protected:
    void closeEvent(QCloseEvent *event) override;
    void showEvent(QShowEvent *event) override;

private:
    void buildMenus();
    QWidget *buildToolPanel();
    QWidget *buildLayerPanel();
    void refreshLayers();
    void choosePreset(int index);
    void brushEdited();
    void newDocument();
    void open();
    bool save();
    bool saveAs();
    void exportImage();
    bool askToSave();
    void updateTitle();

    Document m_doc;
    Canvas *m_canvas = nullptr;
    ColorPicker *m_picker = nullptr;
    QList<Brush> m_presets;
    QListWidget *m_brushList = nullptr;
    QSlider *m_size = nullptr, *m_opacity = nullptr, *m_flow = nullptr, *m_hardness = nullptr, *m_softness = nullptr;
    QListWidget *m_layerList = nullptr;
    QSlider *m_layerOpacity = nullptr;
    QComboBox *m_blend = nullptr;
    QLabel *m_status = nullptr;
    QActionGroup *m_tools = nullptr;
    bool m_refreshing = false;
    bool m_firstShow = true;
};

// The window's colours from the desktop's Halcyon theme (Material colours in
// ~/.local/state/quickshell/user/generated/colors.json), else a dark default.
void applyDesktopPalette();
