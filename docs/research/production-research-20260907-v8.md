# production-research-20260907-v8 P0 数据审计

状态：`P0 incomplete`。本版本数据库存与 [v7](production-research-20260907-v7.md) 相同，修正了历史行业成员对当前 VCP 主线的门槛范围。当前只剩权威交易日历和历史证券主表两个硬阻断。

机器清单位于本地忽略目录 `data/research/data-versions/production-research-20260907-v8/manifest.json`。

## 行业成员的范围决策

生产 `ext_hy_ths` 仍是每天覆盖式快照，2026-09-07 最新一次成功拉取为 5,567 行。它不能用于历史时点行业归属，也不会被写回过去。

但当前 P0 策略范围只有：

- `quants_vcp_legacy_v1`；
- `vcp_leader_breakout`；
- `launch_pullback_support`。

现有 VCP 实现以价格、成交量、相对强度、市场宽度、形态和明确的基础过滤为输入；`quants_vcp` 的实现注释和策略描述均明确为技术评分，不含原版财务/行业加分。因此，历史行业成员不属于当前 P0 策略的输入依赖。

v8 将该项记为：

- gate `status=pass`；
- data `status=unavailable_historically`；
- policy `disabled until point-in-time membership history is available`。

这不是宣布行业历史已经完成。任何行业领导力、行业相对强度、SEPA 行业增强或历史行业下钻仍不得启用；一旦策略版本新增该输入，历史行业成员立即恢复为硬门槛。

## 当前通过与阻断

已通过：raw/enriched 日 K、复权结构与早期独立对账、五条长期价格指数、两组信号关联分钟执行样本，以及当前 VCP 范围内的行业依赖隔离。

仍阻断：

1. 权威交易日历：生产缺 2,753 个 raw 交易日，等待下一 Tushare 日配额的一次性正式发布。
2. 历史证券主表：退市、改码、历史 ST、停复牌和每日可交易集合未形成；`stock_basic` 与分页 `namechange` 需要带断点的独立快照流程。

P0 通过前继续冻结 VCP 参数，不进入 P1 策略排名。
