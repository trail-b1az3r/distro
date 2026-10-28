import { useEffect, useState } from "react";
import { Accordion } from "@heroui/react";
import {
  ArrowLeft, ArrowRight, Bot, Boxes, Cpu, Download, HardDrive, HeartPulse, Laptop, Monitor, Rocket,
  ShieldCheck, SquareTerminal, Tablet, Undo2, WifiOff,
} from "lucide-react";
import { cli, desktopUrl, name, prettyName } from "../brand";
import { useLatestRelease } from "../release";
import { HexLines, LinkButton, Nav, Terminal, TextLink } from "../components/ui";
import Install from "../components/Download";
import bootMenu from "../assets/boot-menu.jpg";
import redSun from "../../../desktop/dots/docs/assets/preview-red-sun.jpg";
import themes from "../../../desktop/dots/docs/assets/preview-themes.jpg";
import animeThemes from "../../../desktop/dots/docs/assets/preview-anime-themes.jpg";
import silence from "../../../desktop/dots/docs/assets/preview-silence.jpg";
import picker from "../../../desktop/dots/docs/assets/theme-picker.jpg";
import panels from "../../../desktop/dots/docs/assets/panels.jpg";

const wrap = "mx-auto max-w-6xl px-4 sm:px-6";

function HeroBox({ title, subtitle, action, children }) {
  return (
    <div className="rounded-[3px] bg-band-2/85 p-5 text-band-ink">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-3xl font-semibold">{title}</h2>
        {action}
      </div>
      <h3 className="mt-2 font-semibold">{subtitle}</h3>
      <p className="mt-1 text-[0.82rem] leading-relaxed text-band-ink/85">{children}</p>
    </div>
  );
}

function Hero() {
  const release = useLatestRelease();
  const tag = release.status === "ok" ? release.release.tag.replace(/^v/, "") : "";
  return (
    <section className="relative overflow-hidden bg-band">
      <HexLines />
      <Nav />
      <div className={`${wrap} relative grid items-center gap-10 pb-16 pt-8 sm:pt-12 lg:grid-cols-[1.45fr_1fr]`}>
        <div className="text-band-ink">
          <h1 className="text-5xl font-bold leading-[1.05] tracking-tight sm:text-[3.3rem]">
            Arch Linux
            <br />
            <span className="text-band-soft">without the homework.</span>
          </h1>
          <p className="mt-8 space-y-1 font-sans text-2xl font-semibold leading-snug sm:text-[1.7rem]">
            <span className="block">Detects your <span className="text-band-soft">hardware</span>.</span>
            <span className="block">Explains every <span className="text-band-soft">change</span>.</span>
            <span className="block">Phones <span className="text-band-soft">nobody</span> home.</span>
          </p>
        </div>
        <div className="space-y-3">
          <HeroBox title={name} subtitle="The distribution"
            action={<LinkButton to={{ pathname: "/", hash: "#install" }} kind="band"><Download size={15} /> Download {name} {tag}</LinkButton>}>
            Arch Linux and EndeavourOS packages with a graphical installer, a GPU manager that gets hybrid laptops right,
            recovery tools and Microsoft Surface support.
          </HeroBox>
          <HeroBox title="Halcyon" subtitle="The desktop"
            action={<LinkButton href={desktopUrl} kind="band"><Monitor size={15} /> Halcyon 2.0</LinkButton>}>
            Hyprland with the illogical-impulse shell, nine hand-made themes and a voice assistant. Installed as upstream
            ships it; your own settings load last.
          </HeroBox>
        </div>
      </div>
    </section>
  );
}

function Intro() {
  return (
    <section className={`${wrap} grid gap-12 py-20 lg:grid-cols-[1.15fr_1fr] [&>*]:min-w-0`}>
      <div>
        <h2 className="text-[1.75rem] font-semibold text-violet">Arch, minus the first weekend</h2>
        <div className="mt-5 space-y-4 text-[0.9rem] leading-7">
          <p>
            Arch is a fine base and a slow first weekend: drivers to pick, a boot loader to set up, a desktop to put
            together, and a wiki tab open for each. {name} does that weekend for you.
          </p>
          <p>
            The installer looks at the machine first. It finds the GPUs, the Wi-Fi card, the screen's pixel density and
            whatever Windows is already on the disk, and says what it will do about each before it writes anything.
          </p>
          <p>
            Then it stays out of the way. It is pacman and yay, the Halcyon desktop exactly as upstream ships it, and your{" "}
            <code>~/.config/hypr/custom</code> is never touched. When something does break, <code>{cli} doctor</code> says
            what and how to fix it.
          </p>
        </div>
      </div>
      <div className="lg:pt-12">
        <Terminal title={`${cli} doctor`} lines={[
          `${cli} doctor`,
          "→ System Doctor",
          "→ ✓ Kernel — linux 6.16.8",
          "→ ! GPU — Graphics driver not configured by the GPU manager",
          `→     fix: sudo ${cli} gpu configure`,
          `sudo ${cli} repair`,
        ]} />
        <p className="mt-3 text-xs text-muted">Every finding comes with its fix; repair shows the plan before it runs.</p>
      </div>
    </section>
  );
}

const SLIDES = [
  [redSun, "Red Sun", "Wallpaper: Eclipse by Alena Aenami"],
  [themes, "HyperNeo, Star Rail, Shattered Glass, Fractured Glass", "Each with its wallpaper, its revolver and Firefox in its colours"],
  [animeThemes, "After ICEY and Manga Ink", "Wallpapers by fw_storm and MotionBGs, not included"],
  [silence, "Silence", "Wallpaper from wallhaven, artist unknown; not included"],
  [panels, "The top bar and side panels", "In After ICEY, Manga Ink, Star Rail and Red Sun"],
  [picker, "The theme picker", "A card for each theme: wallpaper, colours and dock"],
  [bootMenu, `The ${prettyName} boot menu`, "The live ISO on a UEFI machine"],
];
const SLIDE_MS = 7000;

function Carousel() {
  const [at, setAt] = useState(0);
  const [paused, setPaused] = useState(() => window.matchMedia?.("(prefers-reduced-motion: reduce)").matches);
  const go = (d) => setAt((i) => (i + d + SLIDES.length) % SLIDES.length);
  useEffect(() => {
    if (paused) return undefined;
    const t = setTimeout(() => go(1), SLIDE_MS);
    return () => clearTimeout(t);
  }, [at, paused]);
  const [src, title, credit] = SLIDES[at];
  const arrow = "flex size-8 items-center justify-center rounded-[3px] border border-line bg-surface hover:border-ink/40";
  return (
    <section id="desktop" className="border-y border-line bg-paper-2 py-20">
      <div className={wrap}>
        <div className="flex items-end justify-between gap-6">
          <div>
            <h2 className="text-[1.75rem] font-semibold text-violet">See it in action</h2>
            <p className="mt-2 text-[0.9rem] text-muted">Halcyon, the desktop {name} installs, in a few of its nine themes.</p>
          </div>
          <div className="flex gap-2">
            <button type="button" className={arrow} onClick={() => go(-1)} aria-label="Previous screenshot"><ArrowLeft size={15} /></button>
            <button type="button" className={arrow} onClick={() => go(1)} aria-label="Next screenshot"><ArrowRight size={15} /></button>
          </div>
        </div>
        <figure className="relative mt-8 overflow-hidden rounded-[3px] bg-black"
          onMouseEnter={() => setPaused(true)} onMouseLeave={() => setPaused(false)}>
          <img key={src} src={src} alt={`${title}. ${credit}.`} className="aspect-video w-full object-cover" />
          <figcaption className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/75 to-transparent px-4 pb-3 pt-10 text-white">
            <span className="block font-sans text-sm font-semibold">{title}</span>
            <span className="block text-[0.72rem] text-white/70">{credit}</span>
          </figcaption>
        </figure>
        <div className="mt-3 flex gap-1.5" role="tablist" aria-label="Screenshots">
          {SLIDES.map(([, t], i) => (
            <button key={t} type="button" role="tab" aria-selected={i === at} aria-label={t} onClick={() => setAt(i)}
              className="relative h-1 flex-1 overflow-hidden rounded-full bg-line">
              {i < at && <span className="absolute inset-0 bg-teal" />}
              {i === at && (
                <span key={`${at}-${paused}`} className="absolute inset-y-0 left-0 bg-teal"
                  style={paused ? { width: "100%" } : { animation: `fill ${SLIDE_MS}ms linear forwards` }} />
              )}
            </button>
          ))}
        </div>
      </div>
      <style>{"@keyframes fill { from { width: 0 } to { width: 100% } }"}</style>
    </section>
  );
}

const HARDWARE = [
  [Monitor, "NVIDIA", "Open kernel modules on Turing and newer, the 580 legacy driver for Maxwell, Pascal and Volta, or nouveau if you prefer. Suspend works.", "/docs/gpu", "The GPU manager"],
  [Cpu, "AMD and Intel", "Mesa, Vulkan and video decoding out of the box, from old HD Graphics to Arc; ROCm for compute on cards that support it.", "/docs/gpu", "Drivers and compute"],
  [Laptop, "Hybrid laptops", "The integrated GPU runs the desktop and saves the battery; prime-run starts a game or a model on the other one.", "/docs/hardware", "What is detected"],
  [Tablet, "Microsoft Surface", "Recognised, with the linux-surface kernel offered for touch and pen. The 2017 Surface Pro gets its Wi-Fi firmware and a sensible scale.", "/docs/surface", "Surface guide"],
];

function Hardware() {
  return (
    <section id="hardware" className="border-y border-line bg-paper-2 py-20">
      <div className={wrap}>
        <h2 className="text-[1.75rem] font-semibold text-violet">It runs on the hardware you have</h2>
        <p className="mt-2 max-w-2xl text-[0.9rem] leading-7 text-muted">
          Before installing, you see what was found and what is recommended. You can change every recommendation, and
          nothing is forced on hardware it doesn't recognise.
        </p>
        <div className="mt-10 grid gap-x-8 gap-y-10 sm:grid-cols-2 lg:grid-cols-4">
          {HARDWARE.map(([Icon, title, text, to, more]) => (
            <div key={title} className="border-t border-line pt-5">
              <h3 className="flex items-center gap-2 font-semibold"><Icon size={17} className="text-teal" /> {title}</h3>
              <p className="mt-2 text-[0.82rem] leading-6 text-muted">{text}</p>
              <TextLink to={to} className="mt-4">{more}</TextLink>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

const FEATURES = [
  [Rocket, "Installer", <>UEFI or BIOS, <b>install next to Windows</b>, LUKS2, Btrfs or ext4, systemd-boot or GRUB. Nothing is written until you press Install.</>],
  [HeartPulse, "Recovery", <><b>{cli} doctor</b> finds problems, <b>{cli} repair</b> fixes them, and the live ISO can unlock and rescue an installed system.</>],
  [Undo2, "Snapshots", <>On Btrfs, a snapshot <b>before and after every pacman transaction</b>, bootable from the GRUB menu.</>],
  [ShieldCheck, "Secure Boot", <>Turn it back on after installing, <b>with your own keys</b>: the installer sets them up with sbctl.</>],
  [WifiOff, "Offline installs", <>A full ISO installs <b>with no network at all</b>; the standard one carries the distribution's own packages.</>],
  [HardDrive, "Nothing hidden", <><b>No telemetry</b> and no background services you didn't ask for. Commands that change the system show the plan first.</>],
];

function Features() {
  return (
    <section className={`${wrap} py-20`}>
      <h2 className="text-center text-[2rem] font-semibold text-violet">What it sets up for you</h2>
      <div className="mt-14 grid gap-x-10 gap-y-14 sm:grid-cols-2 lg:grid-cols-3">
        {FEATURES.map(([Icon, title, text]) => (
          <div key={title} className="text-center">
            <Icon size={44} strokeWidth={1.25} className="mx-auto text-violet" />
            <h3 className="mt-4 text-xl font-semibold text-violet">{title}</h3>
            <p className="mx-auto mt-2 max-w-xs text-[0.82rem] leading-6 [&_b]:font-semibold">{text}</p>
          </div>
        ))}
      </div>
    </section>
  );
}

const PROFILES = [
  ["Minimal", "Base system, desktop, networking and essential utilities."],
  ["Standard", "Everyday desktop with browser, office suite and developer utilities. The default."],
  ["Developer", "Standard plus editor, compilers, Rust, containers and Claude Code."],
  ["AI", "Developer plus HyperNix, an AI assistant, GPU acceleration and a local model."],
];

function Profiles() {
  return (
    <section className="border-y border-line bg-paper-2 py-20">
      <div className={wrap}>
        <h2 className="text-[1.75rem] font-semibold text-violet">Four starting points</h2>
        <p className="mt-2 max-w-2xl text-[0.9rem] leading-7 text-muted">
          Pick a profile, then switch any part of it on or off in the installer, or later with{" "}
          <code className="text-ink">{cli} install</code>.
        </p>
        <div className="mt-10 grid gap-x-8 gap-y-8 sm:grid-cols-2 lg:grid-cols-4">
          {PROFILES.map(([title, text]) => (
            <div key={title} className="border-t border-line pt-5">
              <h3 className="font-semibold">{title}</h3>
              <p className="mt-2 text-[0.82rem] leading-6 text-muted">{text}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

const AI = [
  [Bot, "Assistants", "Hermis (Hermes Agent by Nous Research), OpenClaw, both or none."],
  [Boxes, "HyperNix", "Chat, GGUF conversion, quantisation and training, with a PyTorch build that matches your GPU."],
  [SquareTerminal, "Claude Code", "Anthropic's coding agent, as claude in every shell."],
  [Cpu, "A local model server", "llama.cpp behind an OpenAI-compatible API, and a catalogue with honest size and memory figures."],
];

function Ai() {
  return (
    <section id="ai" className={`${wrap} grid gap-12 py-20 lg:grid-cols-[1.15fr_1fr] [&>*]:min-w-0`}>
      <div>
        <h2 className="text-[1.75rem] font-semibold text-violet">Local AI, if you want it</h2>
        <p className="mt-2 text-[0.9rem] leading-7 text-muted">
          None of it is installed unless you choose it. When you do, it is built for the GPU you have.
        </p>
        <div className="mt-8 grid gap-x-8 gap-y-6 sm:grid-cols-2">
          {AI.map(([Icon, title, text]) => (
            <div key={title} className="border-t border-line pt-4">
              <h3 className="flex items-center gap-2 font-semibold"><Icon size={16} className="text-teal" /> {title}</h3>
              <p className="mt-1.5 text-[0.82rem] leading-6 text-muted">{text}</p>
            </div>
          ))}
        </div>
        <TextLink to="/docs/ai" className="mt-8">AI assistants and models</TextLink>
      </div>
      <div className="lg:pt-14">
        <Terminal title="local models" lines={[
          `${cli} model recommend`,
          "# sizes and memory first; nothing large downloads without asking",
          `${cli} model install <name>`,
          `${cli} model serve`,
        ]} />
      </div>
    </section>
  );
}

const FAQ = [
  ["Does it boot with Secure Boot on?",
    "Not the ISO: its boot loader isn't signed by Microsoft. Turn Secure Boot off in the firmware (the boot menu's Firmware settings entry takes you there). After installing, the installer can set up your own keys with sbctl so it can go back on."],
  ["My Surface starts Windows instead of the stick.",
    "Secure Boot is still on, or USB boot is off. In Surface UEFI (hold Volume Up, press Power) set Secure Boot to None, then hold Volume Down and press Power with the stick in."],
  ["Why does the ISO come in parts?",
    "GitHub limits release files to 2 GiB. Download every part and join them (cat on Linux and macOS, copy /b on Windows), then check the SHA-256."],
  ["Can I keep Windows?",
    "Yes: choose Install alongside. It shrinks a partition you pick and puts both systems in the boot menu."],
  ["Do I need the internet to install?",
    "With the standard ISO, for Arch's own packages, yes. An ISO built with --offline full installs with no network at all; the installer tells you which you have."],
];

function Faq() {
  return (
    <section className="border-t border-line bg-paper-2 py-20">
      <div className={`${wrap} grid gap-10 lg:grid-cols-[1fr_2fr]`}>
        <div>
          <h2 className="text-[1.75rem] font-semibold text-violet">Before you install</h2>
          <p className="mt-2 text-[0.9rem] text-muted">The questions that come up most.</p>
          <TextLink to="/docs/troubleshooting" className="mt-6">Troubleshooting</TextLink>
        </div>
        <Accordion className="box">
          {FAQ.map(([q, a], i) => (
            <Accordion.Item key={q} id={`faq-${i}`}>
              <Accordion.Heading>
                <Accordion.Trigger className="text-left font-sans font-medium">
                  {q}
                  <Accordion.Indicator />
                </Accordion.Trigger>
              </Accordion.Heading>
              <Accordion.Panel>
                <Accordion.Body className="text-[0.82rem] leading-6 text-muted">{a}</Accordion.Body>
              </Accordion.Panel>
            </Accordion.Item>
          ))}
        </Accordion>
      </div>
    </section>
  );
}

export default function Home() {
  return (
    <>
      <Hero />
      <Intro />
      <Carousel />
      <Install />
      <Hardware />
      <Features />
      <Profiles />
      <Ai />
      <Faq />
    </>
  );
}

