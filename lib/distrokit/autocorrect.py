"""Safe, selection-based local AI autocorrect for graphical applications.

The feature deliberately uses the Wayland clipboard rather than reading
keyboard events. It refuses to run outside a Wayland session and in terminal
windows, so it cannot alter shell commands or TTY input.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request

from .ai import runtime

TERMINAL_CLASSES = {
    "alacritty", "foot", "footclient", "kitty", "konsole", "org.kde.konsole",
    "gnome-terminal", "kgx", "xfce4-terminal", "xterm", "urxvt", "wezterm",
    "com.mitchellh.ghostty", "tilix", "terminator", "ptyxis", "com.raggesilver.blackbox",
}


class AutocorrectError(RuntimeError):
    """A safe autocorrect operation could not be completed."""


def _active_window_class() -> str:
    if not shutil.which("hyprctl"):
        raise AutocorrectError("Could not verify the active application; refusing to type.")
    try:
        result = subprocess.run(["hyprctl", "-j", "activewindow"], check=True,
                                capture_output=True, text=True, timeout=3)
        window = json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        raise AutocorrectError("Could not identify the active application; refusing to type.") from exc
    return str(window.get("class", "")).lower()


def _require_safe_graphical_app() -> None:
    if not os.environ.get("WAYLAND_DISPLAY") or not os.environ.get("XDG_SESSION_TYPE") == "wayland":
        raise AutocorrectError("Autocorrect is available only in a Wayland desktop session, never on a TTY.")
    app_class = _active_window_class()
    if not app_class or app_class in TERMINAL_CLASSES or any(
        token in app_class for token in ("terminal", "konsole", "kitty", "alacritty", "wezterm", "foot")
    ):
        raise AutocorrectError("Autocorrect is disabled in terminal applications and TTYs.")


def correct_text(text: str, timeout: float = 20.0) -> str:
    """Correct spelling and grammar through the configured local llama-server."""
    if not text.strip():
        return text
    payload = {
        "model": "local",
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a conservative spelling and grammar corrector. "
                    "Correct clear spelling, punctuation, and grammar errors only. "
                    "Preserve meaning, tone, formatting, line breaks, names, URLs, "
                    "code, and intentional slang. Do not answer or explain. "
                    "Return only the corrected text. If no correction is needed, "
                    "return the input unchanged."
                ),
            },
            {"role": "user", "content": text},
        ],
        "temperature": 0.0,
        "max_tokens": min(2048, max(128, len(text.split()) * 3)),
    }
    request = urllib.request.Request(
        runtime.endpoint() + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
        corrected = result["choices"][0]["message"]["content"]
    except (OSError, urllib.error.URLError, KeyError, IndexError, TypeError, ValueError) as exc:
        raise AutocorrectError(
            "The local AI model is unavailable. Install and select a local GGUF model, "
            "then start it with the Nexora AI launcher."
        ) from exc
    if not isinstance(corrected, str) or not corrected.strip():
        raise AutocorrectError("The local model returned an empty correction.")
    return corrected


def correct_selection() -> int:
    """Replace selected text using wl-copy/wl-paste and wtype; never read raw keys."""
    _require_safe_graphical_app()
    required = ("wl-copy", "wl-paste", "wtype")
    missing = [name for name in required if not shutil.which(name)]
    if missing:
        raise AutocorrectError("Missing Wayland tools: " + ", ".join(missing))
    try:
        original_clipboard = subprocess.run(["wl-paste", "--no-newline"], check=True,
                                            capture_output=True, timeout=3).stdout
        subprocess.run(["wtype", "-M", "CTRL", "-P", "c", "-m", "CTRL"],
                       check=True, timeout=3)
        time.sleep(0.15)
        selected = subprocess.run(["wl-paste", "--no-newline"], check=True,
                                  capture_output=True, timeout=3).stdout.decode("utf-8")
        if not selected.strip():
            raise AutocorrectError("Select some text first.")
        corrected = correct_text(selected)
        if corrected == selected:
            return 0
        subprocess.run(["wl-copy"], input=corrected.encode("utf-8"), check=True, timeout=3)
        time.sleep(0.08)
        subprocess.run(["wtype", "-M", "CTRL", "-P", "v", "-m", "CTRL"],
                       check=True, timeout=3)
        time.sleep(0.15)
        subprocess.run(["wl-copy"], input=original_clipboard, check=True, timeout=3)
        return 0
    except AutocorrectError:
        raise
    except (OSError, subprocess.SubprocessError, UnicodeDecodeError) as exc:
        raise AutocorrectError(f"Could not safely replace the selected text: {exc}") from exc
