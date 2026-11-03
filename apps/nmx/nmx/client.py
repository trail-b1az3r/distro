"""Talking to nmxd over /run/nmx/nmx.sock: one JSON request per line, one reply per line."""

from __future__ import annotations

import json
import os
import socket
from collections.abc import Iterator

SOCKET = os.environ.get("NMX_SOCKET", "/run/nmx/nmx.sock")


class NotRunning(Exception):
    pass


def request(req: dict, timeout: float = 120.0) -> dict:
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect(SOCKET)
    except OSError as error:
        raise NotRunning(str(error)) from None
    with sock, sock.makefile("rwb") as stream:
        stream.write((json.dumps(req) + "\n").encode())
        stream.flush()
        line = stream.readline()
    if not line:
        raise NotRunning("nmxd closed the connection")
    return json.loads(line)


def events() -> Iterator[dict]:
    """`monitor`: every event nmxd sends, as it sends it."""
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(SOCKET)
    except OSError as error:
        raise NotRunning(str(error)) from None
    with sock, sock.makefile("rwb") as stream:
        stream.write(b'{"op": "monitor"}\n')
        stream.flush()
        stream.readline()
        for line in stream:
            try:
                yield json.loads(line)
            except ValueError:
                continue


def running() -> bool:
    try:
        return request({"op": "status"}, timeout=3).get("ok", False)
    except (NotRunning, OSError, ValueError):
        return False
