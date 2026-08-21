#!/usr/bin/env python3
"""Check whether the expected NZ newspaper front pages are available."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


NZ_TIMEZONE = ZoneInfo("Pacific/Auckland")
IMAGE_ENDPOINT = "https://t.prcdn.co/img"
REQUEST_TIMEOUT_SECONDS = 30
MINIMUM_IMAGE_BYTES = 1_000

EDITION_CONFIG = {
    "weekday": (
        ("1126", "New Zealand Herald"),
        ("1022", "The Post"),
        ("1272", "The Press"),
        ("9hym", "Otago Daily Times"),
    ),
    "saturday": (
        ("7478", "Weekend Herald"),
        ("1022", "The Post"),
        ("1272", "The Press"),
        ("9hym", "Otago Daily Times"),
    ),
    "sunday": (
        ("1211", "Herald on Sunday"),
        ("1543", "Sunday Star-Times"),
    ),
}


@dataclass(frozen=True)
class Observation:
    requested_at_utc: str
    requested_at_nz: str
    edition_date: str
    day_group: str
    edition_id: str
    title: str
    url: str
    available: bool
    status_code: int | None
    content_type: str
    content_length: int
    sha256: str
    duration_ms: int
    error: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check the front pages configured by NZ Newsstand."
    )
    parser.add_argument(
        "--edition-date",
        type=date.fromisoformat,
        help="NZ edition date in YYYY-MM-DD form. Defaults to the upcoming edition.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("results"),
        help="Directory for JSON and CSV observations (default: results).",
    )
    return parser.parse_args()


def default_edition_date(now_nz: datetime) -> date:
    """Select tomorrow before midnight and today after midnight.

    The scheduled monitoring window crosses midnight. At 6 pm through 11:59 pm
    the upcoming papers carry tomorrow's date; from midnight onward they carry
    today's date.
    """

    if now_nz.hour >= 18:
        return now_nz.date() + timedelta(days=1)
    return now_nz.date()


def day_group_for(edition_date: date) -> str:
    if edition_date.weekday() == 5:
        return "saturday"
    if edition_date.weekday() == 6:
        return "sunday"
    return "weekday"


def build_front_page_url(edition_id: str, edition_date: date) -> str:
    issue_date = edition_date.strftime("%Y%m%d")
    file_id = f"{edition_id}{issue_date}00000000001001"
    return f"{IMAGE_ENDPOINT}?file={file_id}&page=1&scale=100"


def looks_like_image(data: bytes) -> bool:
    return (
        data.startswith(b"\xff\xd8\xff")
        or data.startswith(b"\x89PNG\r\n\x1a\n")
        or data.startswith((b"GIF87a", b"GIF89a"))
        or (len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP")
    )


def iso_seconds(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def check_edition(
    edition_date: date,
    day_group: str,
    edition_id: str,
    title: str,
) -> Observation:
    url = build_front_page_url(edition_id, edition_date)
    requested_utc = datetime.now(timezone.utc)
    requested_nz = requested_utc.astimezone(NZ_TIMEZONE)
    started = time.monotonic()
    status_code: int | None = None
    content_type = ""
    data = b""
    error = ""

    try:
        request = Request(
            url,
            headers={
                "Accept": "image/avif,image/webp,image/png,image/jpeg,image/*;q=0.8,*/*;q=0.1",
                "User-Agent": "nz-newsstand-front-page-monitor/1.0",
            },
            method="GET",
        )
        with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            status_code = response.status
            content_type = response.headers.get_content_type()
            data = response.read()
    except HTTPError as exc:
        status_code = exc.code
        content_type = exc.headers.get_content_type() if exc.headers else ""
        error = f"HTTP {exc.code} {exc.reason}"
    except (URLError, TimeoutError, OSError) as exc:
        error = f"{type(exc).__name__}: {exc}"

    duration_ms = round((time.monotonic() - started) * 1_000)
    valid_image = looks_like_image(data)
    available = (
        status_code == 200
        and content_type.startswith("image/")
        and len(data) >= MINIMUM_IMAGE_BYTES
        and valid_image
    )

    if status_code == 200 and not available and not error:
        error = "Response was not a valid image"

    return Observation(
        requested_at_utc=iso_seconds(requested_utc),
        requested_at_nz=iso_seconds(requested_nz),
        edition_date=edition_date.isoformat(),
        day_group=day_group,
        edition_id=edition_id,
        title=title,
        url=url,
        available=available,
        status_code=status_code,
        content_type=content_type,
        content_length=len(data),
        sha256=hashlib.sha256(data).hexdigest() if available else "",
        duration_ms=duration_ms,
        error=error,
    )


def write_results(
    observations: list[Observation], output_dir: Path, run_time: datetime
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = run_time.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_path = output_dir / f"front-pages-{timestamp}.json"
    csv_path = output_dir / f"front-pages-{timestamp}.csv"
    rows = [asdict(observation) for observation in observations]

    json_path.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    return json_path, csv_path


def markdown_summary(observations: Iterable[Observation]) -> str:
    observations = list(observations)
    available_count = sum(item.available for item in observations)
    lines = [
        "## NZ front-page check",
        "",
        f"Edition date: **{observations[0].edition_date}** "
        f"({observations[0].day_group})",
        "",
        "| Publication | Result | HTTP | Type | Bytes | Checked (NZ) |",
        "|---|---:|---:|---|---:|---|",
    ]
    for item in observations:
        result = "Available" if item.available else "Not available"
        status = item.status_code if item.status_code is not None else "—"
        content_type = item.content_type or "—"
        lines.append(
            f"| {item.title} | {result} | {status} | {content_type} | "
            f"{item.content_length} | {item.requested_at_nz} |"
        )
    lines.extend(
        [
            "",
            f"**{available_count}/{len(observations)} front pages available.**",
            "",
            "The upload window is bounded by the last `Not available` check and "
            "the first `Available` check; the observation is not the server's exact upload time.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    args = parse_args()
    run_time = datetime.now(timezone.utc)
    now_nz = run_time.astimezone(NZ_TIMEZONE)
    edition_date = args.edition_date or default_edition_date(now_nz)
    day_group = day_group_for(edition_date)
    editions = EDITION_CONFIG[day_group]

    with ThreadPoolExecutor(max_workers=len(editions)) as executor:
        observations = list(
            executor.map(
                lambda edition: check_edition(
                    edition_date, day_group, edition[0], edition[1]
                ),
                editions,
            )
        )

    json_path, csv_path = write_results(observations, args.output_dir, run_time)
    summary = markdown_summary(observations)
    print(summary)
    print(f"JSON: {json_path}")
    print(f"CSV:  {csv_path}")

    github_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if github_summary:
        with open(github_summary, "a", encoding="utf-8") as handle:
            handle.write(summary)

    return 0


if __name__ == "__main__":
    sys.exit(main())

