"""dmap CLI integration."""
from __future__ import annotations

import io
import subprocess
import sys
from pathlib import Path

import pytest

from dungml.cli import main

SAMPLES = Path(__file__).resolve().parents[3] / "samples"


def test_renderers_command(capsys):
    rc = main(["renderers"])
    out = capsys.readouterr().out.splitlines()
    assert rc == 0
    assert "classic-bw" in out
    assert "floorplan" in out


def test_render_to_file(tmp_path):
    out = tmp_path / "crypt.svg"
    rc = main(["render", str(SAMPLES / "crypt.dmap"), "-o", str(out)])
    assert rc == 0
    text = out.read_text()
    assert text.startswith("<svg")
    assert "Entry Hall" in text


def test_render_to_stdout(capsys):
    rc = main(["render", str(SAMPLES / "cottage.dmap"), "-o", "-"])
    out = capsys.readouterr().out
    assert rc == 0
    assert out.startswith("<svg")


def test_render_from_stdin(monkeypatch, capsys):
    src = (SAMPLES / "cottage.dmap").read_text()
    monkeypatch.setattr("sys.stdin", io.StringIO(src))
    rc = main(["render", "-", "-o", "-"])
    out = capsys.readouterr().out
    assert rc == 0
    assert out.startswith("<svg")


def test_render_uses_override_renderer(tmp_path):
    out = tmp_path / "c.svg"
    rc = main([
        "render", str(SAMPLES / "cottage.dmap"),
        "-o", str(out),
        "--renderer", "classic-bw",
    ])
    assert rc == 0
    assert out.read_text().startswith("<svg")


def test_render_missing_file(capsys):
    rc = main(["render", "/nope/missing.dmap", "-o", "-"])
    err = capsys.readouterr().err
    assert rc == 2
    assert "No such file" in err or "missing" in err.lower()


def test_render_bad_input_returns_one(tmp_path, capsys):
    bad = tmp_path / "bad.dmap"
    bad.write_text('map "X" {')  # truncated
    rc = main(["render", str(bad), "-o", "-"])
    err = capsys.readouterr().err
    assert rc == 1
    assert "parse error" in err


def test_validate_command_clean_sample(capsys):
    rc = main(["validate", str(SAMPLES / "crypt.dmap")])
    assert rc == 0


def test_unknown_renderer_exits_one(tmp_path, capsys):
    rc = main([
        "render", str(SAMPLES / "crypt.dmap"),
        "-o", "-",
        "--renderer", "no-such",
    ])
    err = capsys.readouterr().err
    assert rc == 1
    assert "unknown renderer" in err


def test_console_script_works():
    """The `dmap` console_scripts entry point must run end-to-end."""
    result = subprocess.run(
        ["dmap", "render", str(SAMPLES / "cottage.dmap"), "-o", "-"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert result.stdout.startswith("<svg")
