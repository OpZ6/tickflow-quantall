# 流动性趋势池研究

更新日期：2026-09-14。状态：v1全历史探索完成；容量身份保留为全局约束和排序因子，不作独立收益池。思想见[股票池提纲](../../../../prompt/bucket.md)，公共口径见[研究协议](../protocol.md)。

本池研究成交额容量身份是否在价格状态之外提供增量，并比较前50／100／200、连续在榜、趋势健康度、回撤与弱市表现。宽账本保留成交额前500作为同日对照；前200为候选研究范围，不提前排除趋势走坏组。

全部未来收益与价格路径从T+1开盘起算，固定1／2／3／5／10／20／40／60日。数值产物写入`data/research/stock-pools/liquidity-trend/v1/`。

复现命令（从`backend/`执行）：

```powershell
uv run --frozen python ../scripts/research_liquidity_trend_pool.py
```

版本定义见[v1协议](v1-protocol.md)，完整发现与决定见[v1分析报告](v1-analysis.md)，脚本数值见[v1结果表](v1-results.md)。
