import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from ggraft.errors import PullError
from ggraft.sources import Blob, McMeta

from tests.fixtures import Offline


class TestDownload(unittest.TestCase):
    def test_failed_download_leaves_no_base_and_no_staging(self):
        class Flaky(McMeta):
            calls = 0

            def _open(self, url):
                Flaky.calls += 1
                if Flaky.calls > 3:
                    raise RuntimeError("network drop")
                return b"data"

        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "base"
            blobs = [Blob("core/f%d.vsh" % i, 4) for i in range(10)]
            with self.assertRaises(RuntimeError):
                Flaky("r").download("tag", "src", blobs, dest)
            self.assertFalse(dest.exists())
            self.assertFalse(dest.with_name("base.partial").exists())

    def test_download_replaces_the_previous_contents(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "base"
            (dest / "core").mkdir(parents=True)
            (dest / "core" / "old.vsh").write_text("stale", encoding="utf-8")
            (dest / "loose.txt").write_text("stale", encoding="utf-8")

            Offline("r").download("tag", "src", [Blob("core/new.vsh", 4)], dest)

            self.assertEqual(
                sorted(p.relative_to(dest).as_posix() for p in dest.rglob("*") if p.is_file()),
                ["core/new.vsh"],
            )


    def test_a_file_or_symlink_where_the_base_belongs_is_replaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            as_file = Path(tmp) / "base"
            as_file.write_text("not a directory", encoding="utf-8")
            Offline("r").download("tag", "src", [Blob("core/new.vsh", 4)], as_file)
            self.assertTrue(as_file.is_dir())
            self.assertTrue((as_file / "core" / "new.vsh").is_file())

            outside = Path(tmp) / "elsewhere"
            outside.mkdir()
            (outside / "keep.vsh").write_text("keep", encoding="utf-8")
            link = Path(tmp) / "linked"
            link.symlink_to(outside)
            Offline("r").download("tag", "src", [Blob("core/new.vsh", 4)], link)
            self.assertFalse(link.is_symlink())
            # the link is replaced, never followed into someone else's directory
            self.assertTrue((outside / "keep.vsh").is_file())


class TestListing(unittest.TestCase):
    """The tree walk, with the two GitHub calls stubbed."""

    class Api(McMeta):
        """Stubs the bytes, so JSON decoding runs for real."""

        def __init__(self, recursive, walk=None):
            super().__init__("owner/repo")
            self.recursive = recursive
            self.walk = walk if walk is not None else {"tree": [
                {"path": "assets", "type": "tree", "sha": "s1"},
            ]}

        def _open(self, url):
            return json.dumps(self.recursive if "recursive=1" in url else self.walk).encode()

    def test_only_blobs_are_listed(self):
        blobs = self.Api({"tree": [
            {"path": "core/a.vsh", "type": "blob", "size": 12},
            {"path": "core", "type": "tree"},
        ]}).list_blobs("26.3-assets", "assets")
        self.assertEqual(blobs, [Blob("core/a.vsh", 12)])

    def test_a_truncated_tree_says_to_narrow_the_source(self):
        with self.assertRaises(PullError) as caught:
            self.Api({"tree": [], "truncated": True}).list_blobs("26.3-assets", "assets")
        self.assertIn("narrow base.source", str(caught.exception))

    def test_an_unknown_tag_points_at_the_version_number(self):
        class NoTag(McMeta):
            def _json(self, url):
                raise PullError("HTTP 404")

        with self.assertRaises(PullError) as caught:
            NoTag("owner/repo").list_blobs("99.9-assets", "assets")
        self.assertIn("check the version number", str(caught.exception))

    def test_a_missing_directory_is_named(self):
        api = self.Api({}, walk={"tree": [{"path": "data", "type": "tree", "sha": "s1"}]})
        with self.assertRaises(PullError) as caught:
            api.list_blobs("26.3-assets", "assets/minecraft")
        self.assertIn("no directory 'assets'", str(caught.exception))

    def test_a_failure_below_the_first_level_is_not_blamed_on_the_tag(self):
        class Deep(McMeta):
            def __init__(self):
                super().__init__("owner/repo")
                self.calls = 0

            def _json(self, url):
                self.calls += 1
                if self.calls == 1:
                    return {"tree": [{"path": "assets", "type": "tree", "sha": "s1"}]}
                raise PullError("HTTP 500")

        with self.assertRaises(PullError) as caught:
            Deep().list_blobs("26.3-assets", "assets/minecraft")
        self.assertIn("HTTP 500", str(caught.exception))
        self.assertNotIn("check the version number", str(caught.exception))

    def test_versions_strips_the_assets_suffix_and_ignores_other_tags(self):
        class Tags(McMeta):
            def _json(self, url):
                return [{"name": "26.3-assets"}, {"name": "26.2-assets"}, {"name": "summary"}]

        self.assertEqual(Tags("r").versions(), ["26.3", "26.2"])


class TestHttpErrors(unittest.TestCase):
    """PullError carries the hint; urllib exceptions never reach the user."""

    @staticmethod
    def _raising(exc):
        def urlopen(request, timeout=None):
            raise exc
        return mock.patch("ggraft.sources.mcmeta.urllib.request.urlopen", urlopen)

    def test_a_403_without_a_token_explains_the_rate_limit(self):
        with self._raising(urllib.error.HTTPError("u", 403, "rate", None, None)): # pyright: ignore[reportArgumentType]
            with self.assertRaises(PullError) as caught:
                McMeta("owner/repo")._open("https://x/y")
        self.assertIn("GITHUB_TOKEN", str(caught.exception))

    def test_a_403_with_a_token_is_reported_as_the_status(self):
        with self._raising(urllib.error.HTTPError("u", 403, "rate", None, None)): # pyright: ignore[reportArgumentType]
            with self.assertRaises(PullError) as caught:
                McMeta("owner/repo", token="t")._open("https://x/y")
        self.assertIn("HTTP 403", str(caught.exception))
        self.assertNotIn("GITHUB_TOKEN", str(caught.exception))

    def test_other_statuses_name_the_url(self):
        with self._raising(urllib.error.HTTPError("u", 404, "nf", None, None)): # pyright: ignore[reportArgumentType]
            with self.assertRaises(PullError) as caught:
                McMeta("owner/repo")._open("https://x/y")
        self.assertIn("https://x/y -> HTTP 404", str(caught.exception))

    def test_a_connection_failure_is_reported_as_its_reason(self):
        with self._raising(urllib.error.URLError("dns fail")):
            with self.assertRaises(PullError) as caught:
                McMeta("owner/repo")._open("https://x/y")
        self.assertIn("dns fail", str(caught.exception))
