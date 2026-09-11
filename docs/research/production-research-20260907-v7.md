# production-research-20260907-v7 P0 数据审计

状态：`P0 incomplete`。本版本承接 [v6](production-research-20260907-v6.md)，在完整证据和可回滚备份下删除 56 条历史实时源写入的空 OHLCV 占位。raw 日 K 完整性 gate 现已通过；P0 只剩权威交易日历、历史证券主表和历史行业成员三个结构性阻断。

机器清单位于本地忽略目录 `data/research/data-versions/production-research-20260907-v7/manifest.json`。

复现命令：

```powershell
backend/.venv/Scripts/python.exe scripts/audit_production_research_data.py `
  --output-version production-research-20260907-v7 `
  --early-adjustment-reconciliation data/repair/early-adj-reconciliation-20260907-eastmoney-v1/reconciliation.json
```

## 本版本新通过的门槛

### raw 日 K 完整性

v6 冻结的 56 条空 OHLCV 已逐键与生产分区匹配，分布为：

| 日期 | 删除行数 |
| --- | ---: |
| 2026-08-31 | 18 |
| 2026-09-01 | 19 |
| 2026-09-02 | 19 |

清理只删除任一 OHLCV 为空的占位行，不写入替代值。这些键在 enriched 日 K 中原本即为 0 条，因此没有删除有效研究价格。

前置证据包括：

- v6 逐条分类和扶摇/Tushare 双日线源对账；
- TDX 分钟样本中 `002870.SZ` 在 2026-09-01 无任何成交记录；
- 北交所官方股票列表对 `920268.BJ`、`920298.BJ` 的查询均返回“暂无数据”。官方证据由 standalone Playwright + Edge 无头模式只读采集，位于 `data/repair/bse-listing-reconciliation-20260907-v1/reconciliation.json`，SHA-256 为 `288cd47cc622b0b6b92421044dbf519a3252e61fc63db94292fd8cc73e2d6437`。

正式清理运行 `raw-daily-placeholder-cleanup-279aa009` 将三个原分区完整备份到 `data/.fact_backups/raw-daily-placeholder-cleanup-279aa009/`，并记录清理前审计、官方证据、原文件和新文件 SHA-256。第一次运行在全库复核阶段遇到旧分区 `quote_ts` 异构列后自动回滚；v6 库存指纹和 56 行计数均恢复一致。修正只读扫描兼容参数后第二次运行成功。

v7 raw 日 K 结果：11,341,465 行、5,849 个代码、2,838 个交易日；主键重复、空 OHLCV 和畸形 OHLCV 均为 0。库存指纹为 `5a2f3e268e3ba667ac84a7e42af2c33ab2e65570ecda422b876b9bbedd0e80b7`。

## 当前已通过的 P0 数据门槛

- raw 日 K 完整性；
- enriched 日 K 完整性；
- 复权因子结构与早期独立对账；
- 五条长期核心价格指数逐交易日覆盖；
- 两组信号关联分钟执行样本：2 个运行、39 个完整会话、9,360 行。

## 尚未通过的门槛

- 权威交易日历：生产仍缺 2,753 个 raw 交易日；Tushare `trade_cal` 明确为 `5次/天`，本配额日不再重试。
- 历史证券主表：当前只有单日快照和上市日期；退市、改码、历史 ST、停复牌、每日可交易集合尚未形成。`namechange` 单次全量响应达到 10,000 行上限，且接口为 `1次/分钟`，必须分页并支持断点，不能把首屏当全量。
- 历史行业成员：仍只有当前 `ext_hy_ths` 快照。

## 下一步

1. 下一配额日一次性正式发布已验证的 2015-01-01～2026-09-07 交易日历，并立即生成新审计版本。
2. 先定义历史证券主表的区间事实契约，再以 `stock_basic` + 分页 `namechange` 建立可恢复快照；停复牌来源单独处理，不从名称变化推断成交状态。
3. 从每日已发布的主题/行业成员事实开始积累 point-in-time 历史；对无法回溯的区间保留显式缺口，不用当前快照回填过去。
4. 三个结构性 gate 全部通过前继续冻结 VCP 参数，不进入 P1 策略排名。
