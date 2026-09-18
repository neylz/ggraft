from __future__ import annotations

import json
import shutil
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from ggraft.errors import PullError

API = "https://api.github.com"
RAW = "https://raw.githubusercontent.com"
USER_AGENT = "ggraft"


def _clear(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    elif path.is_symlink() or path.exists():
        path.unlink()


@dataclass
class Blob:
    path: str   # relative to the source root, e.g. "core/terrain.vsh"
    size: int


class McMeta:
    """Read-only client for one mcmeta repository."""

    def __init__(self, repo: str, token: str | None = None, timeout: int = 30) -> None:
        self.repo = repo
        self.token = token
        self.timeout = timeout


    def _open(self, url: str) -> bytes:
        headers = {"User-Agent": USER_AGENT}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 403 and not self.token:
                raise PullError(
                    "Rejected request (rate limit). Set GITHUB_TOKEN "
                    "or pass --token to raise the limit."
                ) from exc
            raise PullError(f"{url} -> HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise PullError(f"{url} -> {exc.reason}") from exc

    def _json(self, url: str):
        return json.loads(self._open(url))


    @staticmethod
    def tag_for(version: str) -> str:
        return f"{version}-assets"

    def versions(self, limit: int = 100) -> list[str]:
        tags = self._json(f"{API}/repos/{self.repo}/tags?per_page={limit}")
        return [t["name"][: -len("-assets")] for t in tags if t["name"].endswith("-assets")]


    def _subtree_sha(self, tag: str, path: str) -> str:
        # one level at a time; the full assets tree is too big to list at once
        sha = tag
        walked: list[str] = []
        for part in path.split("/"):
            try:
                entries = self._json(f"{API}/repos/{self.repo}/git/trees/{sha}")["tree"]
            except PullError as exc:
                if not walked:
                    raise PullError(
                        f"no such tag {tag!r} in {self.repo}. check the version number"
                    ) from exc
                raise
            match = next((e for e in entries if e["path"] == part and e["type"] == "tree"), None)
            if match is None:
                joined = "/".join([*walked, part])
                raise PullError(f"{tag}: no directory {joined!r} in {self.repo}")
            sha = match["sha"]
            walked.append(part)
        return sha

    def list_blobs(self, tag: str, source: str) -> list[Blob]:
        sha = self._subtree_sha(tag, source)
        tree = self._json(f"{API}/repos/{self.repo}/git/trees/{sha}?recursive=1")
        if tree.get("truncated"):
            raise PullError(
                f"{source} tree was truncated by the API; narrow base.source and retry"
            )
        return [Blob(path=e["path"], size=e.get("size", 0))
                for e in tree["tree"] if e["type"] == "blob"]


    def download(self, tag: str, source: str, blobs: list[Blob], dest: Path, workers: int = 8) -> int:
        # staged in a sibling dir and swapped in only once every file has
        # arrived, so an interrupted pull leaves no partial base
        staging = dest.with_name(dest.name + ".partial")
        _clear(staging)
        staging.mkdir(parents=True)

        def fetch(blob: Blob) -> None:
            data = self._open(f"{RAW}/{self.repo}/{tag}/{source}/{blob.path}")
            target = staging / blob.path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)

        try:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                # list() forces the iterator so exceptions surface here
                list(pool.map(fetch, blobs))
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise

        _clear(dest)
        staging.replace(dest)
        return len(blobs)
