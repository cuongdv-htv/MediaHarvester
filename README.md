# MediaHarvester

App desktop Windows giúp editor video tìm kiếm + tải hàng loạt ảnh/video từ nhiều
nguồn internet làm tài nguyên edit video (kinh tế, khoa học, công nghệ, địa chính trị).

## Chạy dev

```powershell
uv sync
uv run mediaharvester-cli --help
uv run pytest
```

## Cấu hình

- Copy `.env.example` → `.env` và điền API keys (Pexels, Pixabay, Unsplash).
- Copy `config.toml.example` → `config.toml` và chỉnh thư mục thư viện, số luồng tải...
