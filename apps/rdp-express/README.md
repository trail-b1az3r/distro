# rdp-express: Frontline's remote desktop server

rdp-express shares your Wayland desktop (Hyprland, sway or another wlroots compositor) with frontline-msg's remote
desktop viewer on another computer. It works on your local network and, by default, over Tailscale. It has its own
protocol, built to be fast: only the parts of the screen that changed are sent, as JPEG, and only as fast as the
viewer takes them. Your pointer, wheel and keys go back the other way.

    sudo pacman -S frontline-rdp-express
    systemctl --user enable --now rdp-express   # share this desktop while you are logged in
    rdp-express pair                            # a one-time code for a new viewer

On the other computer, open Messages, click the remote-desktop button, pick this computer and enter the code. The
next time it connects without one.

    rdp-express serve [--port 47801] [--listen ADDR]... [--any] [--output NAME] [--quality 10-95] [--fps 1-60]
    rdp-express pair [--minutes 10]     # valid for 10 minutes, once; 5 wrong tries end it
    rdp-express clients                 # the viewers allowed in
    rdp-express revoke NAME             # and taking one out
    rdp-express outputs                 # the monitors (pick one with --output)
    rdp-express snapshot FILE.ppm       # one picture, to check that sharing works here

## Where it listens

By default it listens only on this machine (127.0.0.1) and on its Tailscale addresses (`tailscale ip`). That makes
it reachable from your tailnet and nowhere else, so it is never exposed on a café's Wi-Fi. `--listen ADDR` adds
addresses, and `--any` listens everywhere (your LAN). Only one viewer is connected at a time.

## The protocol

TCP, port 47801. Frames are a 4-byte big-endian length followed by the payload.

1. **Hello.** The viewer and the server exchange hellos in the clear: each sends its X25519 public key and a
   16-byte nonce.
2. **Encryption.** Everything after the hellos is ChaCha20-Poly1305, with a nonce made of a direction ("C2S\0" or
   "S2C\0") and a counter, so a replayed, reordered or altered frame is refused.
3. **The key.** For a viewer the server knows, the key is HKDF-SHA256(shared secret, salt = both nonces, info
   "rdp-express v1 key"). For a new viewer, the pairing code is mixed into the input with info "rdp-express v1
   pair". A wrong code, or anyone in the middle, fails the first frame's check, and only then is the viewer's key
   remembered (`~/.config/rdp-express/clients.json`).
4. **Messages.** The first byte of each message is its type:
   - From the server:
     - `1` hello: JSON with the output's name and size, and whether input is possible.
     - `2` a frame: number, size, then rectangles (x, y, w, h and the JPEG of each).
     - `3` an error.
   - From the viewer:
     - `0x10` its hello.
     - `0x11` the pointer's position, in screen pixels.
     - `0x12` a button.
     - `0x13` the wheel, in notches.
     - `0x14` a key, by its Linux key code.
     - `0x15` acknowledging a frame.
     - `0x16` settings: quality, frame rate.
     - `0x17` asking for a whole new frame.

The server sends a new frame only when the screen changed, the viewer is at most two frames behind, and the frame
rate allows it. A still screen costs nothing, and a slow link gets fewer frames rather than a growing delay.

## What it uses

- **Pictures:** the wlr-screencopy protocol, with the cursor drawn in. The compositor answers when it next draws
  the output.
- **Pointer:** wlr-virtual-pointer, for absolute moves on the shared output.
- **Keyboard:** the virtual keyboard protocol, with the seat's own keyboard layout, or the system default from
  `xkbcli` when no keyboard is attached.

GNOME and KDE Plasma have none of these protocols, so rdp-express needs Hyprland, sway or another wlroots
compositor.
