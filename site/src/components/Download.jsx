import { useState } from "react";
import { Download, HardDrive, MonitorPlay } from "lucide-react";
import { name, releasesUrl } from "../brand";
import { formatDate, formatSize, useLatestRelease } from "../release";
import { LinkButton, Terminal, TextLink } from "./ui";

/** How to join a split ISO, for the visitor's system. */
function Join({ release }) {
  const iso = release.iso;
  const guess = /Win/.test(navigator.userAgent) ? "Windows" : /Mac/.test(navigator.userAgent) ? "macOS" : "Linux";
  const [os, setOs] = useState(guess);
  const lines = {
    Windows: [`copy /b ${release.parts.map((p) => p.name).join(" + ")} ${iso}`, `certutil -hashfile ${iso} SHA256`],
    Linux: [`cat ${iso}.part-* > ${iso}`, `sha256sum -c ${iso}.sha256`],
    macOS: [`cat ${iso}.part-* > ${iso}`, `shasum -a 256 -c ${iso}.sha256`],
  }[os];
  return (
    <div className="mt-5">
      <p className="text-[0.78rem] leading-6 text-muted">
        GitHub takes files up to 2 GiB, so the ISO comes in {release.parts.length} parts. Put them in one folder and join
        them, on{" "}
        {["Windows", "Linux", "macOS"].map((o, i) => (
          <span key={o}>
            {i > 0 && (i === 2 ? " or " : ", ")}
            <button type="button" onClick={() => setOs(o)}
              className={`underline underline-offset-4 ${o === os ? "text-ink decoration-teal" : "decoration-line hover:text-ink"}`}>
              {o}
            </button>
          </span>
        ))}
        :
      </p>
      <Terminal className="mt-3" lines={lines} />
    </div>
  );
}

function Full({ state }) {
  const box = "box p-6";
  if (state.status !== "ok") {
    return (
      <div className={box}>
        <h3 className="flex items-center gap-2 font-sans text-lg font-medium"><HardDrive size={17} className="text-teal" /> Full-disk or dual-boot installation</h3>
        <p className="mt-3 text-[0.82rem] leading-6 text-muted">
          {state.status === "loading"
            ? "Looking up the newest release…"
            : "The newest release couldn't be loaded from here. Every release is on GitHub, and the ISO also builds on any Linux with Docker or Podman."}
        </p>
        <div className="mt-5 flex flex-wrap gap-3">
          <LinkButton href={releasesUrl}><Download size={15} /> Releases on GitHub</LinkButton>
        </div>
        <Terminal className="mt-5" title="or build it" lines={["./build.sh --container", "→ dist/*.iso, checksums/, metadata/"]} />
      </div>
    );
  }
  const r = state.release;
  return (
    <div className={box}>
      <h3 className="flex items-center gap-2 font-sans text-lg font-medium"><HardDrive size={17} className="text-teal" /> Full-disk or dual-boot installation</h3>
      <p className="mt-3 text-[0.82rem] leading-6 text-muted">
        Write the ISO to a USB stick, start from it, and answer the installer's questions. It can erase the disk, install
        next to Windows, or use partitions you made.
      </p>
      <div className="mt-5 flex flex-wrap gap-2">
        {r.parts.map((p, i) => (
          <LinkButton key={p.name} href={p.url} kind={i === 0 ? "primary" : "outline"}>
            <Download size={15} />
            {r.split ? `Part ${i + 1} of ${r.parts.length}` : `Download ${r.title}`}
          </LinkButton>
        ))}
      </div>
      <p className="mt-3 text-[0.74rem] leading-5 text-muted">
        {r.title}, {formatSize(r.size)}, released {formatDate(r.published)}.{" "}
        Verify the file: {r.sha256Url ? <a className="underline underline-offset-4" href={r.sha256Url}>SHA-256</a> : "SHA-256"},{" "}
        <a className="underline underline-offset-4" href={r.url} target="_blank" rel="noreferrer">release notes</a>.
      </p>
      {r.split && <Join release={r} />}
    </div>
  );
}

export default function Install() {
  const state = useLatestRelease();
  return (
    <section id="install" className="py-20">
      <div className="mx-auto max-w-6xl px-4 sm:px-6">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h2 className="text-[1.75rem] font-semibold text-violet">Install {name}</h2>
            <p className="mt-2 max-w-xl text-[0.9rem] leading-7 text-muted">
              One ISO for UEFI and older BIOS machines. It starts a live desktop with the installer, and nothing is written
              to the disk until you press Install.
            </p>
          </div>
          <TextLink to="/docs/installation">Full installation guide</TextLink>
        </div>
        <div className="mt-10 grid gap-5 lg:grid-cols-2 [&>*]:min-w-0">
          <Full state={state} />
          <div className="box p-6">
            <h3 className="flex items-center gap-2 font-sans text-lg font-medium"><MonitorPlay size={17} className="text-teal" /> Try it first</h3>
            <p className="mt-3 text-[0.82rem] leading-6 text-muted">
              The live system runs from the stick without touching the disk: try the desktop, check the Wi-Fi and the
              graphics, then decide. Or start the ISO in a virtual machine:
            </p>
            <Terminal className="mt-5" lines={[
              "qemu-img create -f qcow2 disk.qcow2 40G",
              `qemu-system-x86_64 -enable-kvm -m 4G -smp 2 -cdrom ${name}-*.iso \\`,
              "  -drive file=disk.qcow2,if=virtio -vga virtio",
            ]} />
            <p className="mt-4 text-[0.74rem] leading-5 text-muted">
              Write the stick with Rufus (either mode), balenaEtcher, Ventoy or dd. Turn Secure Boot off first.
            </p>
          </div>
        </div>
        <p className="mt-6 text-[0.78rem] text-muted">
          The guide also covers <TextLink to="/docs/surface">Microsoft Surface</TextLink>{" "}and{" "}
          <TextLink to="/docs/installation">unattended installs</TextLink>.
        </p>
      </div>
    </section>
  );
}
