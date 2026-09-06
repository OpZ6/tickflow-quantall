# Quants 策略核心迁移验收（2026-09-05）

验收口径：按用户最新要求，只要求核心思路一致，不追求原版全部字段、筛选排序和历史收益逐项复刻。本记录替代旧迁移计划的严格对账完成门槛；未执行的全量检查不计为通过。

## 策略结果

| 来源 | 当前显示名 | 稳定 ID | 结论 |
| --- | --- | --- | --- |
| V1 | 波动收缩形态(VCP) | `quants_vcp_legacy_v1` | 收缩结构、枢轴、缩量与入场状态核心案例通过 |
| V2 | 成长趋势(经典 VCP) | `quants_growth_trend_legacy_v1` | 从默认策略列表排除，保留 ID 与旧配置兼容；不声称 V1 与原版 V2 数学等价 |
| V3 | 杯柄形态 | `quants_cup_handle_legacy_v1` | 杯体、杯柄、突破及杯沿回踩核心案例通过 |
| V4 | 高窄旗形 | `quants_high_tight_flag_legacy_v1` | 旗杆、紧旗与突破核心案例通过 |
| V5 | 回调低吸(龙吸水) | `quants_pullback_low_absorb_legacy_v1` | 放量锚点、回调和资金流核心案例通过；仍为观察候选，缺真实资金流时不可计算 |

另一个已有 `quants_vcp` 显示为“VCP 多段收缩(研究变体)”，与上述基线区分。五个迁移 ID 均保留，改名不迁移或覆盖用户保存参数。迁移策略仅消费已完成日 K，不启用盘中实时计算。

## 已完成验证

- 从 Quants 提取并冻结 7 个合成输入与原版期望结果，覆盖 V1/V3/V4/V5 的正例和反例。来源 commit：`51b6ef059030d851a82a9bb9620d3f3015df4226`。fixture 位于 `backend/tests/fixtures/quants_core_cases.json`；生产代码不依赖 Quants 工作目录。
- 验证有效性、状态、枢轴和可执行标记；检查快照与历史前缀一致、跨标的对齐补空不改变结果、无效形态不进入候选、缺资金流不使用价量伪造。
- 策略注册、保存参数、缓存、信号事件、预览、监控事件及回测相关回归：**336 passed，6 warnings**（Polars 旧 `streaming` 参数弃用提示）。
- 策略服务重载成功，默认 API 隐藏 V2，加载错误为空。使用独立 Playwright + Edge 无头浏览器验证策略池名称和 V2 隐藏，页面运行错误为空；检查桌面及窄屏截图，窄屏沿用现有截断布局。页面验收产物保存在本地 `artifacts/strategy-core-acceptance-20260905/`。
- 聚焦修改文件的 Ruff 检查通过；项目文档契约检查返回 `PROJECT_CONTRACTS_OK`；`git diff --check` 通过。本轮未修改前端源码，因此未重新执行前端构建。

复现回归（工作目录 `backend/`）：

```powershell
uv run --no-sync pytest tests/test_quants_migration_acceptance.py tests/test_quants_vcp.py tests/test_quants_legacy_migrations.py tests/test_strategy_registry.py tests/test_strategy_saved_params.py tests/test_strategy_cache.py tests/test_strategy_signal_events.py tests/test_strategy_preview.py tests/test_strategy_monitor_events.py tests/backtest -q
```

## 接受的差异与后续边界

后续真实回测已发现更具体的数据限制：长历史截面的可用股票很少，近期全市场样本不足 VCP 默认 252 日收益预热。迁移验收仍有效，但不能据此认定全市场优化数据已齐备，见[VCP 首轮研究记录](../research/vcp/first-run-20260905.md)。

- V2 与 V1 的原版 detector 不同；排除 V2 是简化策略集的选择，不是完全等价替换证明。需要时仍可通过旧 ID 读取。
- 不追求全部质量分数、解释字段、过滤器和排序与原版一致；没有证明全市场历史候选或收益一致。大规模历史诊断已因用户收缩范围停止，其部分输出不计为验收结果。
- V5 原版也是 `watch` 语义，不能为了回测成交强行改成买入。目标输入需真实 `net_mf_amount`（万元）；当前常规行情矩阵尚未提供这条完整历史数据链，因此 V5 尚不能作为完整自动交易策略调优。保留计划止损等展示差异不影响本次核心验收。
- 可开始 VCP、杯柄、高窄旗形的日线基线研究和小规模参数实验。本次未完成分钟数据覆盖、历史财务补齐或 Walk-forward 改造；现有 Walk-forward 的自然日窗口、OOS 重叠及账户连续性仍需在正式样本外优化前处理。测试通过不等于研究结果或收益已经验收。
