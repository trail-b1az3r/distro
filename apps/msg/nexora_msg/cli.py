"""nexora-msg from the command line: sync, import, search and list, without the window."""

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


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="nexora-msg", description="Your iPhone's messages on Nexora.")
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("--store", help="the message store (default: ~/.local/share/nexora-msg/messages.db)")
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
    args = p.parse_args(argv)
    if not args.cmd:
        p.print_help()
        return 2
    if args.cmd == "devices":
        found = wired.devices()
        print(json.dumps(found, indent=2) if args.json else
              "\n".join(f"{d['name']}  {d['udid']}  ({d['link']})" for d in found) or "No iPhone found.")
        return 0
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
                print(f"\nnexora-msg: {failed[0]}", file=sys.stderr)
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
        print(f"nexora-msg: {error}", file=sys.stderr)
        return 1
    finally:
        svc.close()
    return 0
