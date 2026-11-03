"""nmxtui: nmx in the terminal, like nmtui. Arrows move, Enter chooses, Esc or q goes back.

    nmxtui            the menu
    nmxtui connect    straight to the networks in range
    nmxtui edit [ID]  straight to the saved connections (or one of them)
    nmxtui hostname   set the system's name
"""

from __future__ import annotations

import curses
import sys

from . import client, security

WIDTH = 72


class Back(Exception):
    pass


def call(req: dict) -> dict:
    try:
        return client.request(req, timeout=150)
    except client.NotRunning:
        return {"ok": False, "error": "nmx is not running (sudo systemctl start nmx)"}


class App:
    def __init__(self, screen):
        self.s = screen
        curses.curs_set(0)
        curses.use_default_colors()
        if curses.has_colors():
            curses.init_pair(1, curses.COLOR_WHITE, curses.COLOR_BLUE)    # window
            curses.init_pair(2, curses.COLOR_BLACK, curses.COLOR_WHITE)   # selection
            curses.init_pair(3, curses.COLOR_RED, curses.COLOR_BLUE)      # errors
            curses.init_pair(4, curses.COLOR_CYAN, curses.COLOR_BLUE)     # notes
        self.s.bkgd(" ", curses.color_pair(1))

    # ── drawing ──
    def frame(self, title: str, height: int):
        rows, cols = self.s.getmaxyx()
        h, w = min(height, rows - 2), min(WIDTH, cols - 2)
        y, x = max(0, (rows - h) // 2), max(0, (cols - w) // 2)
        self.s.erase()
        win = curses.newwin(h, w, y, x)
        win.bkgd(" ", curses.color_pair(1))
        win.box()
        win.addstr(0, max(1, (w - len(title) - 2) // 2), f" {title} ", curses.A_BOLD)
        self.s.noutrefresh()
        return win

    def message(self, title: str, text: str, error: bool = False) -> None:
        lines = wrap(text, WIDTH - 6)
        win = self.frame(title, len(lines) + 5)
        for i, line in enumerate(lines):
            win.addstr(2 + i, 3, line, curses.color_pair(3 if error else 1))
        win.addstr(len(lines) + 3, 3, "[ OK ]", curses.color_pair(2))
        win.refresh()
        win.getch()

    def menu(self, title: str, items: list[str], hint: str = "", selected: int = 0, keys: str = "") -> tuple[int, str]:
        """Returns (index, key): key is '\\n' for Enter or one of `keys`."""
        while True:
            _, cols = self.s.getmaxyx()
            height = min(len(items), self.s.getmaxyx()[0] - 8) + 5
            win = self.frame(title, height)
            visible = height - 5
            top = max(0, min(selected - visible // 2, len(items) - visible))
            for i, item in enumerate(items[top:top + visible]):
                attr = curses.color_pair(2) if top + i == selected else curses.color_pair(1)
                win.addstr(2 + i, 2, item[:WIDTH - 6].ljust(WIDTH - 6), attr)
            if hint:
                win.addstr(height - 2, 2, hint[:WIDTH - 6], curses.color_pair(4))
            win.keypad(True)
            win.refresh()
            key = win.getch()
            if key in (curses.KEY_UP, ord("k")) and items:
                selected = (selected - 1) % len(items)
            elif key in (curses.KEY_DOWN, ord("j")) and items:
                selected = (selected + 1) % len(items)
            elif key in (10, 13, curses.KEY_ENTER) and items:
                return selected, "\n"
            elif key in (27, ord("q")):
                raise Back
            elif 0 <= key < 256 and chr(key) in keys:
                return selected, chr(key)

    def form(self, title: str, fields: list[list], note: str = "") -> dict | None:
        """fields: [label, value, kind] with kind 'text', 'secret', or a list of choices. Enter on [Save] returns."""
        index = 0
        while True:
            win = self.frame(title, len(fields) + 7 + (1 if note else 0))
            win.keypad(True)
            for i, (label, value, kind) in enumerate(fields):
                shown = "*" * len(value) if kind == "secret" else value
                if isinstance(kind, list):
                    shown = f"< {value} >"
                attr = curses.color_pair(2) if i == index else curses.color_pair(1)
                win.addstr(2 + i, 2, f"{label:>20}  ")
                win.addstr(2 + i, 24, shown[:WIDTH - 28].ljust(WIDTH - 28), attr)
            save_row = len(fields) + 3
            win.addstr(save_row, 24, "[ Save ]", curses.color_pair(2) if index == len(fields) else curses.color_pair(1))
            win.addstr(save_row, 36, "[ Cancel ]", curses.color_pair(2) if index == len(fields) + 1 else curses.color_pair(1))
            if note:
                win.addstr(save_row + 2, 2, note[:WIDTH - 6], curses.color_pair(4))
            win.refresh()
            key = win.getch()
            if key in (curses.KEY_UP,):
                index = (index - 1) % (len(fields) + 2)
            elif key in (curses.KEY_DOWN, 9):
                index = (index + 1) % (len(fields) + 2)
            elif key == 27:
                return None
            elif index == len(fields) and key in (10, 13):
                return {f[0]: f[1] for f in fields}
            elif index == len(fields) + 1 and key in (10, 13):
                return None
            elif index < len(fields):
                label, value, kind = fields[index]
                if isinstance(kind, list):
                    if key in (curses.KEY_LEFT, curses.KEY_RIGHT, 10, 13, 32):
                        step = -1 if key == curses.KEY_LEFT else 1
                        fields[index][1] = kind[(kind.index(value) + step) % len(kind)] if value in kind else kind[0]
                elif key in (curses.KEY_BACKSPACE, 127, 8):
                    fields[index][1] = value[:-1]
                elif key in (10, 13):
                    index += 1
                elif 32 <= key < 0x110000:
                    fields[index][1] = value + chr(key)

    # ── screens ──
    def main_menu(self) -> None:
        items = ["Activate a connection", "Edit a connection", "Device management", "Set system hostname",
                 "Wi-Fi radio on / off", "Quit"]
        selected = 0
        while True:
            try:
                selected, _ = self.menu("nmx", items, "Enter: choose   q: quit", selected)
            except Back:
                return
            if selected == len(items) - 1:
                return
            try:
                [self.activate, self.edit_list, self.devices, self.hostname, self.radio][selected]()
            except Back:
                pass

    def activate(self) -> None:
        selected = 0
        rescan = "auto"
        while True:
            wifi = call({"op": "wifi-list", "rescan": rescan})
            rescan = "no"
            conns = call({"op": "connections"}).get("data", [])
            nets: dict[str, dict] = {}
            for ap in wifi.get("data", []):
                if ap["ssid"] and (ap["ssid"] not in nets or ap["in-use"] or ap["signal"] > nets[ap["ssid"]]["signal"]):
                    if not (ap["ssid"] in nets and nets[ap["ssid"]]["in-use"]):
                        nets[ap["ssid"]] = ap
            rows, actions = [], []
            for c in conns:
                if c["type"] == "ethernet":
                    rows.append(f"{'*' if c['active'] else ' '} {c['name']:<34} wired")
                    actions.append(("conn", c))
            for ap in sorted(nets.values(), key=lambda a: (not a["in-use"], -a["signal"])):
                bars = "".join(ch if ap["signal"] > t else "_" for ch, t in zip("▂▄▆█", (0, 25, 50, 75), strict=True))
                label = ap["security"] or "open"
                rows.append(f"{'*' if ap['in-use'] else ' '} {ap['ssid'][:34]:<34} {bars}  {label}{'  (saved)' if ap['saved'] else ''}")
                actions.append(("ap", ap))
            if not rows:
                rows, actions = ["(no networks found: r to scan again)"], [("none", {})]
            selected, key = self.menu("Activate a connection", rows, "Enter: connect / disconnect   r: rescan   q: back",
                                      min(selected, len(rows) - 1), keys="r")
            if key == "r":
                rescan = "yes"
                continue
            kind, item = actions[selected]
            if kind == "conn":
                op = "connection-down" if item["active"] else "connection-up"
                reply = call({"op": op, "id": item["uuid"]})
                if not reply.get("ok"):
                    self.message("Could not change the connection", reply.get("error", ""), error=True)
            elif kind == "ap":
                if item["in-use"]:
                    reply = call({"op": "connection-down", "id": item["ssid"]})
                else:
                    reply = self.connect(item)
                if reply is not None and not reply.get("ok"):
                    self.message("Could not connect", reply.get("error", ""), error=True)

    def connect(self, ap: dict) -> dict | None:
        req = {"op": "wifi-connect", "ssid": ap["ssid"], "wait": 90}
        for _ in range(3):
            self.frame(f"Connecting to {ap['ssid']}…", 5).refresh()
            reply = call(req)
            if reply.get("ok") or reply.get("code") != "secrets":
                return reply
            need = reply.get("need", ["password"])
            fields = []
            if "username" in need:
                fields.append(["Username", req.get("username", ""), "text"])
            if "password" in need:
                fields.append(["Password", "", "secret"])
            if "certificate" in need:
                fields += [["Certificate file", "", "text"], ["Key file", "", "text"], ["Key password", "", "secret"]]
            answers = self.form(ap["ssid"], fields, note=ap.get("describe") or reply.get("security", ""))
            if answers is None:
                return None
            req.update({"username": answers.get("Username", req.get("username", "")),
                        "password": answers.get("Password", ""),
                        **({"client-cert": answers["Certificate file"], "private-key": answers["Key file"] or answers["Certificate file"],
                            "private-key-password": answers["Key password"]} if "Certificate file" in answers else {})})
        return call(req)

    def edit_list(self, only: str = "") -> None:
        selected = 0
        while True:
            conns = call({"op": "connections"}).get("data", [])
            if only:
                match = [c for c in conns if only in (c["name"], c["uuid"], c["ssid"])]
                if match:
                    self.edit(match[0]["uuid"])
                return
            rows = [f"{c['name'][:40]:<40} {c['type']:<9} {'auto' if c['autoconnect'] else ''}" for c in conns]
            rows.append("<Add a connection>")
            selected, key = self.menu("Edit a connection", rows, "Enter: edit   d: delete   q: back",
                                      min(selected, len(rows) - 1), keys="d")
            if selected == len(conns):
                self.add()
            elif key == "d":
                reply = call({"op": "connection-delete", "id": conns[selected]["uuid"]})
                if not reply.get("ok"):
                    self.message("Could not delete", reply.get("error", ""), error=True)
            else:
                self.edit(conns[selected]["uuid"])

    def add(self) -> None:
        answers = self.form("Add a connection", [["Type", "wifi", ["wifi", "ethernet"]], ["Name", "", "text"],
                                                 ["SSID", "", "text"]])
        if answers:
            props = {"type": answers["Type"], "con-name": answers["Name"] or answers["SSID"] or answers["Type"]}
            if answers["Type"] == "wifi":
                props["ssid"] = answers["SSID"] or answers["Name"]
            reply = call({"op": "connection-add", "props": props})
            if not reply.get("ok"):
                self.message("Could not add", reply.get("error", ""), error=True)

    def edit(self, uuid: str) -> None:
        reply = call({"op": "connection-show", "id": uuid, "show-secrets": True})
        if not reply.get("ok"):
            self.message("Could not read the connection", reply.get("error", ""), error=True)
            return
        d = reply["data"]
        g = lambda s, k, default="": d.get(s, {}).get(k, default)  # noqa: E731
        kinds = ["open", "owe", "wep", "psk", "sae", "psk-sae", "eap"]
        kind = security.kind_from_key_mgmt(g("wifi-security", "key-mgmt"))
        fields = [["Name", g("connection", "id"), "text"],
                  ["Autoconnect", "yes" if g("connection", "autoconnect", "true") in ("true", "yes") else "no", ["yes", "no"]],
                  ["Priority", g("connection", "autoconnect-priority", "0"), "text"]]
        wifi = g("connection", "type") == "wifi"
        if wifi:
            fields += [["SSID", g("wifi", "ssid"), "text"],
                       ["Hidden", "yes" if g("wifi", "hidden") in ("true", "yes") else "no", ["no", "yes"]],
                       ["Security", kind if kind in kinds else "open", kinds],
                       ["Password", g("wifi-security", "psk") or g("802-1x", "password"), "secret"],
                       ["Username", g("802-1x", "identity"), "text"],
                       ["EAP method", g("802-1x", "eap", "peap"), ["peap", "ttls", "tls", "pwd"]],
                       ["Inner method", g("802-1x", "phase2-auth", "mschapv2"), ["mschapv2", "pap", "gtc", "chap"]],
                       ["CA certificate", g("802-1x", "ca-cert", "auto"), "text"]]
        fields += [["IPv4", g("ipv4", "method", "auto"), ["auto", "manual", "disabled"]],
                   ["Addresses", g("ipv4", "addresses"), "text"], ["Gateway", g("ipv4", "gateway"), "text"],
                   ["DNS servers", g("ipv4", "dns"), "text"]]
        answers = self.form(f"Edit {g('connection', 'id')}", fields,
                            note="CA certificate: auto (system CAs, then the network's own, pinned), system, none or a file")
        if not answers:
            return
        props = {"connection.id": answers["Name"], "connection.autoconnect": answers["Autoconnect"],
                 "connection.autoconnect-priority": answers["Priority"], "ipv4.method": answers["IPv4"],
                 "ipv4.addresses": answers["Addresses"], "ipv4.gateway": answers["Gateway"], "ipv4.dns": answers["DNS servers"]}
        if wifi:
            props.update({"wifi.ssid": answers["SSID"], "wifi.hidden": answers["Hidden"],
                          "wifi-security.key-mgmt": security.key_mgmt_for_kind(answers["Security"])})
            if answers["Security"] == "eap":
                props.update({"802-1x.identity": answers["Username"], "802-1x.password": answers["Password"],
                              "802-1x.eap": answers["EAP method"], "802-1x.phase2-auth": answers["Inner method"],
                              "802-1x.ca-cert": answers["CA certificate"]})
            elif answers["Security"] == "wep":
                props["wifi-security.wep-key0"] = answers["Password"]
            elif answers["Security"] != "open":
                props["wifi-security.psk"] = answers["Password"]
        reply = call({"op": "connection-modify", "id": uuid, "props": props})
        if not reply.get("ok"):
            self.message("Could not save", reply.get("error", ""), error=True)

    def devices(self) -> None:
        selected = 0
        while True:
            rows_data = [r for r in call({"op": "devices"}).get("data", []) if r["type"] != "loopback"]
            rows = [f"{r['device']:<16} {r['type']:<9} {r['state']:<14} {'managed' if r['managed'] else 'UNMANAGED'}"
                    for r in rows_data] or ["(no devices)"]
            selected, key = self.menu("Device management", rows,
                                      "u: unmanage   m: manage   c: connect   x: disconnect   (manage/unmanage: root)",
                                      min(selected, len(rows) - 1), keys="umcx")
            if not rows_data:
                continue
            iface = rows_data[selected]["device"]
            op = {"u": "device-unmanage", "m": "device-manage", "c": "device-connect", "x": "device-disconnect",
                  "\n": "device-connect"}[key]
            reply = call({"op": op, "ifname": iface, "wait": 60})
            if not reply.get("ok"):
                self.message(iface, reply.get("error", ""), error=True)
            elif reply.get("message"):
                self.message(iface, reply["message"])

    def hostname(self) -> None:
        current = call({"op": "hostname"}).get("data", "")
        answers = self.form("Set system hostname", [["Hostname", current, "text"]])
        if answers and answers["Hostname"] != current:
            reply = call({"op": "hostname", "name": answers["Hostname"]})
            self.message("Hostname", f"Set to '{answers['Hostname']}'." if reply.get("ok") else reply.get("error", ""),
                         error=not reply.get("ok"))

    def radio(self) -> None:
        status = call({"op": "status"}).get("data", {})
        state = "off" if status.get("wifi") == "enabled" else "on"
        reply = call({"op": "radio", "wifi": state})
        self.message("Wi-Fi", f"Wi-Fi is {state}." if reply.get("ok") else reply.get("error", ""), error=not reply.get("ok"))


def wrap(text: str, width: int) -> list[str]:
    out = []
    for para in text.splitlines() or [""]:
        line = ""
        for word in para.split():
            if len(line) + len(word) + 1 > width:
                out.append(line)
                line = word
            else:
                line = f"{line} {word}".strip()
        out.append(line)
    return out


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    if not client.running():
        print("nmx is not running (sudo systemctl start nmx).", file=sys.stderr)
        return 8

    def run(screen):
        app = App(screen)
        try:
            if not argv:
                app.main_menu()
            elif argv[0] == "connect":
                app.activate()
            elif argv[0] == "edit":
                app.edit_list(argv[1] if len(argv) > 1 else "")
            elif argv[0] == "hostname":
                app.hostname()
        except (Back, SystemExit):
            pass

    curses.wrapper(run)
    return 0
