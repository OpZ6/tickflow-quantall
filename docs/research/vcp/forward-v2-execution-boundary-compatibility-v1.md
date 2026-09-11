# 前向执行日期边界兼容性

本轮解决首日观察记录提出的具体疑点：研究回测新增 `entry_fill_time_mask` 后，是否会改变 `forward-v2` 的日期范围内成交。不是全量历史收益复测，也不更新冻结规则。

调用链：`observe_vcp_forward.py` 构造 `mode="position"`，start 为 observation_start，end 为 as_of；`StrategyBacktestService` 在此模式令 sim_end 等于 config.end，按 start..sim_end 截取模拟矩阵，再传入同一个 start..end 的成交掩码。因此掩码在该模拟时间轴上全部为真。`full` 研究模式含额外退出/标签日期，才可能排除区间外成交，不能把两种模式混淆。

在现有 `test_delayed_entry_cannot_fill_outside_formal_time_mask` 中增加有实际入场信号的兼容断言：三根 K 线中第二根产生信号，第三根按 T+1 可成交；不传掩码与传全真掩码的 entry、entry_signal_time、entry_signal_code、open 和 exit 数组完全一致。原区间外屏蔽断言仍通过。既有前向账本测试同时覆盖末日信号次日排队、路径末端标记保留为未平仓和拒绝状态。

验证命令（backend 目录）：

`uv run --frozen pytest tests/backtest/test_matrix_strategy.py tests/backtest/test_vcp_forward_observation.py tests/backtest/test_vcp_forward_archive.py -q`

结果：37 passed；改动测试文件 Ruff 通过。

结论：当前 position 调用链下，新增成交日期掩码不改变区间内 T+1 成交矩阵。这一具体疑点已关闭。当前代码仍不等于冻结归档的逐字节副本；可选研究开关默认关闭及缓存发布差异已记录，不能把本定向验证扩大为所有代码、所有数据上的完整行为等价证明。首次真实前向成交仍需保留实际运行版本与成交证据，且不授予实盘资格。

目前最新完成数据仍为 2026-09-09，首日快照已存在，不能重复追加。恢复条件是出现下一完成交易日分区，或新的独立机制/必要数据证据。当前没有在运行的研究回测等待取结果。
