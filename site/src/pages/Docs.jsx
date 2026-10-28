import { useEffect, useMemo, useState } from "react";
import { Link, useLocation, useParams } from "react-router";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeSlug from "rehype-slug";
import { ArrowLeft, ArrowRight, ChevronDown, Pencil } from "lucide-react";
import { blobUrl, prettyName } from "../brand";
import NotFound from "./NotFound";
import { PageBand } from "../components/ui";
import cliReadme from "../../../cli/README.md?raw";
import contributing from "../../../CONTRIBUTING.md?raw";

// docs/*.md, plus the two pages docs/README.md links outside docs/.
const files = import.meta.glob("../../../docs/*.md", { query: "?raw", import: "default", eager: true });

const PAGES = {};
for (const [file, text] of Object.entries(files)) {
  const base = file.split("/").pop().replace(/\.md$/, "");
  PAGES[base === "README" ? "" : base] = { text, source: `docs/${base}.md`, dir: "docs" };
}
PAGES.cli = { text: cliReadme, source: "cli/README.md", dir: "cli" };
PAGES.contributing = { text: contributing, source: "CONTRIBUTING.md", dir: "" };

const titleOf = (text) => (text.match(/^#\s+(.+)$/m)?.[1] || "").replace(/`/g, "");

/** The sidebar: docs/README.md's groups and tables, in their order. */
function navigation() {
  const groups = [];
  for (const line of PAGES[""].text.split("\n")) {
    const group = line.match(/^\*\*(.+)\*\*\s*$/);
    if (group) groups.push({ title: group[1], pages: [] });
    const row = line.match(/^\|\s*\[[^\]]+\]\(([^)]+)\)\s*\|\s*(.+?)\s*\|\s*$/);
    if (row && groups.length) {
      const slug = slugFor(row[1], "docs");
      if (slug !== null && PAGES[slug]) groups.at(-1).pages.push({ slug, title: titleOf(PAGES[slug].text), blurb: row[2] });
    }
  }
  return groups;
}

/** The site page a repository path names (null: not a page here). */
function slugFor(href, dir) {
  const path = href.split("#")[0];
  const resolved = new URL(path, `https://x/${dir ? dir + "/" : ""}`).pathname.slice(1);
  if (resolved === "docs/README.md") return "";
  if (resolved === "cli/README.md") return "cli";
  if (resolved === "CONTRIBUTING.md") return "contributing";
  const m = resolved.match(/^docs\/([a-z0-9-]+)\.md$/);
  return m ? m[1] : null;
}

function MdLink({ href = "", children, dir }) {
  if (/^(https?:|mailto:)/.test(href)) {
    return <a href={href} target="_blank" rel="noreferrer">{children}</a>;
  }
  if (href.startsWith("#")) return <a href={href}>{children}</a>;
  const slug = slugFor(href, dir);
  const hash = href.includes("#") ? `#${href.split("#")[1]}` : "";
  if (slug !== null && PAGES[slug]) {
    return <Link to={{ pathname: slug ? `/docs/${slug}` : "/docs", hash }}>{children}</Link>;
  }
  const path = new URL(href.split("#")[0], `https://x/${dir ? dir + "/" : ""}`).pathname.slice(1);
  return <a href={blobUrl(path) + hash} target="_blank" rel="noreferrer">{children}</a>;
}

function Sidebar({ groups, current, onPick }) {
  return (
    <nav aria-label="Documentation" className="space-y-7 text-sm">
      <Link to="/docs" onClick={onPick}
        className={`block font-sans font-medium ${current === "" ? "text-teal" : "hover:text-teal"}`}>
        Overview
      </Link>
      {groups.map((g) => (
        <div key={g.title}>
          <p className="mb-3 text-[0.7rem] uppercase tracking-wider text-muted">{g.title}</p>
          <ul className="space-y-1 border-l border-line">
            {g.pages.map((p) => (
              <li key={p.slug}>
                <Link to={`/docs/${p.slug}`} onClick={onPick}
                  className={`-ml-px block border-l py-1 pl-4 transition-colors ${
                    current === p.slug ? "border-teal text-teal" : "border-transparent text-muted hover:text-ink"
                  }`}>
                  {p.title}
                </Link>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </nav>
  );
}

function Outline({ text, slug }) {
  const [items, setItems] = useState([]);
  useEffect(() => {
    // The ids rehype-slug gave the rendered headings.
    setItems([...document.querySelectorAll("article.prose h2[id]")].map((h) => [h.id, h.textContent.replace(/#$/, "")]));
  }, [text, slug]);
  if (items.length < 2) return null;
  return (
    <nav aria-label="On this page" className="text-sm">
      <p className="mb-3 text-[0.7rem] uppercase tracking-wider text-muted">On this page</p>
      <ul className="space-y-2">
        {items.map(([id, label]) => (
          <li key={id}><a href={`#${id}`} className="text-[0.8rem] text-muted hover:text-ink">{label}</a></li>
        ))}
      </ul>
    </nav>
  );
}

function Overview({ groups }) {
  return (
    <div>
      <p className="max-w-2xl text-[0.9rem] leading-7 text-muted">
        Installing, using and repairing the system, and building it yourself. Commands use the default names; a rebranded
        build uses its own.
      </p>
      {groups.map((g) => (
        <section key={g.title} className="mt-12">
          <h2 className="mb-4 text-xl font-semibold text-violet">{g.title}</h2>
          <div className="grid gap-3 sm:grid-cols-2">
            {g.pages.map((p) => (
              <Link key={p.slug} to={`/docs/${p.slug}`}
                className="group box p-5 transition-colors hover:border-teal/60">
                <p className="flex items-center justify-between font-sans font-semibold">
                  {p.title}
                  <ArrowRight size={16} className="text-muted transition-transform group-hover:translate-x-0.5 group-hover:text-teal" />
                </p>
                <p className="mt-1.5 text-[0.8rem] leading-6 text-muted">{p.blurb}</p>
              </Link>
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}

export default function Docs() {
  const { slug = "" } = useParams();
  const location = useLocation();
  const groups = useMemo(navigation, []);
  const [menu, setMenu] = useState(false);
  const page = PAGES[slug];
  const flat = groups.flatMap((g) => g.pages);
  const at = flat.findIndex((p) => p.slug === slug);

  useEffect(() => {
    document.title = page ? `${slug ? titleOf(page.text) + " · " : "Documentation · "}${prettyName}` : prettyName;
  }, [page, slug]);
  useEffect(() => setMenu(false), [location.pathname]);

  if (!page) return <NotFound />;
  const components = { a: (props) => <MdLink {...props} dir={page.dir} /> };

  return (
    <>
    <PageBand>
      <h1 className="text-3xl font-semibold">{slug ? titleOf(page.text) : "Documentation"}</h1>
      <p className="mt-1 text-[0.8rem] text-band-ink/75">{prettyName} documentation</p>
    </PageBand>
    <div className="mx-auto grid max-w-7xl gap-10 px-4 py-10 sm:px-6 lg:grid-cols-[15rem_minmax(0,1fr)] xl:grid-cols-[15rem_minmax(0,1fr)_13rem]">
      <aside className="lg:sticky lg:top-24 lg:max-h-[calc(100vh-7rem)] lg:overflow-y-auto">
        <button type="button" onClick={() => setMenu(!menu)} aria-expanded={menu}
          className="box flex w-full items-center justify-between px-4 py-2.5 text-sm lg:hidden">
          {slug ? titleOf(page.text) : "Overview"} <ChevronDown size={16} className={menu ? "rotate-180" : ""} />
        </button>
        <div className={`${menu ? "mt-4 block" : "hidden"} lg:block`}>
          <Sidebar groups={groups} current={slug} onPick={() => setMenu(false)} />
        </div>
      </aside>

      <main className="min-w-0">
        {slug === "" ? (
          <Overview groups={groups} />
        ) : (
          <>
            <article className="prose max-w-3xl">
              <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeSlug]} components={components}>
                {page.text}
              </ReactMarkdown>
            </article>
            <div className="mt-14 flex max-w-3xl flex-wrap items-center justify-between gap-4 border-t border-line pt-6 text-[0.8rem]">
              <a href={blobUrl(page.source)} target="_blank" rel="noreferrer" className="flex items-center gap-2 text-muted hover:text-ink">
                <Pencil size={14} /> Edit this page on GitHub
              </a>
              <div className="flex gap-6">
                {at > 0 && (
                  <Link to={`/docs/${flat[at - 1].slug}`} className="flex items-center gap-1.5 text-muted hover:text-ink">
                    <ArrowLeft size={14} /> {flat[at - 1].title}
                  </Link>
                )}
                {at >= 0 && at < flat.length - 1 && (
                  <Link to={`/docs/${flat[at + 1].slug}`} className="flex items-center gap-1.5 text-muted hover:text-ink">
                    {flat[at + 1].title} <ArrowRight size={14} />
                  </Link>
                )}
              </div>
            </div>
          </>
        )}
      </main>

      {slug !== "" && (
        <aside className="hidden xl:block">
          <div className="sticky top-24">
            <Outline text={page.text} slug={slug} />
          </div>
        </aside>
      )}
    </div>
    </>
  );
}
