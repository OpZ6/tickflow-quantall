# 中/长尺度主形态限制：运行记录

- 协议：`legacy-high-tight-flag-medium-long-train-v1.json`。
- Run：`20260909T153630166989Z`，2026-09-09 15:36:30 UTC 启动。
- 已完成，735 笔成交；路径分析及决策见 `legacy-high-tight-flag-medium-long-train-v1-decision.json`。实际净 Alpha 和年度稳定性未通过，停止该表示。
- 恢复时检查该 run 的真实进程与状态，不重复启动。运行命令（backend 目录）：`uv run --frozen python ../scripts/run_vcp_research.py --protocol ../docs/research/high-tight-flag/legacy-high-tight-flag-medium-long-train-v1.json`。

实现采用现有策略参数入口，默认 `exclude_short_scale=false`。共享 `_detect` 在原检测器完成主形态选择后将被排除的可执行 short 标记为 watch，原因 `short_scale_excluded`，历史矩阵与快照共同使用该判断。没有备选尺度提升，退出矩阵不受过滤影响。属于现有配置契约加最小内部逻辑修改，不新增注册框架。

与基线 `20260909T130617820559Z/source.zip` 逐文件比较后端 Python 源码（忽略换行差异），差异仅为本次 `_quants_high_tight_flag.py` 和 `quants_high_tight_flag_legacy_v1.py`。已生成的 `universe.json`、`data-references.json` 解析后与基线完全相等；`config.json` 唯一差异为 params 从 null 变为 `{"exclude_short_scale": true}`。这证明归档引用一致，不等同于额外验证文件内容不可变。事件子集检查仍待运行产物完成后核对。

验证：

- 新用例先验证 short 仍入场而失败，完成过滤后通过。
- `uv run --frozen pytest tests/test_high_tight_flag_scale_gate.py tests/test_quants_migration_acceptance.py tests/backtest/test_research_training_boundary.py -q`：33 passed。
- 核心实现和新增测试 Ruff 通过；META 文件保留原有第 7、9 行中文标点的 4 项 RUF001，本次新增行无告警。
- `uv run --frozen python ../scripts/validate_project_contracts.py`：PROJECT_CONTRACTS_OK。系统 `python` 为 3.10，缺少 StrEnum，因此使用项目解释器验证。
- `git diff --check`：通过。

已完成 40 日标签分析、735 笔成交子集和保留交易一致性检查、63/117 大赢家保留检查及全部训练门槛决策。完整候选身份未在 result 中物化，未据成交子集冒充完整候选证明；训练门槛已明确失败，不授予晋级。
