"""nmxcli: nmx from the command line, with nmcli's commands, abbreviations, output modes and exit codes.

    nmxcli [OPTIONS] OBJECT { COMMAND | help }

    OBJECT  g[eneral]  n[etworking]  r[adio]  c[onnection]  d[evice]  m[onitor]  p[ortal]

    OPTIONS -t, --terse                 terse output (fields split by ':', ':' and '\\' escaped)
            -f, --fields FIELD,...|all  which fields to print
            -g, --get-values FIELD,...  -t -f FIELDS, without headers
            -m, --mode tabular|multiline
            -e, --escape yes|no
            -a, --ask                   ask for missing passwords and usernames
            -s, --show-secrets          show passwords in `connection show`
            -w, --wait SECONDS          how long to wait for an activation (default 90)
            -v, --version, -h, --help

Beyond nmcli: `device wifi connect` takes `username`, `eap`, `phase2`, `ca-cert`, `domain`, `cert`, `key`,
`key-password` and `anonymous-identity` for enterprise (802.1X) networks, and asks for what the network needs (a
password; or a username and a password) when run in a terminal. `device unmanage` (root only) is the one way to take
a device away from nmx; `device manage` gives it back. `device remanagenm` (root only) hands every device back to
NetworkManager and turns NetworkManager on; `device manage` takes them all back. `connection import networkmanager`
brings NetworkManager's saved connections over. `nmx` is a short name for `nmxcli`.

Captive portals (hotel, airport and café Wi-Fi that wants you to sign in first): `networking connectivity` says
`portal`, and `nmxcli portal` prints the sign-in page (`portal open` opens it in your browser, `portal check` checks
again now). nmx finds the page from the network's RFC 8910/8908 announcement when it makes one, and otherwise from
where the portal redirects a plain-HTTP probe.
"""

from __future__ import annotations

import getpass
import os
import sys
from collections.abc import Callable

from . import __version__, client

EXIT = {"invalid": 2, "timeout": 3, "failed": 4, "secrets": 4, "certificate": 4, "ip": 4, "unavailable": 4,
        "not-active": 10, "not-found": 10, "permission": 1}

STATE_TEXT = {
    "connected": "connected", "connecting": "connecting (configuring)",
    "getting-ip": "connecting (getting IP configuration)", "disconnected": "disconnected",
    "unavailable": "unavailable", "unmanaged": "unmanaged", "failed": "disconnected",
}
STATE_CODE = {"connected": 100, "getting-ip": 70, "connecting": 50, "disconnected": 30, "unavailable": 20, "unmanaged": 10}


class Usage(Exception):
    pass


class Options:
    terse = False
    fields: list[str] | None = None
    get_values = False
    mode = ""
    escape = True
    ask = False
    show_secrets = False
    wait = 90.0


def pick(word: str, choices: list[str]) -> str:
    """nmcli's abbreviations: any prefix that picks one choice (and the first, by nmcli's order, on a tie)."""
    for choice in choices:
        if choice == word:
            return choice
    for choice in choices:
        if choice.startswith(word):
            return choice
    raise Usage(f"argument '{word}' not understood. Try one of: {', '.join(choices)}")


# ── output ───────────────────────────────────────────────────────────────────────────────────────────────────────

def escape(value: str, opts: Options) -> str:
    return value.replace("\\", "\\\\").replace(":", "\\:") if opts.escape else value


def table(rows: list[dict], fields: dict[str, Callable[[dict], object]], default: list[str], opts: Options) -> str:
    names = choose_fields(fields, default, opts)
    cells = [[text(fields[n](row)) for n in names] for row in rows]
    if opts.terse:
        return "".join(":".join(escape(c, opts) for c in line) + "\n" for line in cells)
    widths = [max([len(n)] + [len(line[i]) for line in cells]) for i, n in enumerate(names)]
    out = ["  ".join(n.ljust(widths[i]) for i, n in enumerate(names)).rstrip()]
    out += ["  ".join(c.ljust(widths[i]) for i, c in enumerate(line)).rstrip() for line in cells]
    return "\n".join(out) + "\n"


def choose_fields(fields: dict, default: list[str], opts: Options) -> list[str]:
    if not opts.fields or opts.fields == ["common"]:
        return default
    if opts.fields == ["all"]:
        return list(fields)
    names = []
    for name in opts.fields:
        upper = name.upper()
        if upper not in fields:
            raise Usage(f"invalid field '{name}'; allowed fields: {','.join(fields)}")
        names.append(upper)
    return names


def multiline(pairs: list[tuple[str, str]], opts: Options) -> str:
    wanted = [f.upper() for f in opts.fields] if opts.fields and opts.fields not in (["all"], ["common"]) else None
    out = []
    for key, value in pairs:
        if wanted and not any(key == w or key.split(".")[0] == w or key.split("[")[0] == w for w in wanted):
            continue
        if opts.get_values:
            out.append(value)
        elif opts.terse:
            out.append(f"{key}:{value}")
        else:
            out.append(f"{key + ':':<40}{value or '--'}")
    return "\n".join(out) + ("\n" if out else "")


def text(value: object) -> str:
    if value is True:
        return "yes"
    if value is False:
        return "no"
    return "" if value is None else str(value)


def bars(signal: int) -> str:
    return "".join(c if signal > t else "_" for c, t in zip("▂▄▆█", (0, 25, 50, 75), strict=True))


DEVICE_FIELDS = {
    "DEVICE": lambda r: r["device"], "TYPE": lambda r: r["type"],
    "STATE": lambda r: STATE_TEXT.get(r["state"], r["state"]),
    "IP4-CONNECTIVITY": lambda r: "full" if r["state"] == "connected" else "none",
    "IP6-CONNECTIVITY": lambda r: "full" if r["state"] == "connected" else "none",
    "DBUS-PATH": lambda r: f"/nmx/Devices/{r['device']}", "CONNECTION": lambda r: r["connection"] or "--",
    "CON-UUID": lambda r: r["con-uuid"] or "--", "CON-PATH": lambda r: f"/nmx/Active/{r['con-uuid']}" if r["connection"] else "--",
    "MANAGED": lambda r: r["managed"], "DRIVER": lambda r: r["driver"], "REASON": lambda r: r["reason"],
}
WIFI_FIELDS = {
    "NAME": lambda r: "AP", "SSID": lambda r: r["ssid"] or "--", "SSID-HEX": lambda r: r["ssid"].encode().hex().upper(),
    "BSSID": lambda r: r["bssid"], "MODE": lambda r: "Infra", "CHAN": lambda r: r["chan"],
    "FREQ": lambda r: f"{r['freq']} MHz", "RATE": lambda r: "--", "SIGNAL": lambda r: r["signal"],
    "BARS": lambda r: bars(r["signal"]), "SECURITY": lambda r: r["security"] or "--",
    "WPA-FLAGS": lambda r: "--", "RSN-FLAGS": lambda r: r["flags"], "DEVICE": lambda r: r["device"],
    "ACTIVE": lambda r: r["in-use"], "IN-USE": lambda r: "*" if r["in-use"] else " ",
    "DBUS-PATH": lambda r: f"/nmx/AccessPoint/{r['bssid']}",
    "NEEDS": lambda r: "username+password" if r["needs-username"] else ("password" if r["needs-password"] else "--"),
    "SECURITY-DETAIL": lambda r: r["describe"], "PMF": lambda r: ("disabled", "optional", "required")[r["pmf"]],
    "SAVED": lambda r: r["saved"],
}
GENERAL_FIELDS = {
    "RUNNING": lambda r: r["running"], "VERSION": lambda r: r["version"], "STATE": lambda r: r["state"],
    "STARTUP": lambda r: r["startup"], "CONNECTIVITY": lambda r: r["connectivity"],
    "NETWORKING": lambda r: r["networking"], "WIFI-HW": lambda r: r["wifi-hw"], "WIFI": lambda r: r["wifi"],
    "WWAN-HW": lambda r: r["wwan-hw"], "WWAN": lambda r: r["wwan"], "METERED": lambda r: "no (guessed)",
    "PORTAL-URL": lambda r: r.get("portal-url", ""),
}
CONNECTION_FIELDS = {
    "NAME": lambda r: r["name"], "UUID": lambda r: r["uuid"], "TYPE": lambda r: r["type"],
    "TIMESTAMP": lambda r: r["timestamp"], "AUTOCONNECT": lambda r: r["autoconnect"],
    "AUTOCONNECT-PRIORITY": lambda r: r["priority"], "READONLY": lambda r: False,
    "DBUS-PATH": lambda r: f"/nmx/Settings/{r['uuid']}", "ACTIVE": lambda r: r["active"],
    "DEVICE": lambda r: r["device"] or "--", "STATE": lambda r: "activated" if r["active"] else "--",
    "ACTIVE-PATH": lambda r: f"/nmx/Active/{r['uuid']}" if r["active"] else "--", "SSID": lambda r: r["ssid"] or "--",
    "SECURITY": lambda r: r["security"] or "--",
}


# ── talking to nmxd ──────────────────────────────────────────────────────────────────────────────────────────────

class Failed(Exception):
    def __init__(self, reply: dict):
        super().__init__(reply.get("error", "failed"))
        self.reply = reply


def call(req: dict, opts: Options | None = None) -> dict:
    reply = client.request(req, timeout=(opts.wait if opts else 90) + 30)
    if not reply.get("ok"):
        raise Failed(reply)
    return reply


def ask_secrets(req: dict, need: list[str], opts: Options, describe: str = "") -> bool:
    """With --ask (or in a terminal, for `device wifi connect`): ask for what the network needs."""
    if not sys.stdin.isatty():
        return False
    if describe:
        print(f"{req.get('ssid', 'This network')}: {describe}")
    if "username" in need and not req.get("username"):
        req["username"] = input("Username: ").strip()
    if "password" in need:
        req["password"] = getpass.getpass("Password: ")
    if "certificate" in need:
        req["client-cert"] = input("Client certificate (file): ").strip()
        req["private-key"] = input("Private key (file, or the same .p12): ").strip() or req["client-cert"]
        req["private-key-password"] = getpass.getpass("Private key password (empty if none): ")
    return True


def activate(req: dict, opts: Options, interactive: bool) -> dict:
    for _ in range(3):
        try:
            return call(req, opts)
        except Failed as failed:
            reply = failed.reply
            if reply.get("code") == "secrets" and (opts.ask or interactive) and \
                    ask_secrets(req, reply.get("need", ["password"]), opts, reply.get("security", "")):
                continue
            raise
    return call(req, opts)


# ── commands ─────────────────────────────────────────────────────────────────────────────────────────────────────

def cmd_general(args: list[str], opts: Options) -> int:
    sub = pick(args.pop(0), ["status", "hostname", "permissions", "logging", "reload"]) if args else "status"
    if sub == "status":
        sys.stdout.write(table([call({"op": "status"})["data"]], GENERAL_FIELDS,
                               ["STATE", "CONNECTIVITY", "WIFI-HW", "WIFI", "WWAN-HW", "WWAN", "METERED"], opts))
    elif sub == "hostname":
        reply = call({"op": "hostname", "name": args[0] if args else ""})
        if not args:
            print(reply["data"])
    elif sub == "permissions":
        sys.stdout.write(table([{"p": "org.nmx.network-control", "v": "yes"}],
                               {"PERMISSION": lambda r: r["p"], "VALUE": lambda r: r["v"]}, ["PERMISSION", "VALUE"], opts))
    elif sub in ("logging", "reload"):
        print("journalctl -u nmx" if sub == "logging" else "", end="\n" if sub == "logging" else "")
    return 0


def cmd_networking(args: list[str], opts: Options) -> int:
    if not args:
        print(call({"op": "status"})["data"]["networking"])
        return 0
    sub = pick(args.pop(0), ["on", "off", "connectivity"])
    if sub == "connectivity":
        reply = call({"op": "connectivity", "check": bool(args and pick(args[0], ["check"]))})
        print(reply["data"])
        if reply["data"] == "portal" and reply.get("url") and sys.stderr.isatty():
            print(f"Sign in at {reply['url']}  (nmxcli portal open)", file=sys.stderr)
    else:
        call({"op": "networking", "enable": sub})
    return 0


def cmd_radio(args: list[str], opts: Options) -> int:
    if not args:
        sys.stdout.write(table([call({"op": "status"})["data"]], GENERAL_FIELDS, ["WIFI-HW", "WIFI", "WWAN-HW", "WWAN"], opts))
        return 0
    what = pick(args.pop(0), ["all", "wifi", "wwan"])
    if args:
        state = pick(args[0], ["on", "off"])
        if what in ("all", "wifi"):
            call({"op": "radio", "wifi": state})
        return 0
    data = call({"op": "status"})["data"]
    if what == "all":
        sys.stdout.write(table([data], GENERAL_FIELDS, ["WIFI-HW", "WIFI", "WWAN-HW", "WWAN"], opts))
    else:
        print(data["wifi"] if what == "wifi" else "enabled")
    return 0


SECRET_ARGS = {"password", "username", "key-password", "psk", "wifi-sec.psk", "802-1x.password", "802-1x.identity"}


def parse_pairs(args: list[str], allowed: set[str] | None = None) -> dict[str, str]:
    """KEY VALUE pairs. A secret given as env:NAME is read from the environment, so it never shows in ps."""
    out = {}
    while args:
        key = args.pop(0)
        if key.startswith("--"):
            key = key[2:]
        if not args:
            raise Usage(f"value for '{key}' is missing.")
        if allowed is not None and key not in allowed:
            raise Usage(f"invalid extra argument '{key}'.")
        value = args.pop(0)
        if key in SECRET_ARGS and value.startswith("env:"):
            value = os.environ.get(value[4:], "")
        out[key] = value
    return out


WIFI_CONNECT_ARGS = {"password", "wep-key-type", "ifname", "bssid", "name", "private", "hidden", "username", "eap",
                     "phase2", "ca-cert", "domain", "cert", "key", "key-password", "anonymous-identity"}


def cmd_device(args: list[str], opts: Options) -> int:
    sub = pick(args.pop(0), ["status", "show", "set", "connect", "reapply", "modify", "disconnect", "delete", "monitor",
                             "wifi", "lldp", "manage", "unmanage", "remanagenm", "remanage-nm"]) if args else "status"
    if sub == "status":
        rows = call({"op": "devices"})["data"]
        sys.stdout.write(table(rows, DEVICE_FIELDS, ["DEVICE", "TYPE", "STATE", "CONNECTION"], opts))
    elif sub == "show":
        rows = call({"op": "device-show", "ifname": args[0] if args else ""})["data"]
        blocks = [multiline(device_pairs(r), opts) for r in rows]
        sys.stdout.write(("" if opts.terse else "\n").join(blocks))
    elif sub == "connect":
        if not args:
            raise Usage("device name is missing.")
        print(call({"op": "device-connect", "ifname": args[0], "wait": opts.wait}, opts)["message"])
    elif sub in ("disconnect", "delete"):
        for iface in args or []:
            print(call({"op": "device-disconnect", "ifname": iface})["message"])
    elif sub == "reapply":
        call({"op": "device-connect", "ifname": args[0], "wait": opts.wait}, opts)
        print(f"Connection successfully reapplied to device '{args[0]}'.")
    elif sub == "set":
        if not args:
            raise Usage("device name is missing.")
        iface = args.pop(0)
        props = parse_pairs(args, {"managed", "autoconnect"})
        if "managed" in props:
            call({"op": "device-manage" if props["managed"] in ("yes", "true", "on") else "device-unmanage", "ifname": iface})
        if props.get("autoconnect") in ("no", "false", "off"):
            call({"op": "device-disconnect", "ifname": iface})
    elif sub in ("manage", "unmanage"):
        print(call({"op": f"device-{sub}", "ifname": args[0] if args else ""})["message"])
    elif sub in ("remanagenm", "remanage-nm"):
        # Every device back to NetworkManager, which is turned on (root only); `device manage` undoes it.
        print(call({"op": "device-remanagenm"})["message"])
    elif sub == "monitor":
        return cmd_monitor(args, opts)
    elif sub == "wifi":
        return cmd_wifi(args, opts)
    elif sub == "lldp":
        print("LLDP is not collected by nmx.")
    elif sub == "modify":
        raise Usage("use `nmxcli connection modify` (nmx applies profiles, not per-device overrides)")
    return 0


def device_pairs(r: dict) -> list[tuple[str, str]]:
    pairs = [("GENERAL.DEVICE", r["device"]), ("GENERAL.TYPE", r["type"]), ("GENERAL.HWADDR", r["hwaddr"]),
             ("GENERAL.MTU", r["mtu"]),
             ("GENERAL.STATE", f"{STATE_CODE.get(r['state'], 0)} ({STATE_TEXT.get(r['state'], r['state'])})"),
             ("GENERAL.CONNECTION", r["connection"] or "--"),
             ("GENERAL.CON-PATH", f"/nmx/Active/{r['con-uuid']}" if r["connection"] else "--"),
             ("GENERAL.DRIVER", r.get("driver") or "--"), ("GENERAL.MANAGED", text(r.get("managed")))]
    for family in ("4", "6"):
        for i, addr in enumerate(r.get(f"ip{family}", []), 1):
            pairs.append((f"IP{family}.ADDRESS[{i}]", addr))
        pairs.append((f"IP{family}.GATEWAY", r.get(f"gw{family}") or "--"))
        if family == "4":
            for i, route in enumerate(r.get("routes4", []), 1):
                pairs.append((f"IP4.ROUTE[{i}]", route))
        for i, dns in enumerate(r.get(f"dns{family}", []), 1):
            pairs.append((f"IP{family}.DNS[{i}]", dns))
        if family == "4":
            for i, domain in enumerate(r.get("domains", []), 1):
                pairs.append((f"IP4.DOMAIN[{i}]", domain))
    return pairs


def cmd_wifi(args: list[str], opts: Options) -> int:
    sub = pick(args.pop(0), ["list", "connect", "rescan", "show-password", "hotspot"]) if args else "list"
    if sub == "list":
        rescan, ifname, bssid = "auto", "", ""
        while args:
            key = args.pop(0)
            if key == "--rescan":
                rescan = pick(args.pop(0), ["auto", "no", "yes"])
            elif key in ("ifname", "bssid") and args:
                ifname, bssid = (args.pop(0), bssid) if key == "ifname" else (ifname, args.pop(0).lower())
            else:
                raise Usage(f"invalid extra argument '{key}'.")
        rows = call({"op": "wifi-list", "ifname": ifname, "rescan": rescan})["data"]
        rows = [r for r in rows if not bssid or r["bssid"].lower() == bssid]
        sys.stdout.write(table(rows, WIFI_FIELDS, ["IN-USE", "BSSID", "SSID", "MODE", "CHAN", "RATE", "SIGNAL", "BARS",
                                                   "SECURITY"], opts))
    elif sub == "rescan":
        props = parse_pairs(args, {"ifname", "ssid"})
        call({"op": "wifi-rescan", "ifname": props.get("ifname", "")})
    elif sub == "connect":
        if not args:
            raise Usage("SSID or BSSID is missing.")
        target = args.pop(0)
        props = parse_pairs(args, WIFI_CONNECT_ARGS)
        req = {"op": "wifi-connect", "wait": opts.wait, "ifname": props.get("ifname", ""),
               "hidden": props.get("hidden") in ("yes", "true", "on"), "name": props.get("name", "")}
        if len(target) == 17 and target.count(":") == 5:
            req["bssid"] = target.lower()
        else:
            req["ssid"] = target
        if props.get("bssid"):
            req["bssid"] = props["bssid"].lower()
        for key, field in (("password", "password"), ("username", "username"), ("eap", "eap"), ("phase2", "phase2-auth"),
                           ("ca-cert", "ca-cert"), ("domain", "domain-suffix-match"), ("cert", "client-cert"),
                           ("key", "private-key"), ("key-password", "private-key-password"),
                           ("anonymous-identity", "anonymous-identity")):
            if key in props:
                req[field] = props[key]
        reply = activate(req, opts, interactive=True)
        print(reply.get("message", "Connected."))
    elif sub == "show-password":
        rows = call({"op": "connections", "active": True})["data"]
        wifi = [r for r in rows if r["type"] == "wifi"]
        if not wifi:
            raise Failed({"code": "not-active", "error": "no Wi-Fi connection is active."})
        data = call({"op": "connection-show", "id": wifi[0]["uuid"], "show-secrets": True})["data"]
        print(f"SSID: {data.get('wifi', {}).get('ssid', '')}")
        print(f"Security: {data.get('wifi-security', {}).get('key-mgmt', 'none').upper()}")
        print(f"Password: {data.get('wifi-security', {}).get('psk') or data.get('802-1x', {}).get('password', '')}")
    elif sub == "hotspot":
        raise Usage("hotspots are not supported by nmx yet.")
    return 0


def cmd_connection(args: list[str], opts: Options) -> int:
    sub = pick(args.pop(0), ["show", "up", "down", "add", "modify", "clone", "edit", "delete", "monitor", "reload",
                             "load", "import", "export", "migrate"]) if args else "show"
    if sub == "show":
        active = False
        while args and args[0].startswith("-"):
            flag = args.pop(0)
            if flag in ("--active", "-a"):
                active = True
            elif flag in ("--order", "--show-secrets"):
                opts.show_secrets = opts.show_secrets or flag == "--show-secrets"
                if flag == "--order":
                    args.pop(0)
        if args:
            key = args.pop(-1) if args[0] in ("id", "uuid") else args.pop(0)
            data = call({"op": "connection-show", "id": key, "show-secrets": opts.show_secrets})["data"]
            pairs = [(f"{section}.{k}", v) for section, values in data.items() for k, v in values.items()]
            sys.stdout.write(multiline(pairs, opts))
        else:
            rows = call({"op": "connections", "active": active})["data"]
            sys.stdout.write(table(rows, CONNECTION_FIELDS, ["NAME", "UUID", "TYPE", "DEVICE"], opts))
    elif sub == "up":
        if not args:
            raise Usage("connection name is missing.")
        key = args.pop(-1) if args[0] in ("id", "uuid") and len(args) > 1 else args.pop(0)
        props = parse_pairs(args, {"ifname", "ap", "passwd-file", "password", "username"})
        req = {"op": "connection-up", "id": key, "ifname": props.get("ifname", ""), "wait": opts.wait}
        if props.get("passwd-file"):
            for line in open(props["passwd-file"], encoding="utf-8"):
                k, _, v = line.strip().partition(":")
                if k.endswith(".psk") or k.endswith(".password"):
                    req["password"] = v
                elif k.endswith(".identity"):
                    req["username"] = v
        req.update({k: v for k, v in props.items() if k in ("password", "username")})
        print(activate(req, opts, interactive=opts.ask).get("message", "Connection successfully activated."))
    elif sub == "down":
        for key in [a for a in args if a not in ("id", "uuid", "path", "apath")]:
            print(call({"op": "connection-down", "id": key})["message"])
    elif sub == "delete":
        for key in [a for a in args if a not in ("id", "uuid", "path")]:
            print(call({"op": "connection-delete", "id": key})["message"])
    elif sub == "add":
        props = parse_pairs(args)
        print(call({"op": "connection-add", "props": props})["message"])
    elif sub == "modify":
        if not args:
            raise Usage("connection name is missing.")
        key = args.pop(0)
        if key in ("id", "uuid"):
            key = args.pop(0)
        call({"op": "connection-modify", "id": key, "props": parse_pairs(args)})
    elif sub in ("import", "migrate"):
        source = args[-1] if args else "networkmanager"
        if source not in ("networkmanager", "nm", "NetworkManager"):
            raise Usage("nmx imports NetworkManager's saved connections: nmxcli connection import networkmanager")
        print(call({"op": "connection-import-nm"})["message"])
    elif sub == "export":
        data = call({"op": "connection-show", "id": args[0], "show-secrets": True})["data"]
        for section, values in data.items():
            print(f"[{section}]")
            for k, v in values.items():
                print(f"{k}={v}")
            print()
    elif sub == "edit":
        from . import tui
        return tui.main(["edit"] + args)
    elif sub == "monitor":
        return cmd_monitor(args, opts)
    elif sub in ("reload", "load"):
        pass
    elif sub == "clone":
        raise Usage("use `nmxcli connection export` and `connection add`")
    return 0


def cmd_portal(args: list[str], opts: Options) -> int:
    """`portal`: print the sign-in page (exit 0) or nothing (exit 10: no portal). `portal open`, `portal check`."""
    sub = pick(args.pop(0), ["show", "open", "check"]) if args else "show"
    data = call({"op": "portal", "check": sub == "check"})["data"]
    if data["connectivity"] != "portal" or not data["url"]:
        if not opts.terse:
            print(f"No captive portal (connectivity: {data['connectivity']}).", file=sys.stderr)
        return 10
    if sub == "open":
        return open_url(data["url"])
    if opts.terse:
        print(data["url"])
    else:
        print(f"{data['device'] or 'This network'} wants you to sign in at:\n    {data['url']}")
    return 0


def open_url(url: str) -> int:
    """Open the sign-in page in the user's browser; plain HTTP so the portal can redirect it."""
    import shutil
    import subprocess
    for opener in (["xdg-open"], ["gio", "open"], ["sensible-browser"]):
        if shutil.which(opener[0]):
            subprocess.Popen(opener + [url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
            print(f"Opening {url}")
            return 0
    print(url)
    return 0


def cmd_monitor(args: list[str], opts: Options) -> int:
    try:
        for event in client.events():
            line = describe_event(event)
            if line:
                print(line, flush=True)
    except KeyboardInterrupt:
        pass
    return 0


def describe_event(e: dict) -> str:
    kind = e.get("event")
    if kind == "device":
        state = STATE_TEXT.get(e["state"], e["state"])
        return f"{e['device']}: {state}" + (f" ({e['reason']})" if e.get("reason") and e["state"] != "connected" else "")
    if kind == "device-added":
        return f"{e['device']}: device created"
    if kind == "device-removed":
        return f"{e['device']}: device removed"
    if kind == "connectivity":
        if e["state"] == "portal" and e.get("url"):
            return f"Connectivity is now 'portal': sign in at {e['url']}"
        return f"Connectivity is now '{e['state']}'"
    if kind == "scan":
        return f"{e['device']}: {e['count']} networks in range"
    if kind == "secrets-required":
        return f"{e['device']}: '{e['connection']}' needs {' and '.join(e.get('need', ['password']))}"
    if kind == "certificate-trusted":
        return f"{e['device']}: trusted the certificate of '{e['connection']}' ({e.get('subject', '')}, SHA-256 {e.get('sha256', '')})"
    if kind == "resumed":
        return "Woke up: reconnecting"
    return ""


def overview(opts: Options) -> int:
    for row in call({"op": "device-show"})["data"]:
        if row["type"] == "loopback":
            continue
        state = STATE_TEXT.get(row["state"], row["state"])
        print(f"{row['device']}: {state}" + (f" to {row['connection']}" if row["connection"] else ""))
        print(f"        {row['type']}, {row['hwaddr']}, {row['driver'] or 'unknown driver'}, mtu {row['mtu']}")
        for addr in row.get("ip4", []) + row.get("ip6", []):
            print(f"        inet {addr}")
        if row.get("gw4"):
            print(f"        route default via {row['gw4']}")
        print()
    dns = sorted({d for row in call({"op": "device-show"})["data"] for d in row.get("dns4", []) + row.get("dns6", [])})
    if dns:
        print("DNS configuration:\n        servers: " + " ".join(dns) + "\n")
    print('Use "nmxcli device show" to get complete information about known devices and\n'
          '"nmxcli connection show" to get an overview on active connection profiles.')
    return 0


OBJECTS = {"general": cmd_general, "networking": cmd_networking, "radio": cmd_radio, "connection": cmd_connection,
           "device": cmd_device, "monitor": cmd_monitor, "portal": cmd_portal}


def parse_options(argv: list[str], opts: Options) -> list[str]:
    args = list(argv)
    while args and args[0].startswith("-") and args[0] != "-":
        flag = args.pop(0)
        if flag in ("-t", "--terse"):
            opts.terse = True
        elif flag in ("-p", "--pretty"):
            pass
        elif flag in ("-f", "--fields"):
            opts.fields = args.pop(0).split(",")
        elif flag in ("-g", "--get-values"):
            opts.fields = args.pop(0).split(",")
            opts.terse = opts.get_values = True
        elif flag in ("-m", "--mode"):
            opts.mode = args.pop(0)
        elif flag in ("-e", "--escape"):
            opts.escape = args.pop(0) != "no"
        elif flag in ("-c", "--colors"):
            args.pop(0)
        elif flag in ("-a", "--ask"):
            opts.ask = True
        elif flag in ("-s", "--show-secrets"):
            opts.show_secrets = True
        elif flag in ("-w", "--wait"):
            opts.wait = float(args.pop(0))
        elif flag in ("-v", "--version"):
            print(f"nmxcli tool, version {__version__}")
            raise SystemExit(0)
        elif flag in ("-h", "--help"):
            print(__doc__)
            raise SystemExit(0)
        else:
            raise Usage(f"Option '{flag}' is unknown, try 'nmxcli -h'.")
    return args


def main(argv: list[str] | None = None) -> int:
    opts = Options()
    raw = sys.argv[1:] if argv is None else argv
    if raw[:1] == ["--internal"]:
        # The sleep hook, the package's scripts and the unit: suspend, resume, reexec, exit (root).
        try:
            reply = client.request({"op": raw[1] if len(raw) > 1 else ""}, timeout=60)
        except client.NotRunning:
            return 8
        return 0 if reply.get("ok") else 1
    try:
        args = parse_options(sys.argv[1:] if argv is None else argv, opts)
        if not args:
            return overview(opts)
        if args[0] in ("help", "--help"):
            print(__doc__)
            return 0
        obj = pick(args.pop(0), list(OBJECTS))
        if args and args[0] in ("help", "--help", "-h"):
            print(__doc__)
            return 0
        return OBJECTS[obj](args, opts)
    except Usage as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2
    except client.NotRunning:
        print("Error: nmx is not running (sudo systemctl start nmx).", file=sys.stderr)
        return 8
    except Failed as failed:
        reply = failed.reply
        message = reply.get("error", "failed")
        if reply.get("code") == "secrets":
            need = reply.get("need", ["password"])
            message = f"Connection activation failed: Secrets were required, but not provided ({' and '.join(need)} needed)."
            if reply.get("security"):
                message += f" The network is {reply['security']}."
        print(f"Error: {message}", file=sys.stderr)
        return EXIT.get(reply.get("code", ""), 1)
    except KeyboardInterrupt:
        return 130
