import pytest

from agent.diff_parser import FileDiff, parse_pr_files


def _file(filename, patch="@@ -1 +1 @@\n+line", status="added"):
    return {"filename": filename, "patch": patch, "status": status}


class TestParseSkipsRemovedFiles:
    def test_removed_file_is_skipped(self):
        files = [_file("main.py", status="removed")]
        assert parse_pr_files(files, 500) == []

    def test_modified_file_is_included(self):
        files = [_file("main.py", status="modified")]
        assert len(parse_pr_files(files, 500)) == 1


class TestParseSkipsBinaryFiles:
    def test_file_without_patch_is_skipped(self):
        files = [{"filename": "image.png", "status": "added"}]
        assert parse_pr_files(files, 500) == []

    def test_file_with_empty_patch_is_skipped(self):
        files = [{"filename": "main.py", "patch": None, "status": "added"}]
        assert parse_pr_files(files, 500) == []


class TestParseSkipsByExtension:
    @pytest.mark.parametrize("filename", [
        "package-lock.json",
        "go.sum",
        "go.mod",
        "bundle.min.js",
        "styles.min.css",
        "photo.png",
        "photo.jpg",
        "photo.jpeg",
        "icon.gif",
        "favicon.ico",
        "logo.svg",
        "font.woff",
        "font.woff2",
        "font.ttf",
        "font.eot",
        "doc.pdf",
    ])
    def test_skipped_extension(self, filename):
        files = [_file(filename)]
        assert parse_pr_files(files, 500) == []

    def test_python_file_is_included(self):
        files = [_file("main.py")]
        assert len(parse_pr_files(files, 500)) == 1

    def test_typescript_file_is_included(self):
        files = [_file("app.ts")]
        assert len(parse_pr_files(files, 500)) == 1


class TestParseRespectsMaxDiffLines:
    def test_file_within_limit_is_included(self):
        patch = "\n".join(["+line"] * 10)
        files = [_file("main.py", patch=patch)]
        assert len(parse_pr_files(files, 20)) == 1

    def test_file_exceeding_limit_is_skipped(self):
        patch = "\n".join(["+line"] * 100)
        files = [_file("main.py", patch=patch)]
        assert parse_pr_files(files, 50) == []

    def test_file_exactly_at_limit_is_included(self):
        patch = "\n".join(["+line"] * 10)
        line_count = patch.count("\n") + 1
        files = [_file("main.py", patch=patch)]
        assert len(parse_pr_files(files, line_count)) == 1


class TestParseReturnedFields:
    def test_returns_filediff_with_correct_fields(self):
        patch = "@@ -1 +1 @@\n+hello\n+world"
        files = [_file("app.py", patch=patch, status="modified")]
        result = parse_pr_files(files, 500)

        assert len(result) == 1
        assert isinstance(result[0], FileDiff)
        assert result[0].filename == "app.py"
        assert result[0].patch == patch
        assert result[0].status == "modified"
        assert result[0].lines == 3

    def test_multiple_files_all_returned(self):
        files = [_file("a.py"), _file("b.py"), _file("c.py")]
        result = parse_pr_files(files, 500)
        assert len(result) == 3
        assert [r.filename for r in result] == ["a.py", "b.py", "c.py"]

    def test_mixed_files_only_valid_returned(self):
        files = [
            _file("keep.py"),
            _file("skip.lock"),
            _file("removed.py", status="removed"),
            {"filename": "binary.png", "status": "added"},
            _file("keep2.ts"),
        ]
        result = parse_pr_files(files, 500)
        assert len(result) == 2
        assert result[0].filename == "keep.py"
        assert result[1].filename == "keep2.ts"
