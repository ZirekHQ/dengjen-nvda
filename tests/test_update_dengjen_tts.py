import hashlib
import io
import json
import os
import sys
import zipfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import update_dengjen_tts as updater

DIGEST = "a" * 64


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


class TestLock:
    def test_round_trips(self, tmp_path):
        lock = tmp_path / "x.lock"
        updater.write_lock("2.0.3", DIGEST, lock)
        assert updater.read_lock(lock) == ("2.0.3", DIGEST)

    @pytest.mark.parametrize(
        "text",
        [
            "",
            "version = 2.0.3\n",
            f"sha256 = {DIGEST}\n",
            "version = v2\nsha256 = 00\n",
        ],
    )
    def test_rejects_incomplete_or_malformed_lock(self, tmp_path, text):
        lock = tmp_path / "x.lock"
        lock.write_text(text)
        with pytest.raises(SystemExit):
            updater.read_lock(lock)


class TestFetch:
    def _setup(self, tmp_path, payload):
        (tmp_path / "NOTICES").mkdir()
        lock = tmp_path / "x.lock"
        updater.write_lock("2.0.3", hashlib.sha256(payload).hexdigest(), lock)
        return lock, tmp_path, tmp_path / ".marker"

    def test_installs_binary_notice_and_marker(self, tmp_path, monkeypatch):
        payload = _zip({"dengjen-tts-grpc.exe": b"exe", "NOTICE": b"notice"})
        monkeypatch.setattr(updater, "_get", lambda _url: payload)
        lock, bin_dir, marker = self._setup(tmp_path, payload)
        updater.fetch(lock, bin_dir, marker)
        assert (bin_dir / "dengjen-tts-grpc.exe").read_bytes() == b"exe"
        assert (
            bin_dir / "NOTICES" / "COPYING - dengjen-tts-grpc"
        ).read_bytes() == b"notice"
        assert marker.exists()

    def test_second_fetch_skips_download(self, tmp_path, monkeypatch):
        payload = _zip({"dengjen-tts-grpc.exe": b"exe", "NOTICE": b"n"})
        calls = []
        monkeypatch.setattr(updater, "_get", lambda url: calls.append(url) or payload)
        lock, bin_dir, marker = self._setup(tmp_path, payload)
        updater.fetch(lock, bin_dir, marker)
        updater.fetch(lock, bin_dir, marker)
        assert len(calls) == 1

    def test_digest_mismatch_installs_nothing(self, tmp_path, monkeypatch):
        payload = _zip({"dengjen-tts-grpc.exe": b"exe", "NOTICE": b"n"})
        monkeypatch.setattr(updater, "_get", lambda _url: payload + b"tampered")
        lock, bin_dir, marker = self._setup(tmp_path, payload)
        with pytest.raises(SystemExit):
            updater.fetch(lock, bin_dir, marker)
        assert not (bin_dir / "dengjen-tts-grpc.exe").exists()
        assert not marker.exists()


class TestVerifyDigest:
    def test_matching_digest_passes(self):
        digest = "sha256:" + hashlib.sha256(b"abc").hexdigest()
        updater.verify_digest(b"abc", {"name": "a.zip", "digest": digest})

    def test_mismatched_digest_exits(self):
        with pytest.raises(SystemExit):
            updater.verify_digest(b"abc", {"name": "a.zip", "digest": "sha256:00"})

    @pytest.mark.parametrize(
        "asset", [{"name": "a.zip"}, {"name": "a.zip", "digest": None}]
    )
    def test_missing_digest_exits(self, asset):
        with pytest.raises(SystemExit):
            updater.verify_digest(b"abc", asset)


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

    def test_latest_skips_non_semver_tag_suffix(self, monkeypatch):
        releases = [
            _release("grpc-release-v2.1.0-rc1"),
            _release("grpc-release-v2.0.2"),
        ]
        monkeypatch.setattr(updater, "_get", lambda _url: json.dumps(releases))
        assert updater.fetch_release(None)["tag_name"] == "grpc-release-v2.0.2"

    def test_latest_pages_past_unrelated_releases(self, monkeypatch):
        page1 = [_release(f"java-v1.{i}.0") for i in range(100)]
        page2 = [_release("grpc-release-v2.0.2")]
        pages = {"&page=1": page1, "&page=2": page2}
        monkeypatch.setattr(
            updater,
            "_get",
            lambda url: json.dumps(next(v for k, v in pages.items() if k in url)),
        )
        assert updater.fetch_release(None)["tag_name"] == "grpc-release-v2.0.2"

    def test_latest_exits_when_no_release_qualifies(self, monkeypatch):
        monkeypatch.setattr(
            updater, "_get", lambda _url: json.dumps([_release("java-v1.0.0")])
        )
        with pytest.raises(SystemExit):
            updater.fetch_release(None)

    def test_explicit_version_requests_its_tag(self, monkeypatch):
        seen = []
        monkeypatch.setattr(
            updater,
            "_get",
            lambda url: seen.append(url) or json.dumps(_release("grpc-release-v1.2.3")),
        )
        updater.fetch_release("1.2.3")
        assert seen[0].endswith("/tags/grpc-release-v1.2.3")


class TestBump:
    def test_writes_lock_with_downloaded_zip_digest(self, tmp_path, monkeypatch):
        zip_bytes = b"zip"
        release = _release("grpc-release-v2.0.4")
        digest = "sha256:" + hashlib.sha256(zip_bytes).hexdigest()
        release["assets"][0]["digest"] = digest
        monkeypatch.setattr(updater, "fetch_release", lambda _v: release)
        monkeypatch.setattr(updater, "_get", lambda _url: zip_bytes)
        lock = tmp_path / "x.lock"
        updater.bump(None, lock)
        assert updater.read_lock(lock) == (
            "2.0.4",
            hashlib.sha256(zip_bytes).hexdigest(),
        )

    def test_release_without_digest_writes_no_lock(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            updater, "fetch_release", lambda _v: _release("grpc-release-v2.0.4")
        )
        monkeypatch.setattr(updater, "_get", lambda _url: b"zip")
        lock = tmp_path / "x.lock"
        with pytest.raises(SystemExit):
            updater.bump(None, lock)
        assert not lock.exists()


class TestMain:
    @pytest.mark.parametrize("bad", ["2.0", "v2.0.2", "2.0.2; rm -rf /", "latest"])
    def test_rejects_non_semver_version(self, bad):
        with pytest.raises(SystemExit):
            updater.main(["update_dengjen_tts.py", "bump", bad])

    def test_rejects_unknown_command(self):
        with pytest.raises(SystemExit):
            updater.main(["update_dengjen_tts.py", "install"])


class TestFetchReinstall:
    def test_missing_binary_is_refetched_despite_marker(self, tmp_path, monkeypatch):
        payload = _zip({"dengjen-tts-grpc.exe": b"exe", "NOTICE": b"n"})
        monkeypatch.setattr(updater, "_get", lambda _url: payload)
        (tmp_path / "NOTICES").mkdir()
        lock = tmp_path / "x.lock"
        updater.write_lock("2.0.3", hashlib.sha256(payload).hexdigest(), lock)
        marker = tmp_path / ".marker"
        updater.fetch(lock, tmp_path, marker)
        (tmp_path / "dengjen-tts-grpc.exe").unlink()
        updater.fetch(lock, tmp_path, marker)
        assert (tmp_path / "dengjen-tts-grpc.exe").read_bytes() == b"exe"
