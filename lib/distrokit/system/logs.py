"""Diagnostic logs: always kept on this computer; shared only when turned on.

Sharing is off by default. Its state is /etc/<id>/logging.conf
(``share=yes|no``). Turned on, ``<cli> logs send`` files a report in the
GitHub repository named by DISTRO_LOG_REPO in distro.conf: through the
GitHub CLI when it is logged in, otherwise as a pre-filled issue opened in
the browser for the user to submit. Nothing is sent without that command.
"""

from __future__ import annotations

import socket
import tarfile
import urllib.parse
import webbrowser
from pathlib import Path

from .. import paths, util
from ..branding import Branding, load as load_branding

# GitHub refuses longer issue URLs; the browser fallback is cut to this.
URL_BODY_LIMIT = 6000


def config_path(branding: Branding, root: Path | str = "/") -> Path:
    return Path(root) / "etc" / branding.id / "logging.conf"


def sharing_enabled(branding: Branding | None = None, root: Path | str = "/") -> bool:
    branding = branding or load_branding()
    try:
        text = config_path(branding, root).read_text()
    except OSError:
        return False
    return any(line.strip().lower() in ("share=yes", "share=true", "share=1") for line in text.splitlines())


def set_sharing(enabled: bool, branding: Branding | None = None, root: Path | str = "/") -> Path:
    branding = branding or load_branding()
    path = config_path(branding, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"# {branding.pretty_name}: share diagnostic logs (`{branding.cli} logs on|off`).\n"
                    f"share={'yes' if enabled else 'no'}\n")
    return path


def log_repo(branding: Branding | None = None) -> str:
    return (branding or load_branding()).get("DISTRO_LOG_REPO", "").strip().strip("/")


def local_dir(branding: Branding, home: Path | None = None) -> Path:
    return paths.user_state_dir(branding.id, home) / "logs"


def save(branding: Branding | None = None, home: Path | None = None) -> Path:
    """A support bundle in ~/.local/state/<id>/logs. Stays on this computer."""
    from . import doctor

    branding = branding or load_branding()
    dest = local_dir(branding, home)
    dest.mkdir(parents=True, exist_ok=True)
    return doctor.write_report(doctor.Doctor("/", branding).run(), dest, branding)


def summary(bundle: Path, limit: int = 60000) -> str:
    """The text of a bundle, for an issue body: doctor results first."""
    order = ("doctor.json", "uname.txt", "install.json", "journal-boot.txt", "lspci.txt", "lsblk.txt")
    parts = []
    with tarfile.open(bundle) as tar:
        members = {Path(m.name).name: m for m in tar.getmembers() if m.isfile()}
        for name in order:
            m = members.get(name)
            f = tar.extractfile(m) if m else None
            if f:
                text = f.read().decode(errors="replace").strip()
                parts.append(f"### {name}\n\n```\n{text}\n```\n")
    body = "\n".join(parts)
    return body if len(body) <= limit else body[:limit] + "\n\n(cut short)\n"


def send(bundle: Path, branding: Branding | None = None, runner: util.Runner | None = None,
         open_browser=webbrowser.open) -> str:
    """File the bundle in DISTRO_LOG_REPO. Returns where it went."""
    branding = branding or load_branding()
    repo = log_repo(branding)
    if not sharing_enabled(branding):
        raise RuntimeError(f"log sharing is off: `sudo {branding.cli} logs on` turns it on")
    if not repo:
        raise RuntimeError("no log repository is set (DISTRO_LOG_REPO in distro.conf)")
    title = f"{branding.pretty_name} logs from {socket.gethostname()} ({bundle.stem})"
    body = summary(bundle)
    runner = runner or util.Runner()
    if util.which("gh") and runner.run(["gh", "auth", "status"], check=False, capture=True, mutating=False).ok:
        res = runner.run(["gh", "issue", "create", "-R", repo, "--title", title, "--body-file", "-"],
                         input=body, check=False, capture=True)
        if res.ok:
            return res.stdout.strip() or f"https://github.com/{repo}/issues"
    short = body if len(body) <= URL_BODY_LIMIT else body[:URL_BODY_LIMIT] + "\n\n(cut short; the full bundle is " \
        f"{bundle} on the sender's computer)\n"
    url = f"https://github.com/{repo}/issues/new?" + urllib.parse.urlencode({"title": title, "body": short})
    open_browser(url)
    return url
