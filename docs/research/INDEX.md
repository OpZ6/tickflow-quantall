# 量化研究文件索引

未来开发只看 [量化开发唯一主计划](quant-development-plan.md)。

## 文件分层

| 层级 | 位置 | 用途 |
| --- | --- | --- |
| 唯一执行计划 | `quant-development-plan.md` | 当前任务、阶段门槛、文件规则 |
| 数据修复证据 | `adj-factor-repair-20260907.md` | 生产复权修复与断点复核 |
| 调查与路线历史 | `quant-development-roadmap-20260906.md` | 全 32 策略盘点和数据调查 |
| VCP 入口 | `vcp/README.md` | VCP 当前状态、运行命令和结果入口 |
| VCP 协议 | `vcp/*.json` | 不可变实验输入，按版本复现 |
| VCP 结果/审计 | `vcp/*evaluation*.json`、`vcp/*results*.md`、`vcp/*audit*.md` | 历史证据，不是新任务 |
| 运行事实 | `data/research/vcp/runs/` | 状态、manifest、交易明细 |

VCP 目录中的 `five-year-*`、`iteration3-*` 至 `iteration9-*`、`candidate-v2-*` 文件均属于历史实验族；保留原路径是为了不破坏复现命令，但统一受主计划的冻结和版本规则约束。
