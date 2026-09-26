#!/usr/bin/env bash
# Static checks: Python lint, shell scripts (including the rendered *.in
# templates), PKGBUILD syntax and shell completions. Used by `make lint` and CI.
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."
export PYTHONPATH=lib
status=0
step() { printf '\033[1;35m==>\033[0m %s\n' "$*"; }
fail() { echo "FAILED: $*" >&2; status=1; }

step "ruff"
if command -v ruff >/dev/null; then ruff check lib tests || fail ruff; else echo "ruff not installed; skipped"; fi

step "shellcheck"
out="$(mktemp -d)"
trap 'rm -rf "$out"' EXIT
python3 - "$out" <<'PY'
import sys
from pathlib import Path
from distrokit.branding import load
b = load()
out = Path(sys.argv[1])
for tmpl in ["desktop/overlay/bin/session-start.in", "desktop/overlay/profile.d/profile.sh.in",
             *map(str, Path("iso/airootfs").rglob("*.in"))]:
    text = Path(tmpl).read_text()
    if not text.startswith("#!") and not tmpl.endswith("profile.sh.in"):
        continue
    dest = out / b.render(Path(tmpl).name.removesuffix(".in"))
    dest.write_text(b.render(text))
    print(dest)
PY
scripts=(build.sh scripts/*.sh tests/qemu/run.sh "$out"/*)
if command -v shellcheck >/dev/null; then
    shellcheck -x -s bash "${scripts[@]}" || fail shellcheck
else
    echo "shellcheck not installed; bash -n only"
    for s in "${scripts[@]}"; do bash -n "$s" || fail "bash -n $s"; done
fi

step "PKGBUILDs"
python3 -m distrokit.build.packages render --out "$out/pkgbuild" >/dev/null
for p in "$out"/pkgbuild/*/PKGBUILD; do bash -n "$p" || fail "$p"; done
if command -v namcap >/dev/null; then namcap "$out"/pkgbuild/*/PKGBUILD || true; fi

step "completions"
python3 -m distrokit.build.completions bash | bash -n || fail "bash completion"
if command -v fish >/dev/null; then
    python3 -m distrokit.build.completions fish | fish --no-execute || fail "fish completion"
    python3 -c 'import sys; from pathlib import Path; from distrokit.branding import load
sys.stdout.write(load().render(Path("desktop/overlay/fish/vendor.fish.in").read_text()))' | fish --no-execute ||
        fail "vendor.fish"
fi

step "package manifests"
python3 -m distrokit.build.manifests --check || fail "manifests (python3 -m distrokit.build.manifests)"

step "distro.conf and templates"
python3 -m distrokit.build.branding --quick >/dev/null || fail "branding templates"

if ((status)); then
    echo "Some checks failed." >&2
else
    echo "All checks passed."
fi
exit "$status"
