"""FrontArt (apps/frontart): packaged, tested at build time, and on the desktop."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_frontart_is_packaged_and_checked():
    pkgbuild = (ROOT / "packages/pkgbuild/frontart/PKGBUILD.in").read_text()
    assert "--self-test" in pkgbuild and "QT_QPA_PLATFORM=offscreen" in pkgbuild
    assert '"frontart"' in (ROOT / "packages/repo.toml").read_text()
    assert "@DISTRO_ID@-frontart" in (ROOT / "packages/lists/desktop.list").read_text().split()


def test_frontart_reads_pens_and_openraster():
    src = ROOT / "apps/frontart/src"
    canvas = (src / "canvas.cpp").read_text()
    assert "void Canvas::tabletEvent(QTabletEvent *event)" in canvas and "event->pressure()" in canvas
    assert "QPointingDevice::PointerType::Eraser" in canvas
    document = (src / "document.cpp").read_text()
    assert 'QByteArrayLiteral("image/openraster"), true' in document     # stored first, as the format asks
    assert "mergedimage.png" in document and "Thumbnails/thumbnail.png" in document
    desktop = (ROOT / "apps/frontart/data/frontart.desktop.in").read_text()
    assert "image/openraster" in desktop and "Categories=Graphics;2DGraphics;RasterGraphics;" in desktop
