"""批次 1 验收测试:验证 Tushare provider + migrate + collector 集成就绪。

不验证真实数据对账(需要 Tushare Token + Quants 库);
验证框架就绪:provider 可实例化、plugin.yaml 完整、脚本可 import、配置就位。
真实对账步骤见 docs/batch1-acceptance-checklist.md。
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

from app.plugins.tushare.provider import TushareProvider

_scripts = Path(__file__).resolve().parents[1].parent / "scripts"
sys.path.insert(0, str(_scripts))


# ---- Tushare provider 就绪 ----

def test_tushare_provider_instantiable():
    provider = TushareProvider()
    assert provider.name == "tushare"
    assert provider.builtin is True
    assert provider.config.name == "tushare"


def test_tushare_provider_datasets():
    provider = TushareProvider()
    expected = {"daily", "adj_factor", "index", "financial", "moneyflow"}
    assert set(provider.config.datasets) == expected


def test_tushare_plugin_yaml_exists():
    plugin_yaml = Path(__file__).resolve().parents[1] / "app" / "plugins" / "tushare" / "plugin.yaml"
    assert plugin_yaml.exists(), f"plugin.yaml not found at {plugin_yaml}"
    manifest = yaml.safe_load(plugin_yaml.read_text(encoding="utf-8"))
    assert manifest["name"] == "tushare"
    assert manifest["runtime"] == "python"
    assert manifest["entry"] == "app.plugins.tushare.provider:TushareProvider"
    assert "daily" in manifest["datasets"]
    assert "financial" in manifest["datasets"]
    assert "moneyflow" in manifest["datasets"]


def test_tushare_bridge_exists():
    from app.plugins.tushare import bridge

    ok, msg = bridge.availability()
    assert isinstance(ok, bool)
    assert isinstance(msg, str)


# ---- 脚本可 import ----

def test_migrate_script_importable():
    import importlib

    spec = importlib.util.spec_from_file_location(
        "migrate_from_quants", _scripts / "migrate_from_quants.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert hasattr(mod, "export_daily")
    assert hasattr(mod, "export_adj_factor")
    assert hasattr(mod, "export_moneyflow")
    assert hasattr(mod, "main")


def test_collect_script_importable():
    import importlib

    spec = importlib.util.spec_from_file_location(
        "collect_quantx", _scripts / "collect_quantx.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert hasattr(mod, "collect_ths_hot")
    assert hasattr(mod, "collect_zhangtingke")
    assert hasattr(mod, "collect_pywencai")
    assert hasattr(mod, "collect_duanxianxia")


# ---- 配置就位 ----

def test_env_example_has_tushare_token():
    repo_root = Path(__file__).resolve().parents[2]
    env_example = repo_root / ".env.example"
    assert env_example.exists()
    content = env_example.read_text(encoding="utf-8")
    assert "TUSHARE_TOKEN" in content


def test_pyproject_has_tushare_extra():
    repo_root = Path(__file__).resolve().parents[2]
    pyproject = repo_root / "backend" / "pyproject.toml"
    content = pyproject.read_text(encoding="utf-8")
    assert 'tushare = [' in content
    assert "tushare>=" in content


# ---- 集成:所有批次 1 测试模块存在 ----

def test_all_batch1_test_files_exist():
    tests_dir = Path(__file__).resolve().parent
    expected = [
        "test_tushare_provider.py",
        "test_migrate_from_quants.py",
        "test_collect_quantx.py",
        "test_batch1_acceptance.py",
    ]
    for name in expected:
        assert (tests_dir / name).exists(), f"missing {name}"
