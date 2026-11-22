"""The login screen stays the distribution's SilentSDDM after a desktop's installer (HyDE) picks its own."""

from distrokit import paths
from distrokit.branding import load as load_branding
from distrokit.build import branding, stage

B = load_branding()


def test_the_branding_package_sets_it_last(tmp_path):
    # Stage.branding() packages the complete generated artwork, not just the
    # rendered templates. quick=True deliberately skips wallpapers, icons,
    # boot artwork, and other raster assets, so it cannot be used here.
    branding.generate(log=lambda _m: None)
    st = stage.Stage(tmp_path, B)
    st.branding()
    conf = tmp_path / f"etc/sddm.conf.d/zz-{B.id}-theme.conf"
    assert f"[Theme]\nCurrent={B.id}\n" in conf.read_text()
    # SDDM reads sddm.conf.d in name order, the last Current= wins: after HyDE's file, and after the old 99- one.
    assert sorted(["the_hyde_project.conf", f"99-{B.id}-theme.conf", conf.name])[-1] == conf.name
    theme = tmp_path / f"usr/share/sddm/themes/{B.id}"
    assert (theme / "backgrounds/default.jpg").stat().st_size > 100_000   # the photograph, not a drawn background
    assert 'background = "default.jpg"' in (theme / "configs/theme.conf").read_text()


def test_installing_a_desktop_puts_it_back_last():
    script = paths.data("desktop", "profiles", "install-selected.sh").read_text()
    assert 'etc/sddm.conf.d/zz-$DISTRO_ID-theme.conf' in script
    assert '"zz-$DISTRO_ID-theme.conf") return 0' in script     # never set aside as an installer's file
