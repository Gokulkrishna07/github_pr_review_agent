from dataclasses import dataclass

SKIP_EXTENSIONS = {
    ".lock", ".sum", ".mod", ".min.js", ".min.css",
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg",
    ".woff", ".woff2", ".ttf", ".eot", ".pdf",
}


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
            continue

        # Skip binary files (no patch)
        if not patch:
            continue

        # Skip by extension
        if any(filename.endswith(ext) for ext in SKIP_EXTENSIONS):
            continue

        line_count = patch.count("\n") + 1
        if line_count > max_diff_lines:
            continue

        results.append(FileDiff(
            filename=filename,
            patch=patch,
            status=status,
            lines=line_count,
        ))
    return results
