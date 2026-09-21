#!/usr/bin/env python3
"""Public Git-backed H1 regression matrix; no rejected review payloads."""
from __future__ import annotations

import re
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from test_autoreview_hardening import SCRIPT, git, init_repo, load_helper


REGEX = r'''text.replace(/([^\s"'<>?#]+)[?#][^\s"'<>]*/g, "$1");'''
COMPUTED = 'obj["cred" + "_secret"] = untrustedInput;'
PREFIX = "// public padding\n" * 12
SUFFIX = "// public tail\n" * 12


class VerifiedContextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.helper = load_helper()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = init_repo(Path(self.temp.name))

    def change(self, before: str | bytes, after: str | bytes, path="sample.ts") -> str:
        source = self.repo / path
        source.parent.mkdir(parents=True, exist_ok=True)
        for content, message in ((before, "before"), (after, "after")):
            source.write_bytes(content.encode() if isinstance(content, str) else content)
            git(self.repo, "add", "--", path)
            git(self.repo, "commit", "-q", "-m", message)
        return git(self.repo, "rev-parse", "HEAD^").strip()

    def fixture(self, *, prefix=PREFIX, suffix=SUFFIX, path="sample.ts") -> str:
        return self.change(prefix + "text;\n" + suffix,
                           prefix + REGEX + "\n" + suffix, path)

    def patch(self, base: str, *options: str) -> str:
        return subprocess.check_output(
            ["git", "diff", "--no-ext-diff", "--no-textconv", "--no-renames",
             *options, f"{base}...HEAD"], cwd=self.repo,
        ).decode("utf-8", errors="strict")

    def bundle(self, base: str, replacement: str | None = None) -> str:
        original_git = self.helper["git"]
        original_git_bytes = self.helper["git_bytes"]

        def read_git(repo, *args, **kwargs):
            if replacement is not None and args[0] == "diff" and "--patch" in args:
                return replacement
            return original_git(repo, *args, **kwargs)

        def read_git_bytes(repo, *args, **kwargs):
            if replacement is not None and args[0] == "diff" and "--patch" in args:
                return subprocess.CompletedProcess(args, 0, replacement.encode("utf-8"), b"")
            return original_git_bytes(repo, *args, **kwargs)

        with mock.patch.dict(self.helper["branch_bundle"].__globals__,
                             {"git": read_git, "git_bytes": read_git_bytes}):
            bundle, truncated = self.helper["branch_bundle"](self.repo, base)
        self.assertFalse(truncated)
        return bundle

    def assert_refused(self, base: str, replacement: str | None = None) -> None:
        with self.assertRaises(SystemExit):
            self.bundle(base, replacement)

    def clean_bundle(self, base: str, replacement: str | None = None) -> str:
        try:
            return self.bundle(base, replacement)
        except SystemExit as error:
            self.fail(f"verified public content was refused: {error}")

    def test_r1_verified_partial_regex_preserves_exact_patch(self) -> None:
        base = self.fixture()
        patch = self.patch(base)
        self.assertRegex(patch, r"@@ -10,")
        self.assertIn(patch, self.clean_bundle(base))

    def test_r1_javascript_crlf_multiple_hunks_and_no_final_newline(self) -> None:
        before = PREFIX + "text;\n" + SUFFIX + "text;"
        after = PREFIX + REGEX + "\n" + SUFFIX + REGEX
        base = self.change(before.replace("\n", "\r\n"),
                           after.replace("\n", "\r\n"), "sample.js")
        self.assertIn(self.patch(base), self.clean_bundle(base))

    def test_r3_full_context_control_stays_clean(self) -> None:
        base = self.fixture()
        patch = self.patch(base, "-U999")
        self.assertIn(patch, self.clean_bundle(base, patch))

    def test_n1_computed_assignment_rejected_partial_and_complete(self) -> None:
        base = self.change(PREFIX + "text;\n" + SUFFIX,
                           PREFIX + REGEX + "\n" + COMPUTED + "\n" + SUFFIX)
        self.assert_refused(base)
        self.assert_refused(base, self.patch(base, "-U999"))

    def test_n2_unbound_patch_and_missing_index_stay_rejected(self) -> None:
        base = self.fixture()
        patch = self.patch(base)
        with self.assertRaises(SystemExit):
            self.helper["validate_review_patch"]("unbound", ["sample.ts"], patch)
        self.assert_refused(base, re.sub(r"^index .*\n", "", patch, flags=re.M))

    def test_n3_wrong_blob_hunk_and_path_provenance_stay_rejected(self) -> None:
        base = self.fixture()
        patch = self.patch(base)
        old, new = re.search(r"^index ([0-9a-f]+)\.\.([0-9a-f]+)", patch, re.M).groups()
        for damaged in (
            patch.replace(f"{old}..{new}", f"{new}..{old}"),
            patch.replace(f"{old}..{new}", "1234567..7654321"),
            patch.replace("-text;", "-wrong;"),
            patch.replace("@@ -10,", "@@ -9,"),
            re.sub(r"(@@ -10,)\d+", r"\g<1>2", patch),
            patch.replace("--- a/sample.ts", "--- a/other.ts"),
            patch.replace("diff --git a/sample.ts", "diff --git a/other.ts"),
            patch.replace(" // public padding", " // tampered context"),
        ):
            if damaged == patch:
                continue
            with self.subTest(damage=damaged.splitlines()[0:3]):
                self.assert_refused(base, damaged)

    def test_n3_missing_eof_markers_stays_rejected(self) -> None:
        base = self.change(PREFIX + "text;", PREFIX + REGEX)
        patch = self.patch(base)
        self.assertIn("\\ No newline at end of file\n", patch)
        self.assert_refused(base, patch.replace("\\ No newline at end of file\n", ""))

    def test_n3_entire_after_blob_must_match_not_only_hunk_windows(self) -> None:
        base = self.fixture()
        patch = self.patch(base)
        source = self.repo / "sample.ts"
        source.write_text(source.read_text() + "// unrepresented change\n")
        git(self.repo, "add", "sample.ts")
        other = git(self.repo, "rev-parse", ":sample.ts").strip()
        patch = re.sub(r"(?m)^(index [0-9a-f]+\.\.)[0-9a-f]+", r"\g<1>" + other, patch)
        self.assert_refused(base, patch)

    def test_n3_omitted_hunk_fails_even_with_correct_tree_blob_ids(self) -> None:
        base = self.change(PREFIX + "text;\n" + SUFFIX + "before;\n",
                           PREFIX + REGEX + "\n" + SUFFIX + "after;\n")
        patch = self.patch(base)
        self.assertEqual(len(re.findall(r"^@@ ", patch, re.M)), 2)
        # Keep genuine tree/index identities and an applicable first hunk;
        # the changed tail must still be detected by full byte applicability.
        self.assert_refused(base, patch[:patch.rfind("\n@@ ") + 1])

    def test_n3_matching_alternate_blobs_not_in_reviewed_trees_stay_rejected(self) -> None:
        base = self.fixture()
        patch = self.patch(base)
        source = self.repo / "sample.ts"
        objects = []
        for line in ("text;", REGEX):
            source.write_text("// alternate context\n" + "// public padding\n" * 11
                              + line + "\n" + SUFFIX)
            git(self.repo, "add", "sample.ts")
            objects.append(git(self.repo, "rev-parse", ":sample.ts").strip())
        patched = re.sub(r"(?m)^index [0-9a-f]+\.\.[0-9a-f]+",
                         "index " + "..".join(objects), patch)
        # Both alternate blobs are genuine objects and the hunk can apply, but
        # neither is the blob at this path in the branch's reviewed trees.
        self.assert_refused(base, patched)

    def test_n4_real_inherited_string_with_computed_assignment_stays_rejected(self) -> None:
        prefix = "const doc = 'start\\\n" + "continued\\\n" * 12
        base = self.change(prefix + "end';\n" + SUFFIX,
                           prefix + "end'; " + COMPUTED + "\n" + REGEX + "\n" + SUFFIX)
        self.assert_refused(base)

    def test_n5_real_full_file_overflow_stays_rejected(self) -> None:
        base = self.fixture(suffix=SUFFIX + 'obj["unfinished\n')
        self.assert_refused(base)

    def test_visible_secret_change_on_either_side_stays_rejected(self) -> None:
        for side in ("before", "after"):
            with self.subTest(side=side):
                hidden = 'const api_key = "A7f9K2m4Q8v6N3x5R1p0T9z8";\n'
                before = (hidden if side == "before" else "// clean\n") + PREFIX + "text;\n" + SUFFIX
                after = (hidden if side == "after" else "// clean\n") + PREFIX + REGEX + "\n" + SUFFIX
                base = self.change(before, after)
                self.assert_refused(base)

    def test_unchanged_secret_outside_all_hunks_stays_rejected(self) -> None:
        synthetic = "A7f9K2m4Q8v6N3x5R1p0T9z8"
        # Put the unchanged credential after the hunk so Git's optional
        # function-context header cannot pull it into the visible patch.
        base = self.fixture(suffix=SUFFIX + 'const api_key = "' + synthetic + '";\n')
        self.assertNotIn(synthetic, self.patch(base))
        self.assert_refused(base)

    def test_n6_oversize_complete_blob_stays_rejected(self) -> None:
        base = self.fixture(prefix="// " + "x" * 180_001 + "\n" + PREFIX)
        self.assert_refused(base)

    def test_n6_too_many_context_lines_stays_rejected(self) -> None:
        base = self.fixture(prefix="\n" * 20_001 + PREFIX)
        self.assert_refused(base)

    def test_promisor_repository_cannot_supply_retry_context(self) -> None:
        base = self.fixture()
        # All objects exist: configuration itself must disable the H1 retry,
        # before Git could use a lazy-fetch path for any missing object.
        git(self.repo, "config", "remote.fixture.promisor", "true")
        git(self.repo, "config", "remote.fixture.url", "https://example.invalid/fixture")
        self.assert_refused(base)

    def test_promisor_ext_helper_and_included_config_never_execute(self) -> None:
        base = self.fixture()
        sentinel = Path(self.temp.name) / "remote-executed"
        remote = Path(self.temp.name) / "remote-helper"
        self.helper["write_executable"](remote, '#!/bin/sh\ntouch "$1"\nexit 77\n')
        git(self.repo, "config", "protocol.ext.allow", "always")
        git(self.repo, "config", "remote.fixture.url", f"ext::{remote} {sentinel}")
        for included in (False, True):
            with self.subTest(included=included):
                if included:
                    git(self.repo, "config", "--unset", "remote.fixture.promisor")
                    config = Path(self.temp.name) / "included-config"
                    config.write_text('[remote "fixture"]\n\tpromisor = true\n')
                    git(self.repo, "config", "include.path", str(config))
                else:
                    git(self.repo, "config", "remote.fixture.promisor", "true")
                self.assert_refused(base)
                self.assertFalse(sentinel.exists())

    def test_missing_partial_clone_blob_is_refused_before_object_queries(self) -> None:
        base = self.fixture()
        patch = self.patch(base)
        oid = git(self.repo, "rev-parse", "HEAD:sample.ts").strip()
        (self.repo / ".git" / "objects" / oid[:2] / oid[2:]).unlink()
        git(self.repo, "config", "extensions.partialClone", "fixture")
        git(self.repo, "config", "remote.fixture.promisor", "true")
        sentinel = Path(self.temp.name) / "remote-executed"
        remote = Path(self.temp.name) / "remote-helper"
        self.helper["write_executable"](remote, '#!/bin/sh\ntouch "$1"\nexit 77\n')
        git(self.repo, "config", "protocol.ext.allow", "always")
        git(self.repo, "config", "remote.fixture.url", f"ext::{remote} {sentinel}")
        commands = []
        original = self.helper["git_bytes"]

        def read(repo, *args, **kwargs):
            commands.append(args)
            return original(repo, *args, **kwargs)

        with mock.patch.dict(self.helper["validate_review_patch"].__globals__, {"git_bytes": read}):
            with self.assertRaises(SystemExit):
                self.helper["validate_review_patch"](
                    "missing object", ["sample.ts"], patch,
                    git_context=(self.repo, base, "HEAD"),
                )
        self.assertEqual(len(commands), 1)
        self.assertEqual(commands[0][0:2], ("config", "--includes"))
        self.assertFalse(sentinel.exists())

    def test_bounded_git_reader_rejects_oversize_without_returning_prefix(self) -> None:
        self.fixture()
        oid = git(self.repo, "rev-parse", "HEAD:sample.ts").strip()
        result = self.helper["git_bytes"](
            self.repo, "cat-file", "blob", oid, check=False, max_output_bytes=8,
        )
        self.assertNotIn(result.returncode, (0, 1))
        self.assertEqual(result.stdout, b"")
        self.assertEqual(result.stderr, b"")

    @unittest.skipIf(os.name == "nt", "H1 fails closed without POSIX process ownership")
    def test_bounded_git_timeout_kills_owned_descendant_and_cannot_mean_no_config(self) -> None:
        fake = Path(self.temp.name) / "hung-git"
        sentinel = Path(self.temp.name) / "descendant-survived"
        child = f"import time; from pathlib import Path; time.sleep(7); Path({str(sentinel)!r}).touch()"
        self.helper["write_executable"](
            fake,
            f"#!{sys.executable}\nimport subprocess, sys, time\n"
            f"subprocess.Popen([sys.executable, '-c', {child!r}])\n"
            "time.sleep(60)\n",
        )
        with mock.patch.dict(self.helper["git_bytes"].__globals__,
                             {"resolve_command": lambda *_: str(fake)}):
            started = time.monotonic()
            result = self.helper["git_bytes"](
                self.repo, "config", check=False, max_output_bytes=32,
            )
        self.assertLess(time.monotonic() - started, 7)
        self.assertNotIn(result.returncode, (0, 1))
        self.assertEqual(result.stdout, b"")
        time.sleep(2.5)
        self.assertFalse(sentinel.exists())

    def test_missing_blob_never_contacts_real_loopback_promisor_endpoint(self) -> None:
        base = self.fixture()
        patch = self.patch(base)
        oid = git(self.repo, "rev-parse", "HEAD:sample.ts").strip()
        (self.repo / ".git" / "objects" / oid[:2] / oid[2:]).unlink()
        git(self.repo, "config", "extensions.partialClone", "fixture")
        git(self.repo, "config", "remote.fixture.promisor", "true")
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            listener.settimeout(0.2)
            port = listener.getsockname()[1]
            git(self.repo, "config", "remote.fixture.url", f"http://127.0.0.1:{port}/fixture")
            git(self.repo, "config", "protocol.http.allow", "always")
            with self.assertRaises(SystemExit):
                self.helper["validate_review_patch"](
                    "missing object", ["sample.ts"], patch,
                    git_context=(self.repo, base, "HEAD"),
                )
            # Exercise the real Git reader too: transport denial must hold even
            # independently of the earlier config refusal. No mock Git binary.
            result = self.helper["git_bytes"](
                self.repo, "cat-file", "blob", oid, check=False, max_output_bytes=1024,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, b"")
            connections = 0
            while True:
                try:
                    connection, _address = listener.accept()
                except socket.timeout:
                    break
                connection.close()
                connections += 1
            self.assertEqual(connections, 0, "Git contacted the synthetic promisor endpoint")

    def test_optional_socket_trace_of_successful_acquisition(self) -> None:
        # Redundant instrumentation when available; the mandatory loopback and
        # ext-helper tests above verify both boundaries with the real Git binary.
        trace_tool = shutil.which("strace")
        if trace_tool is None:
            self.skipTest("optional strace unavailable; real loopback/ext tests cover no-fetch")
        base = self.fixture()
        patch_file = Path(self.temp.name) / "public.patch"
        patch_file.write_bytes(self.patch(base).encode())
        trace = Path(self.temp.name) / "network.trace"
        code = (
            "import runpy,sys; from pathlib import Path; "
            "h=runpy.run_path(sys.argv[1],run_name='guard_test'); "
            "h['validate_review_patch']('public',['sample.ts'],Path(sys.argv[4]).read_text(),"
            "git_context=(Path(sys.argv[2]),sys.argv[3],'HEAD'))"
        )
        result = subprocess.run(
            [trace_tool, "-f", "-e", "trace=network", "-o", str(trace),
             sys.executable, "-c", code, str(SCRIPT), str(self.repo), base, str(patch_file)],
            capture_output=True, text=True,
        )
        if "ptrace" in result.stderr and "not permitted" in result.stderr:
            self.skipTest("optional ptrace disallowed; real loopback/ext tests cover no-fetch")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotRegex(trace.read_text(), r"\b(?:socket|connect|sendto|sendmsg)\(")

    def test_n6_binary_and_non_utf8_context_stay_rejected(self) -> None:
        for invalid in (b"\x00", b"\xff"):
            with self.subTest(invalid=invalid):
                base = self.change(invalid + b"\n" + (PREFIX + "text;\n" + SUFFIX).encode(),
                                   invalid + b"\n" + (PREFIX + REGEX + "\n" + SUFFIX).encode())
                self.assert_refused(base)


if __name__ == "__main__":
    unittest.main()
