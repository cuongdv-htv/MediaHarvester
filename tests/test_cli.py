"""Test smoke cho CLI: --version và --help chạy đúng."""

from __future__ import annotations

import pytest

from mediaharvester import __version__, cli


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    """--version in ra đúng version rồi exit 0."""
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["--version"])
    assert excinfo.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_help(capsys: pytest.CaptureFixture[str]) -> None:
    """--help hiển thị usage rồi exit 0."""
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["--help"])
    assert excinfo.value.code == 0
    assert "mediaharvester-cli" in capsys.readouterr().out


def test_no_args_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    """Chạy không tham số → in help, exit code 0."""
    assert cli.main([]) == 0
    assert "usage" in capsys.readouterr().out.lower()
