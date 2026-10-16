# production-research-20260907-v5 P0 数据审计

状态：`P0 incomplete`。本版本在 v2 缺失日 K 对账基础上，完成长期核心价格基准回填和早期复权独立对账；历史交易日历、历史证券主表、历史行业成员及分钟执行证据仍未通过。

机器清单位于本地忽略目录 `data/research/data-versions/production-research-20260907-v5/manifest.json`。原始空 OHLCV 的扶摇/Tushare 双源证据复用自 v3，复用前强制校验生产日 K 库存指纹；早期复权证据绑定当前 `adj_factor/all.parquet` 的 SHA-256。

复现命令：

```powershell
backend/.venv/Scripts/python.exe scripts/audit_production_research_data.py `
  --output-version production-research-20260907-v5 `
  --reconciliation-manifest data/research/data-versions/production-research-20260907-v3/manifest.json `
  --early-adjustment-reconciliation data/repair/early-adj-reconciliation-20260907-eastmoney-v1/reconciliation.json
```

## 本版本新通过的门槛

### 长期核心价格基准

腾讯指数 Provider 已从固定最多 640 条改为显式日期窗口拉取。生产库新增并验证以下未复权价格指数：

| 指数 | 区间 | 行数 | 股票交易日缺口 |
| --- | --- | ---: | ---: |
| 上证指数 `000001.SH` | 2015-01-05～2026-09-04 | 2,838 | 0 |
| 沪深300 `000300.SH` | 2015-01-05～2026-09-04 | 2,838 | 0 |
| 中证500 `000905.SH` | 2015-01-05～2026-09-04 | 2,838 | 0 |
| 中证1000 `000852.SH` | 2015-01-05～2026-09-04 | 2,838 | 0 |
| 创业板指 `399006.SZ` | 2015-01-05～2026-09-04 | 2,838 | 0 |

共 14,190 行，主键重复和空 OHLC 均为 0。正式回填运行 `core-index-20260904-64d8aa29` 已备份 502 个既有 raw/enriched 分区并创建 5,174 个新分区；来源帧和回滚清单位于 `data/.fact_backups/core-index-20260904-64d8aa29/`。

审计 gate 现在要求五条指数分别覆盖生产股票的全部 2,838 个交易日，不再只比较最早日期。该门槛仅代表可用的价格指数基准；全收益指数仍不可用，报告与实验不得混用两种口径。

### 早期复权独立对账

生产原始日 K 起点 2015-01-05 至十年研究快照起点 2016-09-05 之间只有浦发银行两条复权事件。东财分红实施记录独立确认：

- 2015-06-23：`10派7.57元`，前收 17.07 元，理论除权价按分币四舍五入为 16.31 元，推导因子 `1.04659717964439`；
- 2016-06-23：`10转1派5.15元`，前收 17.89 元，理论除权价为 15.80 元，推导因子 `1.1322784810126583`。

两次推导均与生产因子完全一致；复权后开盘缺口分别为 0.86% 和 0.63%。隔离证据位于 `data/repair/early-adj-reconciliation-20260907-eastmoney-v1/`，状态为 `pass`，当前因子文件 SHA-256 为 `5703b0f80c9dd2ad794a6bf132b1fbcde8b8b64bb3ab5492b8dab28fc9ceff1e`。

## 尚未通过的门槛

- 原始日 K：56 条旧实时占位仍在；10 条有本地上市前证据、20 条为已上市无交易候选、21 条有外部快照支持的上市前候选，最后 5 条仍缺证券状态证据。enriched 不含这些行且完整性通过。
- 历史交易日历：回填脚本 dry-run 已验证 2015-01-01～2026-09-07 共 4,268 个自然日、2,839 个开市日、无缺日/重复；正式发布被 Tushare `trade_cal` 的 1 次/小时限频阻断，生产门槛仍为失败。脚本不会自动重试低频接口。
- 历史证券主表：`namechange` 可用，`suspend_d` 无权限，`stock_basic` 受 1 次/小时限频；退市、改码、历史 ST、停复牌及每日可交易集合尚未形成。
- 历史行业成员：仍只有当前 `ext_hy_ths` 快照。
- 分钟执行证据：股票分钟 Parquet 仍为空，不能验收真实滑点或分钟级可成交性。

## 下一步

1. 限频窗口恢复后，仅运行一次 `scripts/backfill_trading_calendar.py --start-date 2015-01-01 --end-date 2026-09-07 --apply`，随后生成新审计版本确认日历 gate。
2. 用 `stock_basic` 的 L/D/P 状态闭合剩余 5 条代码；若供应商仍无记录，归为实时源证券代码缺陷。再选择有权限的停复牌替代源核验 20 条无交易候选。
3. 证据闭合后执行可回滚的无效占位清理，不填造 OHLC。
4. 设计历史证券主表和每日可交易集合；之后再处理历史行业成员和候选/持仓分钟样本。
5. P0 全部通过前继续冻结 VCP 参数，不进入 P1 策略排名。

