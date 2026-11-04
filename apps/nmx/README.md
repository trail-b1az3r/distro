# nmx

Nexora's own network manager, the alternative to NetworkManager. **nmxd** keeps Wi-Fi and Ethernet connected;
**nmxcli** controls it with nmcli's commands; **nmxtui** is its terminal interface, like nmtui.

It is opt-in: the installer asks (Network manager: networkmanager or nmx), and on an installed system

```sh
sudo systemctl enable --now nmx       # switch: NetworkManager's saved networks come over, DNS goes through
                                      # systemd-resolved, NetworkManager is turned off (once)
sudo nmxcli device unmanage && sudo systemctl enable --now NetworkManager   # and back
```

```sh
nmxcli                                   # overview
nmxcli device wifi list                  # networks in range, with what each needs
nmxcli device wifi connect Home          # asks for the password if it needs one
nmxcli device wifi connect eduroam       # asks for the username and the password
nmxcli -a connection up Office           # --ask: prompts for missing secrets
nmxcli device status / device show wlan0 / connection show / radio wifi off / general
sudo nmxcli device unmanage wlan0        # the only way to take a device away from nmx
sudo nmxcli device manage wlan0          # and back
nmxtui                                   # menus
```

## How it works

- **Wi-Fi**: one wpa_supplicant per card, driven over its control socket. Networks are handed to it over the
  socket, so passwords never touch a wpa_supplicant config file.
- **Addressing**: systemd-networkd (DHCP, IPv6 router advertisements, static addresses) from one runtime `.network`
  file per device; **DNS** through systemd-resolved.
- **Saved connections**: `/etc/nmx/connections/*.nmx`, readable by root only, in NetworkManager's keyfile layout:
  nmcli property names (`wifi-sec.psk`, `802-1x.identity`, `ipv4.addresses`...) work in `connection add` and
  `connection modify`. NetworkManager's saved connections are imported on the first start (and with
  `nmxcli connection import networkmanager`).
- **Control**: `/run/nmx/nmx.sock`. Anyone may look; members of `wheel` or `network` may connect and change things;
  only root may unmanage or manage a device.

## Staying connected

- `nmx.service` refuses `systemctl stop`, and is restarted if it is killed or crashes. A device stays managed until
  `sudo nmxcli device unmanage`; NetworkManager, when installed, is told to keep its hands off nmx's devices and gets
  an unmanaged one back.
- **Suspend**: the system-sleep hook stops the supplicants before sleep and brings every device back after it;
  nmxd also notices a sleep by itself (the boot clock jumps past the monotonic one). After resume it waits for the
  card, restarts its supplicant and reconnects; a card that does not come back gets its driver reloaded (Marvell
  mwifiex on the Surface Pro 3-6, some Realtek and Intel cards).
- A supplicant that dies is restarted; a card that stops returning scans is restarted, then its driver reloaded.
- A network that keeps failing is retried with a backoff (10 s to 5 min); one whose saved password is refused is not
  retried until it gets a new one, and Halcyon (or `nmxcli monitor`) is told.

## Captive portals

Hotel, airport, train and café Wi-Fi often wants you to sign in on a web page first. After every connection (and every
5 minutes) nmxd asks the network whether it is online:

1. If the network announces a portal (RFC 8910, DHCP option 114 or a router advertisement), systemd-networkd keeps its
   API URI and nmxd asks that API (RFC 8908, HTTPS only) whether you still have to sign in, and where.
2. Otherwise it fetches a plain-HTTP check page **without following redirects**: a portal that redirects (or answers
   511) gives its sign-in page in `Location`; one that answers with its own page has it read from a meta refresh, a
   script redirect or its form.

Connectivity is then `portal`, the `connectivity` event carries the sign-in URL, and nmxd checks every 15 seconds
until you are through (then `full`). Halcyon shows a "Sign in to this network" notification and button; elsewhere:

    nmxcli networking connectivity     # portal
    nmxcli portal                      # wlan0 wants you to sign in at: http://…
    nmxcli portal open                 # opens it in your browser
    nmxcli portal check                # check again now
    nmxtui                             # "Sign in to this network" is the first item

## Security detection

From the scan flags nmx tells apart open, Enhanced Open (OWE), WEP, WPA/WPA2 Personal, WPA2/WPA3 transition, WPA3
Personal (SAE, with protected management frames required), WPA2/WPA3 Enterprise and WPA3 Enterprise 192-bit, plus
fast transition (802.11r) and the SHA-256 AKMs; it joins with everything the network offers, so a saved WPA2
network that adds WPA3 is joined with WPA3. It asks for exactly what is needed: nothing, a password, or a username
and a password (or a certificate for EAP-TLS).

## Enterprise (802.1X) and certificates

- The outer identity is `anonymous@realm` (the username travels only inside the TLS tunnel).
- The server is checked against the system's certificate authorities. If the network uses its own CA, nmx pins the
  server's certificate on first use (SHA-256), says so with its fingerprint, and refuses a different one later
  (`nmxcli connection modify NAME nmx.server-cert ''` to trust a new one). The server's domain is learned on the
  first connection and checked after that.
- When the login is refused, nmx tries PEAP/MSCHAPv2, TTLS/PAP, TTLS/MSCHAPv2 and PEAP/GTC in turn, and keeps the
  one that works. `eap`, `phase2`, `ca-cert` (auto, system, none or a file), `domain`, `cert`, `key` and
  `key-password` on `device wifi connect` set them yourself.
