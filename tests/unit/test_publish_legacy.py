"""Repositories are also published under the distribution's former names (scripts/publish-legacy.sh), so systems
installed as Nexora, whose pacman.conf still reads [nexora-experiments] or [nexora-surface], see the renamed
packages and are offered them on their next pacman -Syu."""

import os
import subprocess

from distrokit import paths

SCRIPT = paths.data("scripts", "publish-legacy.sh")


def fake(tmp_path, existing=("nexora-surface",), assets_in_release=("old-1.pkg.tar.zst", "nexora-surface.db")):
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    log = tmp_path / "gh.log"
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    (bin_ / "gh").write_text(f"""#!/bin/sh
echo "$*" >> {log}
case "$1 $2" in
  "release view")
    case " {' '.join(existing)} " in *" $3 "*) ;; *) exit 1 ;; esac
    [ "$4" = --json ] && printf '%s\\n' {' '.join(assets_in_release)}
    exit 0 ;;
  "release upload") shift 3; for f in "$@"; do [ "$f" = --clobber ] || cp "$f" {uploads}/; done ;;
esac
exit 0
""")
    (bin_ / "gh").chmod(0o755)
    assets = tmp_path / "assets"
    assets.mkdir()
    return {"PATH": f"{bin_}:{os.environ['PATH']}"}, log, uploads, assets


def test_surface_is_also_published_as_nexora_surface(tmp_path):
    env, log, uploads, assets = fake(tmp_path)
    for name in ("frontline-surface.db.tar.gz", "frontline-surface.db", "frontline-surface.files",
                 "linux-surface-7.3-1-x86_64.pkg.tar.zst", "linux-surface-7.3-1-x86_64.pkg.tar.zst.sig"):
        (assets / name).write_text(name)
    res = subprocess.run(["bash", str(SCRIPT), str(assets), "frontline-surface", "--prune"], env=env,
                         capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
    got = sorted(p.name for p in uploads.iterdir())
    assert got == ["linux-surface-7.3-1-x86_64.pkg.tar.zst", "linux-surface-7.3-1-x86_64.pkg.tar.zst.sig",
                   "nexora-surface.db", "nexora-surface.db.tar.gz", "nexora-surface.files"]
    assert (uploads / "nexora-surface.db").read_text() == "frontline-surface.db"   # the same database
    calls = log.read_text()
    assert "release delete-asset nexora-surface old-1.pkg.tar.zst --yes" in calls   # pruned: no longer listed
    assert "delete-asset nexora-surface nexora-surface.db " not in calls


def test_a_missing_old_release_is_made(tmp_path):
    env, log, uploads, assets = fake(tmp_path, existing=())
    (assets / "frontline-experiments.db").write_text("db")
    (assets / "frontline-core-1-1-any.pkg.tar.zst").write_text("pkg")
    subprocess.run(["bash", str(SCRIPT), str(assets), "frontline-experiments"], env=env, check=True,
                   capture_output=True)
    assert "release create nexora-experiments" in log.read_text()
    assert (uploads / "nexora-experiments.db").exists()


def test_the_main_repository_is_left_to_publish_repo(tmp_path):
    env, log, uploads, assets = fake(tmp_path)
    res = subprocess.run(["bash", str(SCRIPT), str(assets), "frontline"], env=env, capture_output=True, text=True)
    assert res.returncode == 0 and not log.exists()


def test_the_workflows_use_it():
    ci = paths.data(".github", "workflows", "ci.yml").read_text()
    surface = paths.data(".github", "workflows", "surface.yml").read_text()
    assert 'publish-legacy.sh build/experiments-assets "$REPO"' in ci
    assert 'publish-legacy.sh build/surface-assets "$REPO" --prune' in surface
