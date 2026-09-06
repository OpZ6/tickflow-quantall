# Quants 策略迁移状态

本文件为早期检查快照，以下“未迁移”状态已过时。当前五个稳定 ID 已建立，V2 从默认列表排除，四类核心语义完成定向回归；请以[核心迁移验收](quants-strategy-core-acceptance-20260905.md)为准。保留下面原始表格仅供追溯，不能作为当前状态或完全等价证明。

| 原版策略 | TickFlow 当前实现 | 独立迁移 ID | 当前证据 | 状态 |
| --- | --- | --- | --- | --- |
| `v1_vcp_optimized` | `_quants_vcp.py` | `quants_vcp_legacy_v1` | 同输入 fixture 的尺度、枢轴、收缩腿、状态、入场类别和质量分数对账；回测下一根开盘成交回归 | 核心逻辑已对齐，历史逐日对账未完成 |
| `v2_growth_trend` | `quants_vcp.py` 近似实现 | 未建立 | 仅有 TickFlow 自身测试 | 未迁移 |
| `v3_cup_with_handle` | `cup_handle_breakout.py` 近似实现 | 未建立 | 仅有 TickFlow 自身测试 | 未迁移 |
| `v4_high_tight_flag` | `high_tight_flag_breakout.py` 近似实现 | 未建立 | 仅有 TickFlow 自身测试 | 未迁移 |
| `v5_pullback_low_absorb` | `launch_pullback_support.py` 近似实现 | 未建立 | 仅有 TickFlow 自身测试 | 未迁移 |

独立 ID 只有在原版 detector、参数消费、状态/入场语义和同输入对账完成后建立。禁止通过 builtin 间导入包装旧策略伪造迁移。
