// Everything the site says about the distribution's identity comes from
// distro.conf and the logo template, as everywhere else in the repository.
import confText from "../../distro.conf?raw";
import markTemplate from "../../branding/logo/logo-mark.svg.in?raw";
import gitmodules from "../../.gitmodules?raw";

function parseConf(text) {
  const conf = {};
  for (const line of text.split("\n")) {
    const m = line.match(/^([A-Z0-9_]+)="(.*)"\s*$/);
    if (m) conf[m[1]] = m[2];
  }
  return conf;
}

export const conf = parseConf(confText);

const markSvg = markTemplate.replace(/@([A-Z0-9_]+)@/g, (m, k) => conf[k] ?? m);
// As an image, so the SVG's gradient and mask ids never clash on the page.
export const logoUrl = `data:image/svg+xml,${encodeURIComponent(markSvg)}`;

const gh = (conf.DISTRO_GIT_URL || "").match(/github\.com\/([^/]+)\/([^/#?]+)/);
export const repo = gh ? { owner: gh[1], name: gh[2].replace(/\.git$/, "") } : null;
export const repoUrl = conf.DISTRO_GIT_URL;
export const releasesUrl = repo ? `https://github.com/${repo.owner}/${repo.name}/releases` : repoUrl;
export const blobUrl = (path, ref = "main") =>
  repo ? `https://github.com/${repo.owner}/${repo.name}/blob/${ref}/${path}` : repoUrl;

export const cli = conf.DISTRO_CLI || conf.DISTRO_ID;
export const name = conf.DISTRO_NAME;
export const prettyName = conf.DISTRO_PRETTY_NAME;

// The desktop's own repository (the dots submodule).
export const desktopUrl = (gitmodules.match(/path = desktop\/dots\s+url = (\S+)/) || [])[1]?.replace(/\.git$/, "") || repoUrl;
