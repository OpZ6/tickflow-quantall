# 批次 1 验收对账清单

> 批次 1(数据基础)完成后,手动验证 TickFlow 用 Tushare 数据与 Quants 对账。
>
> 前置:`TUSHARE_TOKEN` 环境变量已设置;Quants `ppgu_unified.duckdb` 可访问(只读)。

## 自动化验收(已通过)

`backend/tests/test_batch1_acceptance.py` 验证框架就绪:
- TushareProvider 实例化 + datasets 完整(daily/adj_factor/index/financial/moneyflow)
- plugin.yaml 字段正确(name/runtime/entry/datasets)
- bridge.availability 可调用
- migrate_from_quants.py 可 import(export_daily/adj_factor/moneyflow + main)
- collect_quantx.py 可 import(4 个采集器函数)
- .env.example 含 TUSHARE_TOKEN
- pyproject.toml 含 tushare extra

运行:
```powershell
cd backend
uv run python -m pytest tests/test_batch1_acceptance.py -q
```

## 手动对账(需真实数据)

### 1. Tushare provider 日K对账

```powershell
cd backend
$env:TUSHARE_TOKEN="你的token"
uv run python -c "
from app.plugins.tushare.provider import TushareProvider
from datetime import datetime
p = TushareProvider()
df = p.get_daily(['600519.SH'], datetime(2026,8,21), datetime(2026,8,21))
print(df)
print('columns:', df.columns)
print('rows:', len(df))
"
```

对账标准:
- `symbol` 列为 `600519.SH`(TickFlow 格式)
- `date` 列为 `date(2026,8,21)`(Date 类型)
- `open/high/low/close/volume/amount` 为 Float64
- 无停牌行(open=0 且 high=0 被过滤)
- 与 Quants `dwd_daily_bar` 同日同标的字段一致(raw 列)

### 2. Tushare provider 财务/资金对账

```powershell
uv run python -c "
from app.plugins.tushare.provider import TushareProvider
p = TushareProvider()
fin = p.get_financials('income', ['600519.SH'], latest_only=True)
print('financials:', fin.columns, len(fin))
mf = p.get_moneyflow(['600519.SH'], None, None)
print('moneyflow:', mf.columns, len(mf))
"
```

对账标准:
- `financials` 有 `symbol` 列(`600519.SH`)
- `moneyflow` 有 `symbol` + `trade_date` 列
- 字段值与 Tushare 官网一致

### 3. migrate_from_quants 导出对账

```powershell
cd backend
uv run python ../scripts/migrate_from_quants.py `
    --quants-db D:/quantall/apps/quants/data/warehouse/ppgu_unified.duckdb `
    --tickflow-data ./data `
    --tables daily,adj_factor,moneyflow
```

对账标准:
- `data/kline_daily/date=*/part.parquet` 日期完整(Quants 有数据的日期)
- `data/adj_factor/symbol=*/part.parquet` 标的完整
- `data/moneyflow/date=*/part.parquet` 日期完整
- Parquet 字段:symbol/date/open/high/low/close/volume/amount(kline_daily)
- 行数与 Quants DuckDB `SELECT count(*) FROM dwd_daily_bar` 一致
- 停牌行(open=0 且 high=0)被过滤

验证后可启动 TickFlow,确认 `/api/data/status` 显示导入的数据:
```powershell
uv run uvicorn app.main:app --port 3018
# 浏览器打开 http://localhost:3018/data
```

### 4. collector 采集对账

```powershell
cd backend
uv run python ../scripts/collect_quantx.py --source ths_hot --date 20260821 --tickflow-data ./data
uv run python ../scripts/collect_quantx.py --source zhangtingke --date 20260821 --tickflow-data ./data
```

对账标准:
- `data/ext_data/ext_ths_hot/timeseries/date=2026-08-21/part.parquet` 存在
- `data/ext_data/ext_zhangtingke/timeseries/date=2026-08-21/part.parquet` 存在
- ths_hot 字段:symbol/name/reason/pct_chg/turnover_pct/amount/close(与 QuantX ths_hot_scraper 同日产出一致)
- zhangtingke 字段:trade_date/level/count/stocks(连板梯队与 QuantX review s3 一致)

### 5. pywencai / duanxianxia(批次 2 完善)

```powershell
uv run python ../scripts/collect_quantx.py --source pywencai --date 20260821
# 预期: RuntimeError("pywencai 未安装...批次 2 完善")
```

批次 1 阶段标记为骨架,批次 2 迁移情绪三件套时完善采集逻辑。

## 验收结论

- [x] 自动化验收(test_batch1_acceptance.py)通过
- [ ] Tushare provider 日K对账(需 TUSHARE_TOKEN)
- [ ] Tushare provider 财务/资金对账(需 TUSHARE_TOKEN)
- [ ] migrate_from_quants 导出对账(需 Quants 库)
- [ ] ths_hot / zhangtingke 采集对账(需网络)
- [ ] pywencai / duanxianxia(批次 2)

自动化部分已通过(44 个测试全过)。手动对账需真实环境,由用户执行。
