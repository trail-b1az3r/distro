"""Safe local autocorrect integration tests."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from distrokit import autocorrect


def test_correct_text_uses_local_openai_compatible_endpoint(monkeypatch):
    seen = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            seen["path"] = self.path
            seen["payload"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            body = json.dumps({
                "choices": [{"message": {"content": "The corrected sentence."}}]
            }).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(
        "distrokit.autocorrect.runtime.endpoint",
        lambda: f"http://127.0.0.1:{server.server_address[1]}/v1",
    )
    try:
        assert autocorrect.correct_text("The sentnce.") == "The corrected sentence."
    finally:
        server.shutdown()
        thread.join()
    assert seen["path"] == "/v1/chat/completions"
    assert seen["payload"]["temperature"] == 0.0
    assert seen["payload"]["messages"][1]["content"] == "The sentnce."


def test_empty_text_is_returned_without_model_call(monkeypatch):
    monkeypatch.setattr(
        "distrokit.autocorrect.runtime.endpoint",
        lambda: pytest.fail("empty text must not contact the model"),
    )
    assert autocorrect.correct_text("") == ""


def test_tty_session_is_always_rejected(monkeypatch):
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.setenv("XDG_SESSION_TYPE", "tty")
    with pytest.raises(autocorrect.AutocorrectError, match="never on a TTY"):
        autocorrect._require_safe_graphical_app()


@pytest.mark.parametrize("app", [
    "Alacritty", "kitty", "org.kde.konsole", "foot", "wezterm", "gnome-terminal",
])
def test_terminal_windows_are_rejected(monkeypatch, app):
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-1")
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    monkeypatch.setattr(autocorrect, "_active_window_class", lambda: app.lower())
    with pytest.raises(autocorrect.AutocorrectError, match="disabled in terminal"):
        autocorrect._require_safe_graphical_app()


def test_empty_active_window_is_rejected(monkeypatch):
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-1")
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    monkeypatch.setattr(autocorrect, "_active_window_class", lambda: "")
    with pytest.raises(autocorrect.AutocorrectError, match="refusing to type"):
        autocorrect._require_safe_graphical_app()

def test_runner_backend_defaults_to_legacy_and_can_be_changed(tmp_path, monkeypatch):
    from distrokit.ai import runtime

    class FakeBranding:
        id = "nexora"

    monkeypatch.setattr(runtime, "runner_config_path", lambda _branding=None: tmp_path / "ai-runtime.toml")
    assert runtime.runner_backend(FakeBranding()) == "legacy"
    runtime.set_runner_backend("ggml-hnx", FakeBranding())
    assert runtime.runner_backend(FakeBranding()) == "ggml-hnx"
    runtime.set_runner_backend("t1", FakeBranding())
    assert runtime.runner_backend(FakeBranding()) == "t1"
    with pytest.raises(ValueError):
        runtime.set_runner_backend("invalid", FakeBranding())
