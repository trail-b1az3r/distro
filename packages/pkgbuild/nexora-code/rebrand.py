#!/usr/bin/env python3
"""Make VSCodium's product.json the distribution's editor's: its own name (so its own settings folder,
~/.config/<name>), its own extensions folder (~/.<id>), URL scheme and icon. VSCodium's own update check is off
(pacman updates it), and the Open VSX marketplace stays.

    rebrand.py PRODUCT_JSON "Nexora Code" nexora-code
"""
import json
import sys

path, name, ident = sys.argv[1:4]
with open(path) as f:
    product = json.load(f)
product.update({
    "nameShort": name,
    "nameLong": name,
    "dataFolderName": f".{ident}",
    "serverDataFolderName": f".{ident}-server",
    "urlProtocol": ident,
    "linuxIconName": ident,
    "applicationName": "codium",  # the executable is still called codium
    "reportIssueUrl": "https://github.com/trail-b1az3r/distro/issues/new",
})
for key in ("updateUrl", "downloadUrl", "commit_update"):
    product.pop(key, None)
with open(path, "w") as f:
    json.dump(product, f, indent=2)
    f.write("\n")
