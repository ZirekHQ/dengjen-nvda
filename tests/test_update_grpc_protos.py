import importlib.metadata
import importlib.util
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import update_grpc_protos as protos


def test_proto_url_points_at_the_source_tag_for_the_version():
    assert protos.proto_url("2.0.3") == (
        "https://raw.githubusercontent.com/ZirekHQ/dengjen-tts/v2.0.3/"
        "crates/frontends/grpc/proto/dengjen_grpc.proto"
    )


def test_relativize_imports_rewrites_the_generated_absolute_import():
    source = "import grpc\n\nimport dengjen_grpc_pb2 as dengjen__grpc__pb2\n"
    assert protos.relativize_imports(source) == (
        "import grpc\n\nfrom . import dengjen_grpc_pb2 as dengjen__grpc__pb2\n"
    )


def test_relativize_imports_leaves_already_relative_imports_alone():
    source = "from . import dengjen_grpc_pb2 as dengjen__grpc__pb2\n"
    assert protos.relativize_imports(source) == source


def test_main_exits_with_an_install_hint_when_grpc_tools_is_missing(monkeypatch):
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)
    with pytest.raises(SystemExit, match="grpc_tools is not installed"):
        protos.main()


def _toolchain(monkeypatch, *, python, grpcio_tools):
    monkeypatch.setattr(protos.importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr(protos.importlib.metadata, "version", lambda name: grpcio_tools)
    monkeypatch.setattr(protos.sys, "version_info", python)


def test_accepts_the_pinned_toolchain(monkeypatch):
    _toolchain(monkeypatch, python=(3, 12, 0), grpcio_tools="1.62.3")
    protos._require_grpc_tools()


def test_rejects_another_grpcio_tools_version(monkeypatch):
    _toolchain(monkeypatch, python=(3, 12, 0), grpcio_tools="1.63.0")
    with pytest.raises(SystemExit, match="1.63.0"):
        protos._require_grpc_tools()


def test_rejects_python_3_13(monkeypatch):
    _toolchain(monkeypatch, python=(3, 13, 0), grpcio_tools="1.62.3")
    with pytest.raises(SystemExit, match="3.12 or older"):
        protos._require_grpc_tools()
