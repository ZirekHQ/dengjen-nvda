import hashlib
import io
import json
import os
import sys
import zipfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import update_dengjen_tts as updater


def _zip(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, content in files.items():
            z.writestr(name, content)
    return buf.getvalue()


def _release(tag, draft=False, prerelease=False):
    asset = {"name": f"x-{tag}-windows-x64.zip", "browser_download_url": "u"}
    return {
        "tag_name": tag,
        "draft": draft,
        "prerelease": prerelease,
        "assets": [asset],
    }


class TestInstall:
    def test_writes_binary_and_notice(self, tmp_path):
        (tmp_path / "NOTICES").mkdir()
        data = _zip({"dengjen-tts-grpc.exe": b"exe", "NOTICE": b"notice"})
        updater.install(data, tmp_path)
        assert (tmp_path / "dengjen-tts-grpc.exe").read_bytes() == b"exe"
        notice = tmp_path / "NOTICES" / "COPYING - dengjen-tts-grpc"
        assert notice.read_bytes() == b"notice"


class TestVerifyDigest:
    def test_matching_digest_passes(self):
        digest = "sha256:" + hashlib.sha256(b"abc").hexdigest()
        updater.verify_digest(b"abc", {"name": "a.zip", "digest": digest})

    def test_mismatched_digest_exits(self):
        with pytest.raises(SystemExit):
            updater.verify_digest(b"abc", {"name": "a.zip", "digest": "sha256:00"})

    def test_missing_digest_is_accepted(self):
        updater.verify_digest(b"abc", {"name": "a.zip"})


class TestFetchRelease:
    def test_latest_skips_other_tags_drafts_and_prereleases(self, monkeypatch):
        releases = [
            _release("java-v2.0.3"),
            _release("grpc-release-v2.1.0-beta.1", prerelease=True),
            _release("grpc-release-v2.0.9", draft=True),
            _release("grpc-release-v2.0.2"),
        ]
        monkeypatch.setattr(updater, "_get", lambda _url: json.dumps(releases))
        assert updater.fetch_release(None)["tag_name"] == "grpc-release-v2.0.2"

    def test_explicit_version_requests_its_tag(self, monkeypatch):
        seen = []
        monkeypatch.setattr(
            updater,
            "_get",
            lambda url: seen.append(url) or json.dumps(_release("grpc-release-v1.2.3")),
        )
        updater.fetch_release("1.2.3")
        assert seen[0].endswith("/tags/grpc-release-v1.2.3")


class TestMain:
    @pytest.mark.parametrize("bad", ["2.0", "v2.0.2", "2.0.2; rm -rf /", "latest"])
    def test_rejects_non_semver_version(self, bad):
        with pytest.raises(SystemExit):
            updater.main(["update_dengjen_tts.py", bad])
