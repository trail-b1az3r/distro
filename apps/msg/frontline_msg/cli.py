"""frontline-msg from the command line: sync, import, search and list, without the window."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import threading

from . import __version__, wired
from .service import Service

H_START, H_END = "\x02", "\x03"


def when(ms: int) -> str:
    return dt.datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M") if ms else ""


def remote(args) -> int:
    from . import rdp
    if not args.host:
        found = rdp.discover()
        print("\n".join(f"{p['name']}  {p['dns'] or p['host']}" for p in found) or
              "No computer on Tailscale shares its desktop (rdp-express serve).")
        return 0
    host, _, port = args.host.rpartition(":") if args.host.count(":") == 1 else (args.host, "", "")
    got = threading.Event()
    picture = {}

    def on_frame(number, width, height, rects):
        picture.update(size=(width, height), rects=picture.get("rects", []) + rects)
        got.set()
    r = rdp.Remote(on_frame=on_frame)
    try:
        r.connect(host, int(port) if port.isdigit() else rdp.PORT, args.code)
    except rdp.RemoteError as error:
        print(f"frontline-msg: {error}", file=sys.stderr)
        return 1
    info = r.info
    print(f"{r.server}: {info.get('output')} {info.get('width')}x{info.get('height')}, "
          f"{'control' if info.get('pointer') and info.get('keyboard') else 'view only'}")
    if args.snapshot:
        if not got.wait(10):
            print("frontline-msg: no picture came", file=sys.stderr)
            r.close()
            return 1
        from PySide6.QtGui import QImage, QPainter
        w, h = picture["size"]
        img = QImage(w, h, QImage.Format.Format_RGB32)
        p = QPainter(img)
        for x, y, _w, _h, jpeg in picture["rects"]:
            p.drawImage(x, y, QImage.fromData(jpeg, "JPG"))
        p.end()
        img.save(args.snapshot)
        print(f"saved {args.snapshot}")
    r.close()
    return 0


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="frontline-msg", description="Your iPhone's messages on Frontline.")
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("--store", help="the message store (default: ~/.local/share/frontline-msg/messages.db)")
    p.add_argument("--json", action="store_true", help="print JSON")
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("devices", help="iPhones on the cable")
    s = sub.add_parser("sync", help="back the iPhone up over the cable and import its messages and contacts")
    s.add_argument("--udid", default="")
    i = sub.add_parser("import", help="import an existing unencrypted iPhone backup folder")
    i.add_argument("folder")
    q = sub.add_parser("search", help="search messages, people and conversations")
    q.add_argument("words", nargs="+")
    sub.add_parser("chats", help="conversations, latest first")
    sub.add_parser("stats", help="how much is in the store")
    rm = sub.add_parser("remote", help="another computer's desktop (rdp-express): check it, or save a picture of it")
    rm.add_argument("host", nargs="?", default="", help="its name or address (empty: list the ones on Tailscale)")
    rm.add_argument("--code", default="", help="the pairing code `rdp-express pair` showed (the first time)")
    rm.add_argument("--snapshot", default="", help="save its screen to this file (PNG)")
    args = p.parse_args(argv)
    if not args.cmd:
        p.print_help()
        return 2
    if args.cmd == "devices":
        found = wired.devices()
        print(json.dumps(found, indent=2) if args.json else
              "\n".join(f"{d['name']}  {d['udid']}  ({d['link']})" for d in found) or "No iPhone found.")
        return 0
    if args.cmd == "remote":
        return remote(args)
    from pathlib import Path
    svc = Service(Path(args.store) if args.store else None)
    try:
        if args.cmd == "sync":
            done = threading.Event()
            failed = []

            def listen(kind, data):
                if kind == "progress" and not args.json:
                    pct = data.get("percent", -1)
                    print(f"\r{data.get('text', '')} {pct if pct >= 0 else ''}{'%' if pct >= 0 else ''}   ", end="",
                          file=sys.stderr, flush=True)
                elif kind == "synced":
                    print(json.dumps(data) if args.json else f"\n{data['added']} new messages, "
                          f"{data.get('contacts', 0)} contacts")
                elif kind == "error":
                    failed.append(data["message"])
                elif kind == "busy" and not data["busy"]:
                    done.set()
            svc.listen(listen)
            svc.sync_backup(args.udid)
            done.wait()
            if failed:
                print(f"\nfrontline-msg: {failed[0]}", file=sys.stderr)
                return 1
        elif args.cmd == "import":
            result = svc.import_backup(args.folder)
            print(json.dumps(result) if args.json else f"{result['added']} new messages ({result['seen']} read), "
                  f"{result['contacts']} contacts")
        elif args.cmd == "search":
            found = svc.search(" ".join(args.words))
            if args.json:
                print(json.dumps(found, indent=2))
            else:
                for c in found["contacts"]:
                    print(f"[person] {c['name']}  {', '.join(c['handles'])}")
                for m in found["messages"]:
                    text = m["snippet"].replace(H_START, "\033[1m").replace(H_END, "\033[0m")
                    print(f"{when(m['date_ms'])}  {m['sender']}: {text}")
        elif args.cmd == "chats":
            chats = svc.chats()
            print(json.dumps(chats, indent=2) if args.json else
                  "\n".join(f"{when(c['last_ms'])}  {c['title']}: {c['last_text'][:60]}" for c in chats))
        elif args.cmd == "stats":
            print(json.dumps(svc.core.call("stats")))
    except Exception as error:  # noqa: BLE001
        print(f"frontline-msg: {error}", file=sys.stderr)
        return 1
    finally:
        svc.close()
    return 0
