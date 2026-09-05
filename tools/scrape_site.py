"""Pull a company website down to text, sitemap first, for a knowledge base.

    python tools/scrape_site.py https://www.mbsolarhub.com
    python tools/scrape_site.py https://www.mbsolarhub.com --out .tmp/mbsolarhub

Why the sitemap is only the starting point
-------------------------------------------
mbsolarhub.com's sitemap declares 500 URLs. 465 of them are
`blog.php?page=N&search=` -- and pages 2 through 464 are EMPTY. The generator
that wrote the sitemap enumerated pagination that does not exist. Following it
literally would mean 465 requests at the site's expense to collect nothing, and
465 near-identical files for a human to wade through afterwards.

Meanwhile the actual articles live at `blogsnew.php?id=N`, and the sitemap does
not mention a single one of them.

So this does both halves: it reads the sitemap for the page list, and it follows
same-domain links out of every page it fetches to find what the sitemap missed.
Anything already seen is skipped, so the two halves cannot duplicate work.

What is deliberately dropped
-----------------------------
`login.php`, `forgot-password.php`, and any page whose text is byte-identical to
one already saved. A login form has no prose in it, and a knowledge base full of
"Enter your password" is worse than one without it -- it is retrievable, and it
will be retrieved.

The duplicate check is what actually tames this site, and a length threshold is
no substitute for it. Those 465 phantom pagination pages are not empty: each one
still renders the sidebar, the search box and the recent-posts list, for 1,186
characters of chrome identical on all of them. A first pass here kept all 465,
because none of them looked short enough. Identical text is the signal, not
short text.

On the size of the result
--------------------------
For a VOICE agent this scrape is the SOURCE, never the prompt. Vaani's business
layer is re-read on every single turn, and this project has measured what that
costs: 1,086 characters of extra prompt took the LLM's first token from 0.22s to
0.655s (run 206). Pasting a whole website into it would undo every latency fix
made this month. Scrape everything here; distil deliberately afterwards.
"""

from __future__ import annotations

import argparse
import re
import sys
import time
import hashlib
from collections import deque
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from lxml import html as lxml_html

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# Pages with no prose worth keeping. A knowledge base containing "Enter your
# password" will eventually answer a caller with it.
SKIP = re.compile(
    r"/(login|logout|register|signup|forgot-password|reset-password|cart|"
    r"checkout|account)\.(php|html?|aspx)?$"
    r"|\.(jpg|jpeg|png|gif|svg|webp|pdf|zip|mp4|mp3|css|js|ico|woff2?)$",
    re.IGNORECASE)

# Chrome that repeats on every page. Kept out of the text so the same 40 lines
# of menu do not appear in 35 files and drown the content in a search.
STRIP_TAGS = ("script", "style", "noscript", "nav", "header", "footer",
              "svg", "form", "iframe")

BLANKS = re.compile(r"\n{3,}")


def canonical(url: str) -> str:
    """One URL per page. Fragments and the trailing slash are not new pages."""
    parts = urlsplit(url)
    path = parts.path or "/"
    if path != "/" and path.endswith("/"):
        path = path[:-1]
    return urlunsplit((parts.scheme, parts.netloc.lower(), path,
                       parts.query, ""))


def fetch(url: str, timeout: int = 30) -> str | None:
    try:
        req = Request(url, headers={"User-Agent": UA,
                                    "Accept-Language": "en-IN,en;q=0.9"})
        with urlopen(req, timeout=timeout) as r:
            ctype = (r.headers.get("Content-Type") or "").lower()
            if "html" not in ctype and ctype:
                return None
            raw = r.read()
    except Exception as exc:                      # noqa: BLE001
        print(f"    !! {type(exc).__name__}: {exc}")
        return None
    for enc in ("utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def sitemap_urls(base: str) -> list[str]:
    """Every <loc> in the sitemap, including a sitemap index one level deep."""
    out: list[str] = []
    for name in ("sitemap.xml", "sitemap_index.xml", "sitemap-index.xml"):
        body = fetch(urljoin(base, "/" + name))
        if not body:
            continue
        locs = re.findall(r"<loc>\s*([^<]+?)\s*</loc>", body)
        for loc in locs:
            loc = loc.replace("&amp;", "&").strip()
            if loc.endswith(".xml"):
                inner = fetch(loc)
                if inner:
                    out += [u.replace("&amp;", "&").strip()
                            for u in re.findall(r"<loc>\s*([^<]+?)\s*</loc>",
                                                inner)]
            else:
                out.append(loc)
        if out:
            break
    return out


def readable(doc, url: str) -> tuple[str, str]:
    """(title, text). Chrome removed, whitespace collapsed, order preserved."""
    for tag in STRIP_TAGS:
        for node in doc.xpath(f"//{tag}"):
            node.getparent().remove(node)

    title = ""
    for xp in ("//h1//text()", "//title/text()"):
        found = doc.xpath(xp)
        if found:
            title = " ".join(t.strip() for t in found if t.strip())
            break
    title = re.sub(r"\s+", " ", title).strip() or url

    lines: list[str] = []
    for node in doc.xpath("//h1|//h2|//h3|//h4|//p|//li|//td|//th|//dd|//dt"):
        text = re.sub(r"\s+", " ", node.text_content()).strip()
        if not text or len(text) < 2:
            continue
        tag = node.tag.lower()
        if tag in ("h1", "h2", "h3", "h4"):
            lines.append("")
            lines.append("#" * int(tag[1]) + " " + text)
            lines.append("")
        elif tag in ("li", "td", "th", "dd", "dt"):
            lines.append(f"- {text}")
        else:
            lines.append(text)

    # Consecutive duplicates: the same phrase inside a <td> and its <p>.
    deduped: list[str] = []
    for line in lines:
        if deduped and line and line == deduped[-1]:
            continue
        deduped.append(line)
    return title, BLANKS.sub("\n\n", "\n".join(deduped)).strip()


def strip_boilerplate(pages: dict[str, str], threshold: float = 0.3
                      ) -> tuple[dict[str, str], list[str]]:
    """Drop lines that appear on a third or more of the pages.

    Removing `<nav>`, `<header>` and `<footer>` is not enough, and mbsolarhub is
    a good example of why: its menu is a plain `<ul>` of `<li>` in the body, so
    every one of the 46 pages carried the same 40 lines of "Solar Panels /
    Solar Inverter / Solar Structures ..." before the actual content started.
    That is roughly 1,200 characters of noise per page, and in a knowledge base
    it is worse than noise -- a search for "solar pumps" matches all 46 files.

    Frequency finds it without a per-site rule: real content does not repeat
    across a third of a website. The threshold is deliberately not lower,
    because a genuine sentence CAN repeat on a handful of pages (a tagline, a
    compliance note) and those are worth keeping.
    """
    if len(pages) < 4:
        return pages, []                # too few pages for frequency to mean much
    counts: dict[str, int] = {}
    for text in pages.values():
        for line in set(text.splitlines()):
            if line.strip():
                counts[line] = counts.get(line, 0) + 1
    cutoff = max(2, int(len(pages) * threshold))
    common = {line for line, n in counts.items() if n >= cutoff}
    cleaned = {}
    for url, text in pages.items():
        kept = [ln for ln in text.splitlines() if ln.strip() not in
                {c.strip() for c in common} or not ln.strip()]
        cleaned[url] = BLANKS.sub("\n\n", "\n".join(kept)).strip()
    return cleaned, sorted(common, key=lambda s: -counts[s])


def links(doc, url: str, host: str) -> list[str]:
    out = []
    for href in doc.xpath("//a/@href"):
        href = (href or "").strip()
        if not href or href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        full = canonical(urljoin(url, href))
        if urlparse(full).netloc.lower().replace("www.", "") == host:
            out.append(full)
    return out


def slug(url: str) -> str:
    parts = urlsplit(url)
    name = (parts.path.strip("/") or "index")
    if parts.query:
        name += "_" + parts.query
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name)
    return (name[:120] or "index") + ".md"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("base")
    ap.add_argument("--out", default="")
    ap.add_argument("--max-pages", type=int, default=400)
    ap.add_argument("--delay", type=float, default=0.4,
                    help="seconds between requests; be a polite guest")
    a = ap.parse_args()

    base = a.base.rstrip("/")
    host = urlparse(base).netloc.lower().replace("www.", "")
    out = Path(a.out or f".tmp/{host.split('.')[0]}")
    out.mkdir(parents=True, exist_ok=True)

    seeds = sitemap_urls(base)
    print(f"sitemap: {len(seeds)} url(s)")
    queue: deque[str] = deque()
    seen: set[str] = set()
    for u in [base + "/"] + seeds:
        c = canonical(u)
        if c not in seen and not SKIP.search(c):
            seen.add(c)
            queue.append(c)
    print(f"queued : {len(queue)} after dropping login/asset URLs\n")

    saved, empty, failed, dupes = [], [], [], []
    by_text: dict[str, str] = {}          # content hash -> first URL that had it
    pages: dict[str, str] = {}            # url -> text, written after the crawl
    titles: dict[str, str] = {}
    while queue and len(saved) < a.max_pages:
        url = queue.popleft()
        body = fetch(url)
        if body is None:
            failed.append(url)
            continue
        try:
            doc = lxml_html.fromstring(body)
        except Exception:                          # noqa: BLE001
            failed.append(url)
            continue

        # Discover before stripping -- `readable` deletes <nav>, and on this
        # site the article links the sitemap never mentions live in the body.
        for found in links(doc, url, host):
            if found not in seen and not SKIP.search(found):
                seen.add(found)
                queue.append(found)

        title, text = readable(doc, url)
        if len(text) < 120:
            empty.append(url)
            print(f"  --  {url}  (no content)")
            time.sleep(a.delay)
            continue

        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if digest in by_text:
            # The 465 phantom pagination pages land here: same sidebar, same
            # search box, same recent-posts list, not one article between them.
            dupes.append((url, by_text[digest]))
            print(f"  ==  {url}  (same text as {by_text[digest]})")
            time.sleep(a.delay)
            continue
        by_text[digest] = url
        pages[url] = text
        titles[url] = title
        print(f"  ok  {url}  ({len(text):,} chars)")
        time.sleep(a.delay)

    # Boilerplate can only be found once every page is in hand -- it is defined
    # by how often a line repeats ACROSS pages, so nothing can be written until
    # the crawl is finished.
    pages, common = strip_boilerplate(pages)
    for url, text in pages.items():
        if len(text) < 120:
            # Nothing but chrome. Real on this site: `Video_Vlogs.php` is a
            # page of embedded players and a heading.
            empty.append(url)
            continue
        path = out / slug(url)
        path.write_text(
            f"# {titles[url]}\n\nSource: {url}\n\n---\n\n{text}\n",
            encoding="utf-8")
        saved.append((url, len(text)))
    if common:
        (out / "_BOILERPLATE.md").write_text(
            "# Lines removed as site chrome\n\n"
            "Present on a third or more of the pages, so almost certainly the\n"
            "menu, the footer or the newsletter box. Kept here so nothing is\n"
            "silently lost.\n\n" + "\n".join(f"- {c}" for c in common) + "\n",
            encoding="utf-8")
    print(f"\n  stripped {len(common)} boilerplate line(s) present on >= 30% "
          f"of pages  ->  _BOILERPLATE.md")

    index = ["# Scrape index", "", f"Source: {base}",
             f"Pages with content: {len(saved)}", ""]
    for url, size in sorted(saved, key=lambda r: -r[1]):
        index.append(f"- [{slug(url)}]({slug(url)}) - {size:,} chars - {url}")
    if empty:
        index += ["", f"## Empty ({len(empty)})", ""]
        index += [f"- {u}" for u in empty[:20]]
        if len(empty) > 20:
            index.append(f"- ... and {len(empty) - 20} more")
    if dupes:
        index += ["", f"## Duplicate text, not saved ({len(dupes)})", ""]
        index += [f"- {u}  ==  {first}" for u, first in dupes[:20]]
        if len(dupes) > 20:
            index.append(f"- ... and {len(dupes) - 20} more")
    if failed:
        index += ["", f"## Failed ({len(failed)})", ""] + [f"- {u}" for u in failed]
    (out / "_INDEX.md").write_text("\n".join(index) + "\n", encoding="utf-8")

    print(f"\n{len(saved)} unique page(s), {len(dupes)} duplicate, "
          f"{len(empty)} empty, {len(failed)} failed  ->  {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
