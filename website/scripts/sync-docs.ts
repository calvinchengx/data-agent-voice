// Generates Starlight content from the canonical Markdown in /docs, keeping
// /docs as the single source of truth: those files stay pristine and their
// GitHub-relative links keep working, while the site gets its own routes.
//
// For each doc it derives the title from the leading H1, injects Starlight
// frontmatter pointing "Edit this page" at the real file, drops the duplicate
// H1, and rewrites intra-doc links to site routes.
import {
  existsSync,
  mkdirSync,
  readFileSync,
  readdirSync,
  rmSync,
  statSync,
  writeFileSync,
} from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const REPO = join(here, '..', '..');
const DOCS_SRC = join(REPO, 'docs');
const OUT = join(here, '..', 'src', 'content', 'docs');
const BASE = '/data-agent-voice/docs/';
const REPO_URL = 'https://github.com/calvinchengx/data-agent-voice';

// The docs worth publishing: `NN-name.md` chapters, plus the two living
// references that carry no reading-order number.
const DOC_RE = /^(\d{2}-[a-z0-9-]+|parity|upstream-issues)\.md$/;
// ADRs live one level down and keep that shape in the URL.
const ADR_DIR = 'adr';

// `](./|docs/ NN-slug.md#anchor)` -> `](/data-agent-voice/NN-slug/#anchor)`.
const LINK_RE =
  /\]\((?:\.\/|docs\/)?(\d{2}-[a-z0-9-]+|parity|upstream-issues)\.md(#[^)]*)?\)/g;
// `](adr/0001-x.md)` and `](../adr/0001-x.md)` from a chapter or an ADR sibling.
const ADR_LINK_RE = /\]\((?:\.\.\/)?adr\/([a-z0-9-]+)\.md(#[^)]*)?\)/g;
// Repo-relative links (`../seed`, `../services/...`) are correct on GitHub,
// where /docs sits one level under the root — but they are dead on a site
// whose pages are flat `/<base>/<slug>/` routes with nothing above them.
// Rewriting them to absolute GitHub URLs is what keeps ONE source working in
// both renderings; the alternative is editing /docs into something that no
// longer resolves on GitHub. A path matching nothing is reported rather than
// silently linked into a 404.
const REPO_LINK_RE = /\]\(\.\.\/([^)#]+)(#[^)]*)?\)/g;

let warnings = 0;

function rewriteRepoLinks(md: string, where: string): string {
  return md.replace(REPO_LINK_RE, (_match, path: string, anchor?: string) => {
    const clean = path.replace(/\/+$/, '');
    if (clean.startsWith(`${ADR_DIR}/`)) return `](${BASE}${clean.replace(/\.md$/, '')}/${anchor ?? ''})`;
    const target = join(REPO, clean);
    const exists = existsSync(target);
    if (!exists) {
      console.warn(`sync-docs: WARNING ${where}: ../${path} matches nothing in the repo`);
      warnings += 1;
    }
    const kind = exists && statSync(target).isDirectory() ? 'tree' : 'blob';
    return `](${REPO_URL}/${kind}/main/${clean}${anchor ?? ''})`;
  });
}

function rewriteLinks(md: string, where: string): string {
  const chapters = md.replace(
    LINK_RE,
    (_match, slug: string, anchor?: string) => `](${BASE}${slug}/${anchor ?? ''})`,
  );
  const withAdrs = chapters.replace(
    ADR_LINK_RE,
    (_match, slug: string, anchor?: string) => `](${BASE}${ADR_DIR}/${slug}/${anchor ?? ''})`,
  );
  return rewriteRepoLinks(withAdrs, where);
}

// "ADR 0001 — Two executor implementations" keeps its number; a chapter's
// leading "07 — " does not, because the sidebar already orders it.
function cleanTitle(h1: string): string {
  return h1.replace(/^\d{2}\s*[—:-]\s*/, '').trim();
}

// The page's own meta description, taken from the first real paragraph.
//
// WHY. Starlight falls back to the SITE description when a page declares none,
// so every page of a site shipped the same `<meta name="description">` --
// checked on three pages of this site and they were byte-identical. Google
// discards duplicate descriptions and writes its own snippet, so 300+ pages
// across this family were competing with one sentence between them.
//
// FIRST PARAGRAPH, not a summary. It is the one sentence the author already
// wrote to introduce the page, and deriving it means it cannot go stale. Skips
// headings, code fences, tables, quotes, images, lists and HTML, which are all
// things that read badly as a search snippet.
//
// Absent rather than empty when nothing suitable is found: Starlight then falls
// back to the site description, which is the old behaviour and no worse.
function description(raw: string): string | null {
  const lines = raw.split('\n');
  let inFence = false;
  const para: string[] = [];
  for (const line of lines) {
    const t = line.trim();
    if (/^(```|~~~)/.test(t)) { inFence = !inFence; continue; }
    if (inFence) continue;
    if (para.length === 0) {
      if (!t) continue;
      if (/^(#|>|\||-|\*|\d+\.|!\[|<)/.test(t)) continue;
      para.push(t);
    } else {
      if (!t || /^(#|>|\||```|~~~)/.test(t)) break;
      para.push(t);
    }
  }
  if (para.length === 0) return null;
  // Markdown emphasis, links and code marks read as noise in a snippet.
  let text = para
    .join(' ')
    .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
    .replace(/[`*_]/g, '')
    .replace(/\s+/g, ' ')
    .trim();
  // 25, not 40. "Seven services, one discipline." is 30 characters and is a
  // better description than the site-wide sentence it would otherwise inherit:
  // distinctive and short beats generic and long, for a snippet.
  if (text.length < 25) return null;
  // Search engines truncate around 160; cut on a sentence, else on a word.
  if (text.length > 160) {
    const stop = text.lastIndexOf('. ', 160);
    text = stop > 80 ? text.slice(0, stop + 1)
                     : text.slice(0, text.lastIndexOf(' ', 157)) + '\u2026';
  }
  return text;
}

function yamlEscape(s: string): string {
  // Backslashes first, then quotes — otherwise a literal backslash in a title
  // leaks through and corrupts the double-quoted YAML scalar.
  return `"${s.replace(/\\/g, '\\\\').replace(/"/g, '\\"')}"`;
}

const entries: { slug: string; title: string; desc: string | null }[] = [];


// ---------------------------------------------------------------------------
// llms.txt for this site.
//
// A PROPOSED convention (llmstxt.org), not a standard: a markdown file at a
// site root giving a model a short, link-dense map of what the site holds, so
// a crawler need not infer the shape from HTML. No major provider has
// committed to consuming it. It is cheap and cannot hurt; it is not a
// substitute for the per-page descriptions above, which affect search today.
//
// GENERATED FROM THE SAME PASS that writes the pages, so the title, the
// description and the URL of every entry are the ones actually published. A
// hand-written index of a docs tree is wrong within a fortnight.
//
// Written to public/, which Astro copies to the root of the built site, so it
// lands beside the pages it describes at whatever `base` this site uses.
const LLMS_TITLE: string = 'Data Agent Voice';
const LLMS_BLURB: string = 'The Analyst Line: ask your governed data in English, out loud, and hear the answer with the definition it applied. A voice front end over data-agent-service on the TEN framework. No audio has been through it yet; the parity ledger says which rows are red.';

function writeLlms(entries: { slug: string; title: string; desc: string | null }[]): number {
  const origin = 'https://calvinchengx.github.io';
  const out = [`# ${LLMS_TITLE}`, '', `> ${LLMS_BLURB}`, '', '## Documentation', ''];
  for (const e of entries) {
    const url = `${origin}${BASE}${e.slug}/`;
    out.push(e.desc ? `- [${e.title}](${url}): ${e.desc}` : `- [${e.title}](${url})`);
  }
  out.push('');
  const dir = join(here, '..', 'public');
  mkdirSync(dir, { recursive: true });
  writeFileSync(join(dir, 'llms.txt'), out.join('\n'));
  return entries.length;
}

function convert(relative: string): string {
  const raw = readFileSync(join(DOCS_SRC, relative), 'utf8');
  const h1 = raw.split('\n').find((line) => /^#\s+/.test(line));
  const title = h1 ? cleanTitle(h1.replace(/^#\s+/, '')) : relative.replace(/\.md$/, '');
  const lines = raw.split('\n');
  const h1Index = lines.findIndex((line) => /^#\s+/.test(line));
  if (h1Index >= 0) {
    // Starlight renders the frontmatter title, so the H1 would be a duplicate.
    lines.splice(h1Index, lines[h1Index + 1]?.trim() === '' ? 2 : 1);
  }
  const body = rewriteLinks(lines.join('\n').replace(/^\n+/, ''), relative);
  const editUrl = `${REPO_URL}/edit/main/docs/${relative}`;
  const desc = description(raw);
  entries.push({ slug: relative.replace(/\.md$/, ''), title, desc });
  return (
    `---\ntitle: ${yamlEscape(title)}\n` +
    (desc ? `description: ${yamlEscape(desc)}\n` : '') +
    `editUrl: ${yamlEscape(editUrl)}\n---\n\n${body}`
  );
}

// The landing page is synthesized here rather than taken from /docs, because
// the repository's front door is README.md and duplicating it would give two
// things to keep true.
function writeIndex(): void {
  const body =
    `Talk to your governed data. Ask out loud, and hear the answer with the definition it\n` +
    `applied and the caveat it raised — because you cannot skim audio, and a number without\n` +
    `its meaning is how the wrong team wins.\n\n` +
    `A voice front end over [data-agent-service](https://github.com/calvinchengx/data-agent-service),\n` +
    `built on the [TEN framework](https://github.com/TEN-framework/ten-framework). You sign in\n` +
    `once, and every question runs as you, all the way to the source.\n\n` +
    `:::caution[No one has heard an answer from this]\n` +
    `The architecture is decided, the framework is pinned and read from its source, both\n` +
    `image legs build, all seven nodes load, and speech has been recognised end to end. What\n` +
    `has never happened is a reply coming back as sound. [Parity](parity.md) says which rows\n` +
    `are green and which are red, and none of them claims a working line.\n` +
    `:::\n\n` +
    `## Getting started\n\n` +
    `- [Quickstart](01-quickstart.md) — run it, and what you will and will not get\n` +
    `- [Architecture](02-architecture.md) — the two loops, the nodes, and where authority is not\n\n` +
    `## Using it\n\n` +
    `- [Tiers](04-tiers.md) — the three tiers, and what the host may never say\n` +
    `- [Latency](03-latency.md) — the budget, the switches, and where the seconds actually are\n\n` +
    `## Proving it\n\n` +
    `- [Witnesses](06-witnesses.md) — what is checked, and what that is worth\n` +
    `- [CI](07-ci.md) — what runs when; a documentation change skips the image builds\n\n` +
    `## Reference\n\n` +
    `- [The plan](00-plan.md) — the long-form argument: decisions, phases, risks\n` +
    `- [TEN at 0.11.71](05-ten.md) — read from source, including what it does not do\n` +
    `- [Parity](parity.md) — what is witnessed, and what is not\n` +
    `- [Upstream issues](upstream-issues.md) — seven defects, found by running it\n\n` +
    `## The gap this is built around\n\n` +
    `A question to the service upstream takes **26 seconds at the median**. A conversation\n` +
    `reads as broken after about **one second** of silence. No faster model closes a gap of\n` +
    `thirty times, so this does not try to: the conversation stops waiting for the agent,\n` +
    `and the agent runs where nobody is waiting.\n`;
  const frontmatter =
    `---\ntitle: Overview\ndescription: The Analyst Line — talk to your governed data, ` +
    `over a service that takes twenty-six seconds and a conversation that cannot wait.` +
    `\neditUrl: false\n---\n\n`;
  writeFileSync(join(OUT, 'index.md'), frontmatter + rewriteLinks(body, 'index'));
}

rmSync(OUT, { recursive: true, force: true });
mkdirSync(join(OUT, ADR_DIR), { recursive: true });

const chapters = readdirSync(DOCS_SRC).filter((name) => DOC_RE.test(name)).sort();
for (const name of chapters) {
  writeFileSync(join(OUT, name), convert(name));
}

const adrDir = join(DOCS_SRC, ADR_DIR);
const adrs = existsSync(adrDir)
  ? readdirSync(adrDir).filter((name) => name.endsWith('.md')).sort()
  : [];
for (const name of adrs) {
  writeFileSync(join(OUT, ADR_DIR, name), convert(join(ADR_DIR, name)));
}

writeIndex();

// A page nobody can navigate to is a page nobody reads. The sidebar is
// curated rather than generated -- reading order is an editorial decision --
// so the risk is a doc being added and silently never appearing in it. That
// happened once already: docs/13-testing.md was published, linked from the
// README's coverage badges, and absent from every menu.
const config = readFileSync(join(here, '..', 'astro.config.ts'), 'utf8');
const listed = new Set(
  [...config.matchAll(/slug: '([^']+)'/g)].map((m) => m[1]),
);
const generated = [
  ...chapters.map((n) => n.replace(/\.md$/, '')),
  ...adrs.map((n) => `${ADR_DIR}/${n.replace(/\.md$/, '')}`),
];
const unreachable = generated.filter((slug) => !listed.has(slug));
if (unreachable.length) {
  console.error(
    `sync-docs: these documents are published but absent from the sidebar in ` +
      `astro.config.ts, so nothing links to them: ${unreachable.join(', ')}`,
  );
  process.exit(1);
}

console.log(
  `sync-docs: ${chapters.length} chapters, ${adrs.length} ADR(s), ` +
    `all reachable from the sidebar, ${warnings} warning(s)`,
);

writeLlms(entries);
