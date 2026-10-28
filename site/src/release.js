// The newest ISO release, from the GitHub API (no token: 60 requests an hour
// per visitor, so the answer is kept for the browser session).
import { useEffect, useState } from "react";
import { repo } from "./brand";

const KEY = "latest-release";

function summarise(rel) {
  const assets = rel.assets || [];
  const parts = assets
    .filter((a) => /\.iso(\.part-\d+)?$/.test(a.name))
    .sort((a, b) => a.name.localeCompare(b.name))
    .map((a) => ({ name: a.name, url: a.browser_download_url, size: a.size }));
  const iso = parts.length ? parts[0].name.replace(/\.part-\d+$/, "") : "";
  const sum = assets.find((a) => a.name === `${iso}.sha256`);
  const meta = assets.find((a) => a.name === iso.replace(/\.iso$/, ".json"));
  return {
    tag: rel.tag_name,
    title: rel.name || rel.tag_name,
    published: rel.published_at,
    url: rel.html_url,
    iso,
    parts,
    split: parts.length > 1 || /\.part-\d+$/.test(parts[0]?.name || ""),
    size: parts.reduce((n, p) => n + p.size, 0),
    sha256Url: sum?.browser_download_url,
    metaUrl: meta?.browser_download_url,
  };
}

export function useLatestRelease() {
  const [state, setState] = useState(() => {
    try {
      const cached = JSON.parse(sessionStorage.getItem(KEY) || "null");
      if (cached) return { status: "ok", release: cached };
    } catch {
      /* no storage: ask GitHub */
    }
    return { status: "loading" };
  });

  useEffect(() => {
    if (state.status !== "loading" || !repo) {
      if (!repo) setState({ status: "none" });
      return;
    }
    let live = true;
    fetch(`https://api.github.com/repos/${repo.owner}/${repo.name}/releases/latest`, {
      headers: { Accept: "application/vnd.github+json" },
    })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((rel) => {
        const release = summarise(rel);
        if (!release.parts.length) throw new Error("no ISO in the latest release");
        try {
          sessionStorage.setItem(KEY, JSON.stringify(release));
        } catch {
          /* fine without */
        }
        if (live) setState({ status: "ok", release });
      })
      .catch(() => live && setState({ status: "none" }));
    return () => {
      live = false;
    };
  }, [state.status]);

  return state;
}

export function formatSize(bytes) {
  return `${(bytes / 2 ** 30).toFixed(2)} GiB`;
}

export function formatDate(iso) {
  try {
    return new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "long", day: "numeric" });
  } catch {
    return iso;
  }
}
