#!/usr/bin/env python3
"""Download a local mirror of a site from the Internet Archive Wayback Machine."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin, urlparse, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup


CDX_API = "https://web.archive.org/cdx/search/cdx"
WAYBACK_FETCH = "https://web.archive.org/web/{timestamp}id_/{original}"
DEFAULT_BLOG_HINTS = ("/blog", "/posts", "/post", "/articles", "/news")


@dataclass(frozen=True)
class Snapshot:
    timestamp: str
    original: str
    mimetype: str


@dataclass(frozen=True)
class SeedSnapshot:
    timestamp: str
    original: str
    wayback_url: str


def normalize_domain(domain: str) -> str:
    cleaned = domain.strip().lower()
    cleaned = re.sub(r"^https?://", "", cleaned)
    cleaned = cleaned.split("/")[0]
    cleaned = cleaned.strip(".")
    if not cleaned:
        raise ValueError("Domain is empty after normalization.")
    return cleaned


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Mirror archived pages for a domain from the Wayback Machine.",
    )
    parser.add_argument("domain", help="Domain to mirror (example.com)")
    parser.add_argument(
        "--seed-wayback-url",
        default=None,
        help="Start from this exact Wayback URL and crawl links from it",
    )
    parser.add_argument(
        "--output-dir",
        default="output",
        help="Directory where mirrored files will be written (default: output)",
    )
    parser.add_argument(
        "--from-year",
        default=None,
        help="Earliest year to include, e.g. 2012",
    )
    parser.add_argument(
        "--to-year",
        default=None,
        help="Latest year to include, e.g. 2022",
    )
    parser.add_argument(
        "--snapshot-strategy",
        choices=("latest", "earliest", "nearest"),
        default="latest",
        help="Per-URL snapshot selection strategy (default: latest)",
    )
    parser.add_argument(
        "--target-date",
        default=None,
        help=(
            "Target date for --snapshot-strategy nearest, "
            "format YYYYMMDD or YYYYMMDDhhmmss"
        ),
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=500,
        help="Maximum number of unique archived pages to fetch (default: 500)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.15,
        help="Delay in seconds between page downloads (default: 0.15)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="Network timeout in seconds (default: 30)",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=3,
        help="Retries for CDX API requests after timeout/errors (default: 3)",
    )
    parser.add_argument(
        "--include-subdomains",
        action="store_true",
        help="Include subdomains when querying snapshots",
    )
    parser.add_argument(
        "--scrape-blog",
        action="store_true",
        help="Extract likely blog posts into JSON/Markdown files",
    )
    parser.add_argument(
        "--blog-path",
        default="",
        help="Optional blog path prefix like /blog or /news",
    )
    parser.add_argument(
        "--blog-seed-wayback-url",
        default=None,
        help="Optional extra Wayback URL to crawl for off-domain blog content",
    )
    return parser.parse_args()


def fetch_snapshots(
    session: requests.Session,
    domain: str,
    include_subdomains: bool,
    max_pages: int,
    from_year: str | None,
    to_year: str | None,
    strategy: str,
    target_date: str | None,
    timeout: int,
    retries: int,
) -> list[Snapshot]:
    if strategy == "nearest":
        if not target_date:
            raise ValueError(
                "--target-date is required when --snapshot-strategy=nearest"
            )
        return fetch_snapshots_nearest(
            session=session,
            domain=domain,
            include_subdomains=include_subdomains,
            max_pages=max_pages,
            from_year=from_year,
            to_year=to_year,
            target_date=target_date,
            timeout=timeout,
            retries=retries,
        )

    return fetch_snapshots_collapsed(
        session=session,
        domain=domain,
        include_subdomains=include_subdomains,
        max_pages=max_pages,
        from_year=from_year,
        to_year=to_year,
        strategy=strategy,
        timeout=timeout,
        retries=retries,
    )


def fetch_snapshots_collapsed(
    session: requests.Session,
    domain: str,
    include_subdomains: bool,
    max_pages: int,
    from_year: str | None,
    to_year: str | None,
    strategy: str,
    timeout: int,
    retries: int,
) -> list[Snapshot]:
    params: list[tuple[str, str]] = [
        ("url", domain),
        ("matchType", "domain" if include_subdomains else "host"),
        ("output", "json"),
        ("fl", "timestamp,original,mimetype,statuscode,digest,length"),
        ("filter", "statuscode:200"),
        ("filter", "!mimetype:warc/revisit"),
        ("collapse", "urlkey"),
        ("limit", str(max_pages)),
    ]
    if strategy == "latest":
        params.append(("sort", "reverse"))
    if from_year:
        params.append(("from", from_year))
    if to_year:
        params.append(("to", to_year))

    response = get_with_retries(
        session=session,
        url=CDX_API,
        params=params,
        timeout=timeout,
        retries=retries,
        operation="CDX collapsed lookup",
    )
    response.raise_for_status()
    rows = response.json()
    if not rows or len(rows) <= 1:
        return []

    snapshots: list[Snapshot] = []
    for row in rows[1:]:
        if len(row) < 3:
            continue
        timestamp, original, mimetype = row[0], row[1], row[2]
        parsed = urlparse(original)
        if parsed.scheme not in {"http", "https"}:
            continue
        snapshots.append(
            Snapshot(timestamp=timestamp, original=original, mimetype=mimetype)
        )
    return snapshots


def fetch_snapshots_nearest(
    session: requests.Session,
    domain: str,
    include_subdomains: bool,
    max_pages: int,
    from_year: str | None,
    to_year: str | None,
    target_date: str,
    timeout: int,
    retries: int,
) -> list[Snapshot]:
    originals = fetch_unique_originals(
        session=session,
        domain=domain,
        include_subdomains=include_subdomains,
        max_pages=max_pages,
        from_year=from_year,
        to_year=to_year,
        timeout=timeout,
        retries=retries,
    )
    snapshots: list[Snapshot] = []
    for original in originals:
        row = fetch_snapshot_for_exact_url(
            session=session,
            original=original,
            target_date=target_date,
            from_year=from_year,
            to_year=to_year,
            timeout=timeout,
            retries=retries,
        )
        if row is None:
            continue
        snapshots.append(row)
    return snapshots


def fetch_unique_originals(
    session: requests.Session,
    domain: str,
    include_subdomains: bool,
    max_pages: int,
    from_year: str | None,
    to_year: str | None,
    timeout: int,
    retries: int,
) -> list[str]:
    params: list[tuple[str, str]] = [
        ("url", domain),
        ("matchType", "domain" if include_subdomains else "host"),
        ("output", "json"),
        ("fl", "original"),
        ("filter", "statuscode:200"),
        ("collapse", "urlkey"),
        ("limit", str(max_pages)),
    ]
    if from_year:
        params.append(("from", from_year))
    if to_year:
        params.append(("to", to_year))

    response = get_with_retries(
        session=session,
        url=CDX_API,
        params=params,
        timeout=timeout,
        retries=retries,
        operation="CDX unique URL lookup",
    )
    response.raise_for_status()
    rows = response.json()
    if not rows or len(rows) <= 1:
        return []

    originals: list[str] = []
    for row in rows[1:]:
        if not row:
            continue
        original = row[0]
        if urlparse(original).scheme not in {"http", "https"}:
            continue
        originals.append(original)
    return originals


def fetch_snapshot_for_exact_url(
    session: requests.Session,
    original: str,
    target_date: str,
    from_year: str | None,
    to_year: str | None,
    timeout: int,
    retries: int,
) -> Snapshot | None:
    params: list[tuple[str, str]] = [
        ("url", original),
        ("matchType", "exact"),
        ("output", "json"),
        ("fl", "timestamp,original,mimetype,statuscode,digest,length"),
        ("filter", "statuscode:200"),
        ("filter", "!mimetype:warc/revisit"),
        ("limit", "1"),
        ("closest", target_date),
    ]
    if from_year:
        params.append(("from", from_year))
    if to_year:
        params.append(("to", to_year))

    response = get_with_retries(
        session=session,
        url=CDX_API,
        params=params,
        timeout=timeout,
        retries=retries,
        operation="CDX nearest lookup",
    )
    response.raise_for_status()
    rows = response.json()
    if not rows or len(rows) <= 1:
        return None

    row = rows[1]
    if len(row) < 3:
        return None
    timestamp, resolved_original, mimetype = row[0], row[1], row[2]
    if urlparse(resolved_original).scheme not in {"http", "https"}:
        return None
    return Snapshot(timestamp=timestamp, original=resolved_original, mimetype=mimetype)


def fetch_snapshot_boundaries(
    session: requests.Session,
    domain: str,
    include_subdomains: bool,
    timeout: int,
    retries: int,
) -> tuple[str | None, str | None]:
    base_params: list[tuple[str, str]] = [
        ("url", domain),
        ("matchType", "domain" if include_subdomains else "host"),
        ("output", "json"),
        ("fl", "timestamp"),
        ("filter", "statuscode:200"),
        ("limit", "1"),
    ]

    earliest_resp = get_with_retries(
        session=session,
        url=CDX_API,
        params=base_params,
        timeout=timeout,
        retries=retries,
        operation="CDX earliest boundary lookup",
    )
    earliest_resp.raise_for_status()
    earliest_rows = earliest_resp.json()
    earliest = (
        earliest_rows[1][0] if len(earliest_rows) > 1 and earliest_rows[1] else None
    )

    latest_params = [*base_params, ("sort", "reverse")]
    latest_resp = get_with_retries(
        session=session,
        url=CDX_API,
        params=latest_params,
        timeout=timeout,
        retries=retries,
        operation="CDX latest boundary lookup",
    )
    latest_resp.raise_for_status()
    latest_rows = latest_resp.json()
    latest = latest_rows[1][0] if len(latest_rows) > 1 and latest_rows[1] else None

    return earliest, latest


def is_valid_wayback_timestamp(value: str) -> bool:
    return bool(re.fullmatch(r"\d{8}(\d{6})?", value))


def human_ts(ts: str | None) -> str:
    if not ts:
        return "unknown"
    if len(ts) >= 14:
        return f"{ts[0:4]}-{ts[4:6]}-{ts[6:8]} {ts[8:10]}:{ts[10:12]}:{ts[12:14]}"
    if len(ts) >= 8:
        return f"{ts[0:4]}-{ts[4:6]}-{ts[6:8]}"
    return ts


def get_with_retries(
    session: requests.Session,
    url: str,
    params: list[tuple[str, str]],
    timeout: int,
    retries: int,
    operation: str,
) -> requests.Response:
    max_attempts = max(retries, 0) + 1
    for attempt in range(1, max_attempts + 1):
        try:
            return session.get(url, params=params, timeout=(10, timeout))
        except requests.RequestException as exc:
            if attempt >= max_attempts:
                raise
            wait_s = min(8.0, 0.6 * (2 ** (attempt - 1)))
            print(
                f"[!] {operation} failed ({exc}). "
                f"Retrying {attempt}/{max_attempts - 1} in {wait_s:.1f}s..."
            )
            time.sleep(wait_s)

    raise RuntimeError("unreachable")


def sanitize_path_component(part: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]", "_", part)


def local_path_for_url(original: str, mimetype: str) -> Path:
    parsed = urlsplit(original)
    host = sanitize_path_component(parsed.netloc)
    path = parsed.path or "/"
    parts = [sanitize_path_component(p) for p in path.split("/") if p]
    is_html = "html" in (mimetype or "").lower()

    if not parts:
        parts = ["index.html"]
    elif path.endswith("/"):
        parts.append("index.html")
    elif is_html and "." not in parts[-1]:
        parts.append("index.html")

    candidate = Path(host, *parts)

    if parsed.query and not is_html:
        digest = hashlib.sha1(parsed.query.encode("utf-8")).hexdigest()[:10]
        candidate = candidate.with_name(f"{candidate.stem}_{digest}{candidate.suffix}")

    if is_html and candidate.suffix.lower() not in {".html", ".htm"}:
        candidate = candidate.with_name(f"{candidate.name}.html")

    return candidate


def make_wayback_url(snapshot: Snapshot) -> str:
    return WAYBACK_FETCH.format(
        timestamp=snapshot.timestamp, original=snapshot.original
    )


def extract_original_from_wayback_url(url: str) -> str | None:
    parsed = extract_seed_snapshot(url)
    return parsed.original if parsed else None


def extract_seed_snapshot(wayback_url: str) -> SeedSnapshot | None:
    value = wayback_url.strip()
    if value.startswith("//"):
        value = "https:" + value

    parsed = urlparse(value)
    if "web.archive.org" not in parsed.netloc:
        return None

    match = re.search(r"/web/(\d{8,14})(?:[a-z_]+)?/(https?://.+)$", parsed.path)
    if not match:
        return None

    ts = match.group(1)
    original = match.group(2)
    return SeedSnapshot(timestamp=ts, original=original, wayback_url=value)


def to_wayback_url(original: str, timestamp: str) -> str:
    return WAYBACK_FETCH.format(timestamp=timestamp, original=original)


def collect_seed_links(
    html_text: str,
    page_original: str,
    domain: str,
    include_subdomains: bool,
) -> list[str]:
    soup = BeautifulSoup(html_text, "html.parser")
    out: list[str] = []
    seen: set[str] = set()

    for node in soup.find_all("a"):
        href = node.get("href")
        if not href:
            continue
        if href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue

        original_target = extract_original_from_wayback_url(href)
        if original_target is None:
            original_target = urljoin(page_original, href)
        if not is_same_site(original_target, domain, include_subdomains):
            continue

        key = canonical_url(original_target)
        if key in seen:
            continue
        seen.add(key)
        out.append(original_target)

    return out


def crawl_snapshots_from_seed(
    session: requests.Session,
    seed_wayback_url: str,
    domain: str,
    include_subdomains: bool,
    max_pages: int,
    timeout: int,
) -> list[Snapshot]:
    seed = extract_seed_snapshot(seed_wayback_url)
    if seed is None:
        raise ValueError(
            "--seed-wayback-url must be a valid web.archive.org /web/<timestamp>/ URL"
        )

    print(
        "[+] Seed crawl start: "
        f"{seed.original} @ {human_ts(seed.timestamp)} (max-pages={max_pages})"
    )

    queue: list[tuple[str, str]] = [(seed.original, seed.timestamp)]
    queued: set[str] = {canonical_url(seed.original)}
    visited: set[str] = set()
    snapshots: list[Snapshot] = []
    attempts = 0

    while queue and len(snapshots) < max_pages:
        original, ts = queue.pop(0)
        key = canonical_url(original)
        if key in visited:
            continue
        visited.add(key)
        attempts += 1

        if attempts == 1 or attempts % 20 == 0:
            print(
                "[+] Seed crawl progress: "
                f"downloaded={len(snapshots)} visited={len(visited)} queued={len(queue)}"
            )

        wayback_url = to_wayback_url(original, ts)
        try:
            resp = session.get(wayback_url, timeout=(10, timeout))
            resp.raise_for_status()
        except requests.RequestException as exc:
            if attempts <= 5 or attempts % 25 == 0:
                print(f"[!] Seed fetch failed for {original}: {exc}")
            continue

        content_type = (resp.headers.get("Content-Type") or "").lower()
        mimetype = content_type.split(";")[0].strip() if content_type else "text/html"
        snapshots.append(Snapshot(timestamp=ts, original=original, mimetype=mimetype))

        if "html" not in content_type:
            continue

        html_text = resp.text
        discovered = collect_seed_links(
            html_text=html_text,
            page_original=original,
            domain=domain,
            include_subdomains=include_subdomains,
        )
        for target in discovered:
            target_key = canonical_url(target)
            if target_key in queued or target_key in visited:
                continue
            queued.add(target_key)
            queue.append((target, ts))

    print(
        "[+] Seed crawl done: "
        f"downloaded={len(snapshots)} visited={len(visited)} remaining-queue={len(queue)}"
    )

    return snapshots


def canonical_url(url: str) -> str:
    split = urlsplit(url)
    return urlunsplit(
        (split.scheme.lower(), split.netloc.lower(), split.path, split.query, "")
    )


def is_same_site(url: str, domain: str, include_subdomains: bool) -> bool:
    host = (urlparse(url).hostname or "").lower()
    if host == domain:
        return True
    if include_subdomains and host.endswith(f".{domain}"):
        return True
    return False


def rewrite_html_links(
    html_text: str,
    page_original: str,
    page_local_path: Path,
    output_root: Path,
    local_map: dict[str, Path],
    domain: str,
    include_subdomains: bool,
) -> str:
    soup = BeautifulSoup(html_text, "html.parser")

    wayback_banner = soup.find(id="wm-ipp-base")
    if wayback_banner:
        wayback_banner.decompose()

    attributes = {
        "a": "href",
        "img": "src",
        "script": "src",
        "link": "href",
        "source": "src",
    }

    for tag_name, attr in attributes.items():
        for node in soup.find_all(tag_name):
            value = node.get(attr)
            if not value:
                continue
            if value.startswith(("#", "mailto:", "tel:", "javascript:")):
                continue

            original_target = extract_original_from_wayback_url(value)
            if original_target is None:
                original_target = urljoin(page_original, value)

            if not is_same_site(original_target, domain, include_subdomains):
                continue

            key = canonical_url(original_target)
            mapped = local_map.get(key)
            if not mapped:
                continue

            current = output_root / page_local_path
            target = output_root / mapped
            rel = os.path.relpath(target, start=current.parent)
            node[attr] = rel.replace("\\", "/")

    return str(soup)


def looks_like_blog_url(url: str, blog_path: str) -> bool:
    path = urlparse(url).path.lower()
    if blog_path:
        normalized = blog_path if blog_path.startswith("/") else f"/{blog_path}"
        return path.startswith(normalized.lower())
    return any(hint in path for hint in DEFAULT_BLOG_HINTS)


def looks_like_blog_post(url: str, blog_path: str) -> bool:
    path = urlparse(url).path.lower()
    if not looks_like_blog_url(url, blog_path):
        return False
    if any(
        part in path
        for part in ("/tag/", "/category/", "/author/", "/feed", "/wp-content/")
    ):
        return False
    if re.search(r"/\d{4}/\d{2}/", path):
        if re.search(r"/\d{4}/\d{2}/index\.html?$", path):
            return False
        if re.search(r"/\d{4}/\d{2}/[^/]+\.html?$", path):
            return True
        return True
    return bool(re.search(r"/(blog|posts?|articles?|news)/[^/]+/?$", path))


def infer_blog_path_from_url(url: str) -> str:
    path = urlparse(url).path.strip("/")
    if not path:
        return ""
    first = path.split("/")[0]
    if not first:
        return ""
    return f"/{first}"


def dedupe_snapshots(snapshots: list[Snapshot]) -> list[Snapshot]:
    deduped: dict[str, Snapshot] = {}
    for snapshot in snapshots:
        key = canonical_url(snapshot.original)
        existing = deduped.get(key)
        if not existing or snapshot.timestamp > existing.timestamp:
            deduped[key] = snapshot
    return list(deduped.values())


def extract_blog_post(local_html_path: Path) -> dict[str, str] | None:
    try:
        html_text = local_html_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None

    soup = BeautifulSoup(html_text, "html.parser")
    title_node = soup.find("h1") or soup.find("title")
    title = title_node.get_text(" ", strip=True) if title_node else "Untitled"

    body_node = soup.find("article") or soup.find("main") or soup.find("body")
    if not body_node:
        return None

    text = body_node.get_text("\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", text)
    if len(text) < 120:
        return None

    return {
        "title": title,
        "content": text,
    }


def write_blog_exports(posts: Iterable[dict[str, str]], output_root: Path) -> None:
    blog_dir = output_root / "blog_posts"
    blog_dir.mkdir(parents=True, exist_ok=True)

    post_list = list(posts)
    (blog_dir / "posts.json").write_text(
        json.dumps(post_list, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    for idx, post in enumerate(post_list, start=1):
        safe = sanitize_path_component(post["title"])[:80] or f"post_{idx}"
        md_path = blog_dir / f"{idx:04d}_{safe}.md"
        md_path.write_text(
            f"# {post['title']}\n\nSource: {post['source_url']}\n\n{post['content']}\n",
            encoding="utf-8",
        )


def main() -> int:
    args = parse_args()
    domain = normalize_domain(args.domain)

    if args.seed_wayback_url:
        seed = extract_seed_snapshot(args.seed_wayback_url)
        if seed is None:
            print("[!] --seed-wayback-url is not a valid Wayback snapshot URL")
            return 2
        seed_host = normalize_domain(urlparse(seed.original).netloc)
        if seed_host != domain and not seed_host.endswith(f".{domain}"):
            print(
                f"[!] Seed URL host ({seed_host}) does not match domain ({domain}). "
                "Proceeding with the seed host as source-of-truth."
            )
            domain = seed_host

    if args.snapshot_strategy == "nearest":
        if not args.target_date:
            print("[!] --target-date is required when --snapshot-strategy=nearest")
            return 2
        if not is_valid_wayback_timestamp(args.target_date):
            print("[!] --target-date must be YYYYMMDD or YYYYMMDDhhmmss")
            return 2

    run_label = time.strftime("%Y%m%d_%H%M%S")
    output_root = Path(args.output_dir) / f"{domain}_{run_label}"
    output_root.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers.update(
        {"User-Agent": "wayback-scraper/1.0 (+https://archive.org/)"}
    )

    try:
        earliest, latest = fetch_snapshot_boundaries(
            session=session,
            domain=domain,
            include_subdomains=args.include_subdomains,
            timeout=args.timeout,
            retries=args.retries,
        )
    except requests.RequestException as exc:
        earliest, latest = None, None
        print(f"[!] Could not fetch date range from CDX: {exc}")
    print(f"[+] Wayback availability range: {human_ts(earliest)} -> {human_ts(latest)}")

    print(
        f"[+] Looking up snapshots for {domain} (strategy={args.snapshot_strategy})..."
    )
    try:
        if args.seed_wayback_url:
            print("[+] Using seed-based crawl mode for primary site")
            snapshots = crawl_snapshots_from_seed(
                session=session,
                seed_wayback_url=args.seed_wayback_url,
                domain=domain,
                include_subdomains=args.include_subdomains,
                max_pages=args.max_pages,
                timeout=args.timeout,
            )
        else:
            snapshots = fetch_snapshots(
                session=session,
                domain=domain,
                include_subdomains=args.include_subdomains,
                max_pages=args.max_pages,
                from_year=args.from_year,
                to_year=args.to_year,
                strategy=args.snapshot_strategy,
                target_date=args.target_date,
                timeout=args.timeout,
                retries=args.retries,
            )

        if args.blog_seed_wayback_url:
            print("[+] Using additional seed-based crawl mode for blog host")
            blog_seed = extract_seed_snapshot(args.blog_seed_wayback_url)
            if blog_seed is None:
                print("[!] --blog-seed-wayback-url is not a valid Wayback snapshot URL")
                return 2
            blog_host = normalize_domain(urlparse(blog_seed.original).netloc)
            extra = crawl_snapshots_from_seed(
                session=session,
                seed_wayback_url=args.blog_seed_wayback_url,
                domain=blog_host,
                include_subdomains=True,
                max_pages=args.max_pages,
                timeout=args.timeout,
            )
            snapshots.extend(extra)
            snapshots = dedupe_snapshots(snapshots)
    except requests.RequestException as exc:
        print(f"[!] Failed to query CDX snapshots: {exc}")
        print("[!] Try increasing --timeout and/or --retries.")
        return 1
    except ValueError as exc:
        print(f"[!] {exc}")
        return 2

    if not snapshots:
        print("[!] No matching snapshots found.")
        return 1

    print(f"[+] Found {len(snapshots)} snapshots. Downloading...")

    local_map: dict[str, Path] = {}
    html_pages: list[tuple[str, Path]] = []
    metadata: list[dict[str, str]] = []

    for index, snapshot in enumerate(snapshots, start=1):
        target_rel = local_path_for_url(snapshot.original, snapshot.mimetype)
        target_abs = output_root / target_rel
        target_abs.parent.mkdir(parents=True, exist_ok=True)

        wayback_url = make_wayback_url(snapshot)
        try:
            resp = session.get(wayback_url, timeout=args.timeout)
            resp.raise_for_status()
        except requests.RequestException as exc:
            print(f"[!] ({index}/{len(snapshots)}) failed: {snapshot.original} ({exc})")
            continue

        target_abs.write_bytes(resp.content)

        key = canonical_url(snapshot.original)
        local_map[key] = target_rel
        metadata.append(
            {
                "timestamp": snapshot.timestamp,
                "original": snapshot.original,
                "wayback": wayback_url,
                "local_path": str(target_rel),
            }
        )

        content_type = resp.headers.get("Content-Type", snapshot.mimetype)
        if "html" in (content_type or "").lower():
            html_pages.append((snapshot.original, target_rel))

        if index % 25 == 0 or index == len(snapshots):
            print(f"[+] Downloaded {index}/{len(snapshots)}")
        time.sleep(max(args.delay, 0))

    print("[+] Rewriting internal links for offline browsing...")
    for original_url, rel_path in html_pages:
        html_file = output_root / rel_path
        try:
            html_text = html_file.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        rewritten = rewrite_html_links(
            html_text=html_text,
            page_original=original_url,
            page_local_path=rel_path,
            output_root=output_root,
            local_map=local_map,
            domain=domain,
            include_subdomains=args.include_subdomains,
        )
        html_file.write_text(rewritten, encoding="utf-8")

    if args.scrape_blog:
        print("[+] Extracting likely blog posts...")
        effective_blog_path = args.blog_path
        if not effective_blog_path and args.blog_seed_wayback_url:
            seed = extract_seed_snapshot(args.blog_seed_wayback_url)
            if seed:
                effective_blog_path = infer_blog_path_from_url(seed.original)
                if effective_blog_path:
                    print(f"[+] Inferred blog path: {effective_blog_path}")

        posts: list[dict[str, str]] = []
        for original_url, rel_path in html_pages:
            if not looks_like_blog_post(original_url, effective_blog_path):
                continue
            extracted = extract_blog_post(output_root / rel_path)
            if not extracted:
                continue
            extracted["source_url"] = original_url
            extracted["local_path"] = str(rel_path)
            posts.append(extracted)

        if posts:
            write_blog_exports(posts, output_root)
            print(
                f"[+] Exported {len(posts)} blog posts to {output_root / 'blog_posts'}"
            )
        else:
            print("[!] No blog posts matched the current heuristic.")

    (output_root / "snapshot_index.json").write_text(
        json.dumps(metadata, indent=2),
        encoding="utf-8",
    )

    print(f"[+] Done. Mirrored files are in: {output_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
