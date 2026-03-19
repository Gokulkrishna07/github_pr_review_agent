import pytest

from agent.diff_parser import FileDiff, parse_pr_files, SKIP_EXTENSIONS


def _make_file(filename="main.py", patch="+ line1\n+ line2", status="added"):
    return {"filename": filename, "patch": patch, "status": status}


class TestParseSkipping:
    def test_removed_files_are_skipped(self):
        files = [_make_file(status="removed")]
        assert parse_pr_files(files, max_diff_lines=500) == []

    def test_files_without_patch_are_skipped(self):
        files = [{"filename": "image.png", "patch": None, "status": "added"}]
        assert parse_pr_files(files, max_diff_lines=500) == []

    def test_files_with_missing_patch_key_are_skipped(self):
        files = [{"filename": "main.py", "status": "added"}]
        assert parse_pr_files(files, max_diff_lines=500) == []

    @pytest.mark.parametrize("ext", [
        ".lock", ".sum", ".mod", ".min.js", ".min.css",
        ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg",
        ".woff", ".woff2", ".ttf", ".eot", ".pdf",
    ])
    def test_skip_extensions_are_excluded(self, ext):
        files = [_make_file(filename=f"somefile{ext}")]
        assert parse_pr_files(files, max_diff_lines=500) == []

    def test_lock_extension_skipped(self):
        files = [_make_file(filename="poetry.lock")]
        assert parse_pr_files(files, max_diff_lines=500) == []

    def test_package_lock_json_not_skipped(self):
        # package-lock.json ends in .json, not .lock, so it is NOT skipped.
        # This is a known limitation of the current extension-matching logic.
        files = [_make_file(filename="package-lock.json", patch="+ line")]
        result = parse_pr_files(files, max_diff_lines=500)
        assert len(result) == 1
        assert result[0].filename == "package-lock.json"


class TestLineLimitFiltering:
    def test_file_within_max_diff_lines_is_included(self):
        patch = "\n".join([f"+ line {i}" for i in range(10)])  # 10 lines
        files = [_make_file(patch=patch)]
        result = parse_pr_files(files, max_diff_lines=10)
        assert len(result) == 1

    def test_file_exceeding_max_diff_lines_is_excluded(self):
        patch = "\n".join([f"+ line {i}" for i in range(11)])  # 11 lines
        files = [_make_file(patch=patch)]
        result = parse_pr_files(files, max_diff_lines=10)
        assert result == []

    def test_line_count_is_newlines_plus_one(self):
        # A patch with 2 newlines has 3 lines.
        patch = "line1\nline2\nline3"
        files = [_make_file(patch=patch)]
        result = parse_pr_files(files, max_diff_lines=500)
        assert result[0].lines == 3

    def test_single_line_patch_has_line_count_one(self):
        patch = "+ only one line"
        files = [_make_file(patch=patch)]
        result = parse_pr_files(files, max_diff_lines=500)
        assert result[0].lines == 1

    def test_file_at_exactly_max_diff_lines_is_included(self):
        patch = "\n".join([f"+ line {i}" for i in range(5)])  # 5 lines
        files = [_make_file(patch=patch)]
        result = parse_pr_files(files, max_diff_lines=5)
        assert len(result) == 1


class TestFileDiffFields:
    def test_filediff_fields_populated_correctly(self):
        patch = "+ added line\n- removed line"
        files = [{"filename": "src/app.py", "patch": patch, "status": "modified"}]
        result = parse_pr_files(files, max_diff_lines=500)
        assert len(result) == 1
        diff = result[0]
        assert diff.filename == "src/app.py"
        assert diff.patch == patch
        assert diff.status == "modified"
        assert diff.lines == 2

    def test_filediff_is_correct_dataclass_type(self):
        files = [_make_file()]
        result = parse_pr_files(files, max_diff_lines=500)
        assert isinstance(result[0], FileDiff)


class TestMultipleFiles:
    def test_only_valid_files_returned_from_mixed_input(self):
        files = [
            _make_file(filename="valid.py", patch="+ code", status="added"),
            _make_file(filename="removed.py", status="removed"),
            {"filename": "binary.png", "patch": None, "status": "added"},
            _make_file(filename="deps.lock", patch="+ lock data"),
            _make_file(filename="also_valid.py", patch="+ more code", status="modified"),
        ]
        result = parse_pr_files(files, max_diff_lines=500)
        filenames = [r.filename for r in result]
        assert filenames == ["valid.py", "also_valid.py"]

    def test_empty_input_returns_empty_list(self):
        assert parse_pr_files([], max_diff_lines=500) == []

    def test_all_files_valid_returns_all(self):
        files = [
            _make_file(filename="a.py", patch="+ a"),
            _make_file(filename="b.py", patch="+ b"),
            _make_file(filename="c.py", patch="+ c"),
        ]
        result = parse_pr_files(files, max_diff_lines=500)
        assert len(result) == 3
        assert [r.filename for r in result] == ["a.py", "b.py", "c.py"]

    def test_missing_filename_key_defaults_to_empty_string(self):
        # Files with no filename key get "" which has no skip extension, so they pass
        # through if they have a patch and are not removed.
        files = [{"patch": "+ line", "status": "added"}]
        result = parse_pr_files(files, max_diff_lines=500)
        assert len(result) == 1
        assert result[0].filename == ""
