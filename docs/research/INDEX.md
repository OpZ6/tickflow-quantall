# 量化研究文件索引

跨策略研究遵循 [量化策略研发通用规范](strategy-development-methodology.md)，当前身份与停止边界看 [右侧波段方向合同](right-side-swing-operating-system-20260910.md)，策略队列和数据阶段看 [量化开发主计划](quant-development-plan.md)，当前执行任务看根目录 [`goal.md`](../../goal.md)。`/goal` 模式按该顺序读取。

## 文件分层

| 层级 | 位置 | 用途 |
| --- | --- | --- |
| 当前任务 | `../../goal.md` | 本轮结论、下一步与禁止项；`/goal` 入口 |
| 启动指令 | [`../../goal-launch-prompt.txt`](../../goal-launch-prompt.txt) | 可全选复制；从当前枪做到「当天买谁」+ 手册 |
| 迭代助手用法 | [strategy-iteration-assistant.md](strategy-iteration-assistant.md) | 回测/诊断/提案/实现对基线记账；雏形不准换 |
| 宇宙全买决策 | [v1](leader-universe-market-gate-v1-decision.md) / [v2](leader-universe-market-gate-v2-decision.md) | 全买选择器已停；注视名单保留 |
| 短中窗验尸 | [right-side-short-window-autopsy-2016-2022-v1-decision.md](right-side-short-window-autopsy-2016-2022-v1-decision.md) | 顺序 1 已完成；五条默认流停止当选择器 |
| 方向合同 | [right-side-swing-operating-system-20260910.md](right-side-swing-operating-system-20260910.md) | 交易员身份、证据总表、操作系统、雏形清单、评价合同与 Agent 纪律 |
| 通用方法论 | `strategy-development-methodology.md` | 研究顺序、因果边界、Alpha、适用期、反过拟合与证据要求 |
| 项目主计划 | `quant-development-plan.md` | 策略队列、数据状态、阶段门槛与文件规则 |
| 机制族地图 | `strategy-mechanism-map.md` | 按机制、数据和独立性选择下一研究方向，防止轮询默认策略 |
| 已暂停的月末因子实验 | [高点接近度](momentum/high52-cross-section-train-v1-decision.md)、[市场调整强势](momentum/market-adjusted-strength-train-v1-decision.md)、[低特质波动](low-volatility/low-idiosyncratic-cross-section-train-v1-decision.md)、[低换手](liquidity/low-turnover-cross-section-train-v1-decision.md) | 历史对照；与当前右侧波段身份不符，不自动恢复 |
| 数据修复证据 | `adj-factor-repair-20260907.md` | 生产复权修复与断点复核 |
| 数据就绪审计 | `production-research-20260907-v8.md` | 最新 P0 策略范围、行业依赖隔离与剩余阻断 |
| 数据就绪审计历史 | `production-research-20260907-v7.md`、`production-research-20260907-v6.md`、`production-research-20260907-v5.md`、`production-research-20260907-v2.md`、`production-research-20260907-v1.md` | raw 清理、分钟执行、长期基准、早期复权、空 OHLCV 对账与首个只读库存基线 |
| 调查与路线历史 | `quant-development-roadmap-20260906.md` | 全 32 策略盘点和数据调查 |
| VCP 入口 | `vcp/README.md` | VCP 当前状态、运行命令和结果入口 |
| VCP 协议 | `vcp/*.json` | 不可变实验输入，按版本复现 |
| VCP 结果/审计 | `vcp/production-leader-mechanism-review-2016-2026-v1.md`、`vcp/*evaluation*.json`、`vcp/*audit*.json` | 机制结论与历史证据，不是新任务 |
| 运行事实 | `data/research/vcp/runs/` | 状态、manifest、交易明细 |
| VCP 前向候选观察 | `data/research/vcp/forward/forward-v2/` | 自 2026-09-09 起每交易日只追加；`forward-v1/` 仅保留为失效基线证据 |

VCP 目录中的 `five-year-*`、`iteration3-*` 至 `iteration9-*`、`candidate-v2-*` 文件均属于历史实验族；保留原路径是为了不破坏复现命令，但统一受主计划的冻结和版本规则约束。
