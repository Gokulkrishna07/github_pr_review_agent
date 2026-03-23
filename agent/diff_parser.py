import logging
from dataclasses import dataclass

from .metrics import files_skipped_total

logger = logging.getLogger(__name__)

SKIP_SUFFIXES = (
    ".lock", ".sum", ".mod", ".min.js", ".min.css",
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg",
    ".woff", ".woff2", ".ttf", ".eot", ".pdf",
)


@dataclass
class FileDiff:
    filename: str
    patch: str
    status: str
    lines: int = 0


def parse_pr_files(files: list[dict], max_diff_lines: int) -> list[FileDiff]:
    """Parse GitHub PR files response into FileDiff objects, filtering out
    binary files, lock files, and files exceeding max_diff_lines."""
    results: list[FileDiff] = []
    for f in files:
        filename = f.get("filename", "")
        patch = f.get("patch")
        status = f.get("status", "")

        # Skip removed files
        if status == "removed":
            logger.debug("Skipping removed file: %s", filename)
            files_skipped_total.labels(reason="removed").inc()
            continue

        # Skip binary files (no patch)
        if not patch:
            logger.debug("Skipping file with no patch (binary): %s", filename)
            files_skipped_total.labels(reason="no_patch").inc()
            continue

        # Skip by extension
        if filename.endswith(SKIP_SUFFIXES):
            logger.debug("Skipping file by extension: %s", filename)
            files_skipped_total.labels(reason="extension").inc()
            continue

        line_count = patch.count("\n") + 1
        if line_count > max_diff_lines:
            logger.info("Skipping file exceeding max_diff_lines (%d > %d): %s", line_count, max_diff_lines, filename)
            files_skipped_total.labels(reason="too_large").inc()
            continue

        results.append(FileDiff(
            filename=filename,
            patch=patch,
            status=status,
            lines=line_count,
        ))
    return results
