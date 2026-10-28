# The website

The distribution's website, published on GitHub Pages by
[`.github/workflows/pages.yml`](../.github/workflows/pages.yml): Vite, React
and [HeroUI](https://heroui.com) on Tailwind CSS.

It has no content of its own to keep in sync:

* names, colours, links and the logo come from [`distro.conf`](../distro.conf)
  and [`branding/logo`](../branding/logo), so a rebranded build has a rebranded
  site;
* the documentation pages are [`docs/*.md`](../docs), with the sidebar taken
  from [`docs/README.md`](../docs/README.md);
* the desktop screenshots come from the dots submodule (`desktop/dots/docs/assets`);
* the download section reads the newest release from the GitHub API.

```bash
cd site
npm ci
npm run dev                         # http://localhost:5173
BASE_PATH=/distro/ npm run build    # what the workflow publishes, in dist/
```

To publish it, set **Settings → Pages → Source** to **GitHub Actions**. The site
is then at `https://<owner>.github.io/<repository>/` (or at the custom domain
set there), and every push to `main` that changes it updates it.
