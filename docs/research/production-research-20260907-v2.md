# production-research-20260907-v2 缺失日 K 对账

状态：`P0 incomplete`。本版本在 v1 库存清单上增加了逐条空 OHLCV 分类和双日线源只读对账；它仍不是可复现数据副本，也不授权策略收益验收。

机器清单位于本地忽略目录 `data/research/data-versions/production-research-20260907-v2/manifest.json`。复现命令：

```powershell
backend/.venv/Scripts/python.exe scripts/audit_production_research_data.py `
  --output-version production-research-20260907-v2 `
  --reconcile-provider fuyao `
  --reconcile-provider tushare
```

命令只读生产数据与指定日线源，原子发布到新目录，并拒绝覆盖同名审计。

## 56 条空 OHLCV 的结论

| 分类 | 行数 | 当前结论 |
| --- | ---: | --- |
| `pre_listing_supported` | 10 | 当前证券主表给出可信上市日，且上市日晚于占位日期 |
| `known_instrument_nontrading_candidate` | 20 | 已上市代码的成交量/成交额均为 0；可判定为无交易候选，但缺少停复牌历史，不能进一步宣称为已确认停牌 |
| `unresolved_security_master` | 26 | 当前证券主表缺代码，或上市日为 `1970-01-01` 占位，单靠本地数据不能归因 |

这些记录集中于 2026-08-31～2026-09-02。其 `quote_ts` 均为对应日期的实时快照时间，写入链为 `QuoteService._build_daily` → `KlineRepository.flush_live_daily`；不是历史批量日线源的权威行。当前实时构建路径已经在落盘前通过 `filter_halt_days` 排除零成交和空 OHLC 行，因此它们是旧版残留。enriched 数据没有这 56 行，OHLCV 完整性仍通过。

扶摇与 Tushare 在 2026-08-28～2026-09-05 对 24 个受影响代码分别返回 34 行、14 个代码、6 个交易日；两者键指纹完全一致，且都没有返回任何一个空行对应的 `(symbol, date)`。这支持“非有效交易日 K 占位”的判断，但不能单独区分上市前、停牌、退市或代码维表缺陷。

## 证券状态补充探测

2026-09-07 的 mirror 优先小样本实测：

- `trade_cal`：可用；2015-01-01～2015-01-15 返回 15 个自然日，开闭市与前交易日字段存在。
- `namechange`：可用；`002731.SZ` 返回 2026 年两条 ST 名称区间。
- `suspend_d`：当前凭证无访问权限，不能作为历史停牌主来源。
- `stock_basic`：接口限频为 1 次/小时，本轮被限频，尚未取得待上市代码全集。
- 东财 push2 个股基本面：本机代理拒绝连接，本轮没有可用结果。
- 腾讯批量快照：在 2026-09-04 09:00 识别出 8 个异常代码；其中 5 个只有发行价式报价、3 个价格为 0，均无有效日线。它为其中 21 条空行提供“上市前候选”补充证据，但没有上市日期字段，不能提升为已确认分类。`920268.BJ` 与 `920298.BJ` 未被腾讯识别，对应 5 条仍完全未解决。

## 同步修复的 Provider 契约缺口

Tushare mirror 的 pandas 返回使用扩展 `StringDtype`。旧适配器只处理 `object` 字符串，导致有效 `trade_date` 在 Polars 归一化时全部变为 null。适配器现改为识别所有 pandas 字符串 dtype，并新增回归测试；修复后 Tushare 的 34 行日期非空且与扶摇键集合一致。

## P0 当前阻断与下一步

原始 56 条占位尚未物理清理：最后 5 条仍缺证券状态证据，因此本版本继续把 `raw_daily_integrity` 标为 `incomplete`，不以相邻价格或零值补齐。下一步顺序为：

1. 等 `stock_basic` 限频窗口恢复后，只读获取上市/待上市/退市状态，先闭合 `920268.BJ`、`920298.BJ` 及 `1970-01-01` 代码；若仍无记录，则把它们列为实时源代码维表缺陷。
2. 为已上市的 20 条无交易候选寻找有权限的停复牌替代源；没有来源时保留“无交易”而非“停牌”语义。
3. 在证据闭合后用可回滚修复任务删除无效占位行，禁止伪造 OHLC；生成新数据版本清单验证原始和 enriched 主键/OHLCV 门槛。
4. 利用已验证的 `trade_cal` 构建覆盖 2015-01-01 至研究截止日的 Market Facts 历史日历；不得继续以工作日近似交易日。
5. 其余 P0 阻断保持不变：早期复权独立对账、历史证券主表、长期基准、历史行业成员和分钟执行证据仍未完成。

