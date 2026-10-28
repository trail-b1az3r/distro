import { useEffect, useState } from "react";
import { Link, NavLink } from "react-router";
import { ArrowRight, BookOpen, Check, Copy, Cpu, Download, Menu, Monitor, Moon, Sun, X } from "lucide-react";
import { conf, logoUrl, prettyName, repoUrl } from "../brand";

/** GitHub's mark, for links to the source (lucide no longer ships brand icons). */
export function GithubIcon({ size = 17 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <path d="M12 .5A11.5 11.5 0 0 0 .5 12a11.5 11.5 0 0 0 7.86 10.92c.58.1.79-.25.79-.56v-2c-3.2.7-3.87-1.37-3.87-1.37-.53-1.33-1.29-1.69-1.29-1.69-1.05-.72.08-.7.08-.7 1.16.08 1.77 1.19 1.77 1.19 1.03 1.77 2.71 1.26 3.37.96.1-.75.4-1.26.73-1.55-2.55-.29-5.24-1.28-5.24-5.68 0-1.25.45-2.28 1.19-3.08-.12-.29-.52-1.46.11-3.04 0 0 .97-.31 3.17 1.18a11 11 0 0 1 5.77 0c2.2-1.49 3.17-1.18 3.17-1.18.63 1.58.23 2.75.11 3.04.74.8 1.19 1.83 1.19 3.08 0 4.41-2.69 5.38-5.26 5.67.41.36.78 1.06.78 2.14v3.17c0 .31.21.67.8.56A11.5 11.5 0 0 0 23.5 12 11.5 11.5 0 0 0 12 .5Z" />
    </svg>
  );
}

export function Logo({ size = 30 }) {
  return (
    <span className="inline-flex items-center gap-2.5">
      <img src={logoUrl} width={size} height={size} alt="" className="shrink-0" />
      <span className="font-sans text-xl font-semibold tracking-tight">{prettyName}</span>
    </span>
  );
}

/** A flat button that is a link: to= for pages of this site, href= otherwise. */
export function LinkButton({ href, to, kind = "primary", className = "", children, ...rest }) {
  const cls = `btn btn-${kind} ${className}`;
  if (to) return <Link to={to} className={cls} {...rest}>{children}</Link>;
  const external = /^https?:/.test(href || "");
  return (
    <a href={href} className={cls} {...(external ? { target: "_blank", rel: "noreferrer" } : {})} {...rest}>
      {children}
    </a>
  );
}

/** An underlined link with an arrow. */
export function TextLink({ href, to, children, className = "" }) {
  const body = <>{children} <ArrowRight size={14} /></>;
  if (to) return <Link to={to} className={`text-link ${className}`}>{body}</Link>;
  return <a href={href} target="_blank" rel="noreferrer" className={`text-link ${className}`}>{body}</a>;
}

function useTheme() {
  const [dark, setDark] = useState(() => document.documentElement.classList.contains("dark"));
  useEffect(() => {
    const root = document.documentElement;
    root.classList.toggle("dark", dark);
    root.dataset.theme = dark ? "dark" : "light";
    try {
      localStorage.setItem("theme", dark ? "dark" : "light");
    } catch {
      /* the choice just isn't remembered */
    }
  }, [dark]);
  return [dark, setDark];
}

/** Big hexagon outlines, the logo's shape, drawn into the band like NixOS's lambdas. */
export function HexLines() {
  const hex = (cx, cy, r) =>
    Array.from({ length: 6 }, (_, i) => {
      const a = (Math.PI / 180) * (60 * i - 90);
      return `${(cx + r * Math.cos(a)).toFixed(1)},${(cy + r * Math.sin(a)).toFixed(1)}`;
    }).join(" ");
  return (
    <svg className="pointer-events-none absolute inset-0 h-full w-full" viewBox="0 0 1440 640" preserveAspectRatio="xMidYMid slice"
      aria-hidden="true" fill="none" stroke="currentColor">
      <g className="text-white/[0.07]" strokeWidth="2">
        <polygon points={hex(150, 560, 330)} />
        <polygon points={hex(150, 560, 250)} />
        <polygon points={hex(150, 560, 170)} />
        <polygon points={hex(1330, 40, 260)} />
        <polygon points={hex(1330, 40, 180)} />
        <line x1="560" y1="660" x2="980" y2="-20" />
        <line x1="620" y1="660" x2="1040" y2="-20" />
      </g>
    </svg>
  );
}

const TILES = [
  [Download, "Download", { pathname: "/", hash: "#install" }],
  [Monitor, "Desktop", { pathname: "/", hash: "#desktop" }],
  [Cpu, "Hardware", { pathname: "/", hash: "#hardware" }],
  [BookOpen, "Docs", "/docs"],
];

/** The violet band's top row: logo, and the NixOS-style icon tiles. */
export function Nav() {
  const [open, setOpen] = useState(false);
  const [dark, setDark] = useTheme();
  const tile = "flex flex-col items-center gap-1 rounded-[3px] bg-band-2/70 px-4 py-2 text-[0.72rem] text-band-ink/90 transition-colors hover:bg-band-2";
  const tiles = (
    <>
      {TILES.map(([Icon, label, to]) =>
        typeof to === "string" ? (
          <NavLink key={label} to={to} className={tile} onClick={() => setOpen(false)}>
            <Icon size={16} /> {label}
          </NavLink>
        ) : (
          <Link key={label} to={to} className={tile} onClick={() => setOpen(false)}>
            <Icon size={16} /> {label}
          </Link>
        ),
      )}
      <a href={repoUrl} target="_blank" rel="noreferrer" className={tile}>
        <GithubIcon size={16} /> Source
      </a>
      <button type="button" className={tile} onClick={() => setDark(!dark)}
        aria-label={dark ? "Switch to the light theme" : "Switch to the dark theme"}>
        {dark ? <Sun size={16} /> : <Moon size={16} />} {dark ? "Light" : "Dark"}
      </button>
    </>
  );
  return (
    <header className="relative z-10 text-band-ink">
      <nav className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-4 py-4 sm:px-6">
        <Link to="/" aria-label={`${prettyName} home`} onClick={() => setOpen(false)}>
          <Logo />
        </Link>
        <div className="hidden items-stretch gap-2 md:flex">{tiles}</div>
        <button type="button" className="rounded-[3px] bg-band-2/70 p-2 md:hidden" aria-expanded={open}
          aria-label={open ? "Close the menu" : "Open the menu"} onClick={() => setOpen(!open)}>
          {open ? <X size={20} /> : <Menu size={20} />}
        </button>
      </nav>
      {open && <div className="mx-4 mb-4 grid grid-cols-3 gap-2 md:hidden">{tiles}</div>}
    </header>
  );
}

/** The violet band on pages other than the home page. */
export function PageBand({ children }) {
  return (
    <section className="relative overflow-hidden bg-band">
      <HexLines />
      <Nav />
      {children && <div className="relative mx-auto max-w-6xl px-4 pb-8 pt-2 text-band-ink sm:px-6">{children}</div>}
    </section>
  );
}

/** Commands, with a copy button. Lines starting with "→" are output, "#" comments,
 *  two spaces a continued command. */
export function Terminal({ lines, title, className = "" }) {
  const [copied, setCopied] = useState(false);
  const commands = lines.filter((l) => !l.startsWith("#") && !l.startsWith("→")).join("\n");
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(commands);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* the text can still be selected */
    }
  };
  return (
    <div className={`relative rounded-[3px] bg-[var(--code-bg)] text-[var(--code-fg)] ${className}`}>
      {title && <p className="border-b border-white/10 px-4 py-2 text-xs text-white/45">{title}</p>}
      <button type="button" onClick={copy} aria-label="Copy the commands"
        className="absolute right-2 top-2 rounded-[3px] p-1.5 text-white/45 hover:bg-white/10 hover:text-white">
        {copied ? <Check size={14} /> : <Copy size={14} />}
      </button>
      <pre className="overflow-x-auto px-4 py-3.5 pr-10 text-[0.8rem] leading-relaxed">
        {lines.map((l, i) => (
          <div key={i} className={l.startsWith("#") ? "whitespace-pre-wrap text-white/40" : l.startsWith("→") ? "whitespace-pre-wrap text-white/70" : ""}>
            {l.startsWith("→") ? l.slice(1).trimStart() : l.startsWith("#") || l.startsWith("  ") ? l : <><span className="select-none text-band-soft">$ </span>{l}</>}
          </div>
        ))}
      </pre>
    </div>
  );
}

const COLUMNS = [
  ["The project", [["Download", { pathname: "/", hash: "#install" }], ["Documentation", "/docs"], ["Release process", "/docs/release-process"]]],
  ["Using it", [["Installation", "/docs/installation"], ["Microsoft Surface", "/docs/surface"], ["Troubleshooting", "/docs/troubleshooting"]]],
  ["Building it", [["Building the ISO", "/docs/iso-building"], ["Customizing", "/docs/customizing"], ["Contributing", "/docs/contributing"]]],
];

export function Footer() {
  const a = "block border-b border-white/10 py-1.5 text-sm text-white/75 hover:text-white";
  return (
    <footer className="bg-[#161a33] text-white dark:bg-[#07080f]">
      <div className="mx-auto grid max-w-6xl gap-10 px-4 py-14 sm:grid-cols-2 sm:px-6 lg:grid-cols-4">
        {COLUMNS.map(([title, links]) => (
          <div key={title}>
            <h3 className="mb-3 text-lg font-semibold">{title}</h3>
            {links.map(([label, to]) => <Link key={label} to={to} className={a}>{label}</Link>)}
          </div>
        ))}
        <div>
          <h3 className="mb-3 text-lg font-semibold">Get in touch</h3>
          <a className={a} href={conf.DISTRO_SUPPORT_URL} target="_blank" rel="noreferrer">Discussions</a>
          <a className={a} href={conf.DISTRO_BUG_URL} target="_blank" rel="noreferrer">Report a bug</a>
          <a className={a} href={repoUrl} target="_blank" rel="noreferrer">Source code</a>
        </div>
      </div>
      <div className="border-t border-white/10">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-4 px-4 py-6 text-xs text-white/50 sm:px-6">
          <span className="inline-flex items-center gap-2"><img src={logoUrl} width="18" height="18" alt="" /> {prettyName}, GPL-3.0-or-later</span>
          <span>Built on Arch Linux and EndeavourOS; not affiliated with either.</span>
        </div>
      </div>
    </footer>
  );
}
