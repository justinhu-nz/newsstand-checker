# NZ front-page availability monitor

This folder is ready to upload to the root of
[`justinhu-nz/nz-newsstand`](https://github.com/justinhu-nz/nz-newsstand).
It checks when each expected newspaper cover first becomes available from the
image endpoint already used by NZ Newsstand.

## Schedule

The workflow checks every half hour from **6:00 pm through 2:00 am New Zealand
time**, inclusive:

- 6:00 pm, 6:30 pm, ... 11:30 pm
- 12:00 am, 12:30 am, ... 1:30 am
- 2:00 am

The workflow declares `timezone: Pacific/Auckland`, so GitHub automatically
handles NZST and NZDT.

Before midnight the checker requests the following day's edition. After
midnight it requests the current day's edition. It uses the same lineups as the
web app:

- Monday-Friday: New Zealand Herald, The Post, The Press, Otago Daily Times
- Saturday: Weekend Herald, The Post, The Press, Otago Daily Times
- Sunday: Herald on Sunday, Sunday Star-Times

## Results

Each workflow run provides:

- a table in the GitHub Actions job summary
- a JSON observation file
- a CSV observation file
- HTTP status, content type, byte count, response time, and SHA-256 for each
  valid image

The JSON and CSV files are stored as a workflow artifact for 90 days. The
newspaper images themselves are **not** retained.

To estimate an upload window, compare consecutive checks. For example:

```text
10:30 pm — Not available (404)
11:00 pm — Available (200 image/jpeg)
```

This shows the page appeared between 10:30 pm and 11:00 pm. It does not prove
the exact server-side upload time.

## Installation

Upload these paths without changing their locations:

```text
.github/workflows/check-front-pages.yml
check_front_pages.py
FRONT_PAGE_MONITOR.md
.gitignore
```

The workflow must exist on the repository's default branch. Then open the
repository's **Actions** tab, select **Check NZ front pages**, and use **Run
workflow** once to confirm it works.

No repository secrets are required. The workflow has read-only repository
permissions.

## Manual checks

Run against the automatically selected upcoming edition:

```bash
python3 check_front_pages.py
```

Or specify an edition date:

```bash
python3 check_front_pages.py --edition-date 2026-08-22
```

Local results are written to `results/`.
