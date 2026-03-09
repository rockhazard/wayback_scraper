# Wayback Scraper

Download and reconstruct archived websites from the Internet Archive Wayback Machine.

This tool can:
- mirror a site from Wayback snapshots,
- choose per-URL capture timing (`latest`, `earliest`, `nearest`),
- crawl from a specific archived page URL,
- extract likely blog posts to JSON and Markdown.

## Quick Start

### 1) Create and activate a virtualenv

Linux/macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Windows (PowerShell):

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 2) Simple usage

```bash
python wayback_scraper.py example.com
```

### 3) If Wayback is slow

```bash
python wayback_scraper.py example.com --timeout 60 --retries 5
```

## How It Works

The scraper queries Wayback's CDX API for archived URLs, downloads archived content,
and writes files into a local mirror directory.

For HTML files, internal links are rewritten so the mirror is browsable offline.

Because Wayback can store pages/assets at different timestamps, the snapshot strategy
matters for fidelity.

## Core Usage

### Basic mirror

```bash
python wayback_scraper.py example.com
```

### Include subdomains

```bash
python wayback_scraper.py example.com --include-subdomains --max-pages 1200
```

### Constrain archive years

```bash
python wayback_scraper.py example.com --from-year 2015 --to-year 2021
```

### Snapshot strategies

Latest capture per URL (default):

```bash
python wayback_scraper.py example.com --snapshot-strategy latest
```

Earliest capture per URL:

```bash
python wayback_scraper.py example.com --snapshot-strategy earliest
```

Nearest capture per URL to a target date:

```bash
python wayback_scraper.py example.com --snapshot-strategy nearest --target-date 20190615
```

`--target-date` accepts:
- `YYYYMMDD`
- `YYYYMMDDhhmmss`

## Blog Scraping Usage

### Heuristic blog extraction from mirrored pages

```bash
python wayback_scraper.py example.com --scrape-blog
```

### Force a known blog path

```bash
python wayback_scraper.py example.com --scrape-blog --blog-path /blog
```

### Seed from an exact archived home/blog page

```bash
python wayback_scraper.py e-piphanies.com \
  --seed-wayback-url "https://web.archive.org/web/20260208201712/http://e-piphanies.com/" \
  --scrape-blog --max-pages 1500
```

### Blog hosted on a different domain (important)

If the site points to an external blog host (for example Typepad, Substack,
WordPress.com, Blogger), provide both seeds:

```bash
python wayback_scraper.py e-piphanies.com \
  --seed-wayback-url "https://web.archive.org/web/20260208201712/http://e-piphanies.com/" \
  --blog-seed-wayback-url "https://web.archive.org/web/20250910155122/https://ronpogue.typepad.com/e-piphanies/2025/03/index.html" \
  --scrape-blog --blog-path /e-piphanies --max-pages 2000 --timeout 60 --retries 5
```

### Why blog scraping can miss posts

Common reasons:
- blog is on a different host than the main domain,
- monthly archive/index pages are captured but post pages are sparse,
- links in archived HTML are rewritten/non-standard,
- captured pages are thin or mostly script-driven.

When that happens, provide `--blog-seed-wayback-url` and/or `--blog-path`.

## Useful CLI Options

- `domain`: base domain to mirror (required)
- `--seed-wayback-url`: start crawl from an exact Wayback URL
- `--blog-seed-wayback-url`: extra seed for off-domain blog host
- `--snapshot-strategy`: `latest` | `earliest` | `nearest`
- `--target-date`: required for `nearest`
- `--max-pages`: cap number of fetched pages
- `--timeout`: read timeout in seconds
- `--retries`: retries for CDX API calls
- `--include-subdomains`: include subdomains in CDX host/domain matching
- `--scrape-blog`: enable blog extraction
- `--blog-path`: narrow blog matching (for example `/e-piphanies`)

## Output Layout

Each run writes to a timestamped folder under `output/`, for example:

`output/example.com_20260309_120000/`

Contents include:
- mirrored site files,
- `snapshot_index.json` (timestamp/original/local mapping),
- `blog_posts/posts.json` (if blog extraction finds posts),
- `blog_posts/*.md` (one Markdown file per extracted post).

## Windows Executable (No Python Required On Target Machine)

### Option A: Build directly on Windows

On a Windows build machine:

```bat
build_windows_exe.bat
```

Result:
- `dist\wayback_scraper.exe`

You can copy just that `.exe` to another Windows machine and run it without
installing Python.

### Option B: Build Windows exe with GitHub Actions

This repository includes a workflow at
`.github/workflows/build-windows-exe.yml`.

Run it from GitHub Actions, then download the `wayback_scraper-windows-exe`
artifact. The artifact contains `wayback_scraper.exe` for Windows hosts.

## Troubleshooting

Read timeout / slow CDX:

```bash
python wayback_scraper.py example.com --timeout 90 --retries 6
```

No blog posts matched:
- add `--blog-seed-wayback-url` with a known archived post/month URL,
- add `--blog-path` for the real blog path,
- increase `--max-pages`.

Seed crawl appears stuck:
- newer versions print seed crawl progress (`downloaded/visited/queued`),
- reduce `--max-pages` first to validate behavior, then increase.
