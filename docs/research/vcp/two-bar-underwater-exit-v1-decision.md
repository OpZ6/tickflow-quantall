# 无需求且跌破入场价：淘汰

[协议](two-bar-underwater-exit-v1.json)。同一批全量独立训练已完结 474 笔，只在前两日未到 +3% 且第二日收盘低于入场价时提前卖。等于入场价、缺收盘、缺市场日不触发。

| 规则 | 胜率 | 盈亏比 | 平均净收益 |
| --- | ---: | ---: | ---: |
| 原进出场 | 27.43% | 3.56 | +0.9139% |
| 无需求且低于入场价 | 23.63% | 4.24 | +0.7152% |

127 笔提前退出，80 笔改善、47 笔变差，但 25 笔原赢家被提前退出，其中 23 笔变成非盈利。平均盈利 12.9955% → 12.7264%，平均非盈利损失 3.6518% → 3.0010%。盈亏比提高未补偿胜率损失，均值下降 0.1987 个百分点；2017、2019、2020、2022 四年变差。3 笔缺早期市场日数据仍沿用基线，未假装可成交。

淘汰这条附加卖点。停止“两日无需求”及其成本线、需求幅度、天数邻域；基线仍为 474 笔原进出场。原有止损/均线/利润保护保留。

逐笔、年度及规则快照在 `data/research/vcp/two-bar-underwater-exit-v1/`。复算命令（输出应选新文件名以保留既有证据）：

```powershell
backend/.venv/Scripts/python.exe scripts/research_vcp_two_bar_no_demand.py --protocol docs/research/vcp/two-bar-underwater-exit-v1.json --baseline-run 20260909T030431101979Z --output data/research/vcp/two-bar-underwater-exit-v1/recheck.json --ledger data/research/vcp/two-bar-underwater-exit-v1/recheck.parquet
```

下一项已实际检验获利后的放量跌破前低事件，见[决策](profitable-distribution-exit-v1-decision.md)。
