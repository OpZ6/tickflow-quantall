# TickFlow Stock Panel — Backend

A 股选股 + 监控 + 回测面板后端,基于 FastAPI + Polars + DuckDB + Parquet。

完整项目文档见根目录 [`README.md`](../README.md),架构与扩展指南见 [`docs/architecture-and-extension.md`](../docs/architecture-and-extension.md),贡献规范见 [`CONTRIBUTING.md`](../CONTRIBUTING.md)。

## 开发

```bash
uv sync --extra dev
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 3018
```

测试:

```bash
uv run pytest -q
uv run ruff check app tests
```
