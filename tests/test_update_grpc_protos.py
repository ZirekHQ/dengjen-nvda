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


def _stub_generation(monkeypatch, tmp_path, generated):
    monkeypatch.setattr(protos, "PROTO_DIR", tmp_path)
    monkeypatch.setattr(protos.importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr(protos, "read_lock", lambda: ("1.2.3", "digest"))
    monkeypatch.setattr(protos, "_get", lambda url: b"syntax = 'proto3';")
    monkeypatch.setattr(
        protos,
        "_run_protoc",
        lambda proto_file: (tmp_path / "dengjen_grpc_pb2.py").write_text(generated),
    )


def test_main_rejects_gencode_from_another_protobuf_line(monkeypatch, tmp_path):
    _stub_generation(monkeypatch, tmp_path, "# Protobuf Python Version: 4.25.1\n")
    with pytest.raises(SystemExit, match="Protobuf Python Version: 7."):
        protos.main()


def test_main_relativizes_the_generated_grpc_imports(monkeypatch, tmp_path):
    _stub_generation(monkeypatch, tmp_path, "# Protobuf Python Version: 7.35.1\n")
    (tmp_path / "dengjen_grpc_pb2_grpc.py").write_text(
        "import dengjen_grpc_pb2 as dengjen__grpc__pb2\n"
    )
    protos.main()
    assert (
        "from . import dengjen_grpc_pb2"
        in (tmp_path / "dengjen_grpc_pb2_grpc.py").read_text()
    )
