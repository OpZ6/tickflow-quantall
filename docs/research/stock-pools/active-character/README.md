# 股性活跃池研究

更新日期：2026-09-14。状态：v1全历史探索完成。思想见[股票池提纲](../../../../prompt/bucket.md)，公共口径见[研究协议](../protocol.md)。

本池研究近30／60日涨停活动是否提供独立候选价值，并拆分涨停频次、新鲜度、事件后趋势、回撤和与突破／回踩／高流动性的重叠。宽账本保留下跌趋势活动组，并建立同日相近状态的非活跃抽样对照。

全部未来收益与路径从T+1开盘起算，固定1／2／3／5／10／20日。数值产物写入`data/research/stock-pools/active-character/v1/`。

复现命令（从`backend/`执行）：

```powershell
uv run --frozen python ../scripts/research_active_character_pool.py
```

版本定义见[v1协议](v1-protocol.md)，结论见[v1分析](v1-analysis.md)，全量表见[v1数值结果](v1-results.md)。宽30／60日身份没有中期增量；暂保留“涨停后第1日”为待前向验证的超短事件子池，此后只保留活跃度标签。
