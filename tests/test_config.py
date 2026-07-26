"""Test cho core.config: defaults + parse config.toml."""

from __future__ import annotations

from pathlib import Path

from mediaharvester.core.config import AppConfig, load_config


def test_defaults_when_no_file(tmp_path: Path) -> None:
    """Không có config.toml → dùng cấu hình mặc định."""
    cfg = load_config(tmp_path / "khong_ton_tai.toml")
    assert isinstance(cfg, AppConfig)
    assert cfg.download.max_concurrent == 4
    assert cfg.download.max_per_domain == 2
    assert cfg.default_quality == "1080p"
    assert cfg.dedup.phash_threshold == 5
    assert cfg.dedup.allow_duplicates is True  # mặc định: cho phép tải trùng
    assert cfg.rate_limits["pexels"] == 200


def test_load_from_toml(tmp_path: Path) -> None:
    """Đọc đúng giá trị từ file config.toml."""
    toml_file = tmp_path / "config.toml"
    toml_file.write_text(
        """
[general]
library_root = "E:/Lib"
default_quality = "720p"

[download]
max_concurrent = 8
max_per_domain = 3

[rate_limits]
pexels = 100

[dedup]
phash_threshold = 3
auto_skip_duplicates = true
allow_duplicates = false
""",
        encoding="utf-8",
    )
    cfg = load_config(toml_file)
    assert cfg.library_root == Path("E:/Lib")
    assert cfg.default_quality == "720p"
    assert cfg.download.max_concurrent == 8
    assert cfg.download.max_per_domain == 3
    assert cfg.rate_limits == {"pexels": 100}
    assert cfg.dedup.phash_threshold == 3
    assert cfg.dedup.auto_skip_duplicates is True
    assert cfg.dedup.allow_duplicates is False


def test_partial_toml_keeps_defaults(tmp_path: Path) -> None:
    """File toml thiếu section → phần thiếu vẫn dùng mặc định."""
    toml_file = tmp_path / "config.toml"
    toml_file.write_text('[general]\ndefault_quality = "1440p"\n', encoding="utf-8")
    cfg = load_config(toml_file)
    assert cfg.default_quality == "1440p"
    assert cfg.download.max_concurrent == 4
    assert cfg.anti_block.honor_robots_txt is True
