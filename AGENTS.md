# AI 开发入口

修改、调试或审查本仓库前，必须完整阅读并遵循根目录的 [`CONTRIBUTING.md`](CONTRIBUTING.md)。其中定义了项目架构、数据契约、数据源插件化、缓存与性能要求、测试矩阵以及 PR 复审和合并标准。

同时必须先阅读 [`docs/README.md`](docs/README.md)，并按数据类型选择权威文档：

- 跨层架构、模块边界：`docs/architecture.md`；
- 新事实、schema、来源路由、存储：`docs/data-foundation.md`；
- 自有 HTTP 日K/实时/分钟/财务：`docs/custom-data-source.md`；
- Python/Node 行情 Provider：`docs/plugin-development.md`；
- 新指标、分析、API、页面：`docs/analysis-development.md`；
- 上游版本跟踪或合并：`docs/upstream-sync.md`。

不得用历史迁移规划代替当前权威文档。新增数据前必须先分类：通用行情走 Provider，自定义辅助表走 ext_data，可复用非 K 线事实走 SourceManager + Market Facts。QuantX pipeline、Repository、API 和前端不得直接 import 或调用 `legacy_scrapers`。

涉及代码二次开发、前端插槽、后端可替换策略、扩展注册或上游升级兼容时，还必须阅读 [`docs/secondary-development.md`](docs/secondary-development.md)。该文档区分当前已实现能力与目标扩展契约；不得根据设计示例虚构尚不存在的 API。

量化策略 `/goal` 必须先读 [`goal.md`](goal.md) 与 [`docs/research/strategy-iteration-assistant.md`](docs/research/strategy-iteration-assistant.md)。无限迭代直到确认有效策略。思想是 VCP / 杯柄 / 高旗 / 放量突破·缩量回调，选股与进出代码可改、思想保留。TickFlow 全量独立回测，看胜率、盈亏比、平均收益，不管仓位。不得改成无关思想。不得把检测器内部连续字段再切阈值当下一轮。

同时遵守以下规则：

- 先理解调用链和现有测试，再进行修改。
- 保持实现简单、改动范围最小，不处理无关问题。
- 不覆盖工作区已有修改，不虚构测试或审查结果。
- 以实际验证结果作为完成标准。
- 修改数据契约或权威文档后运行 `python scripts/validate_project_contracts.py`。

## 执行原则（补充）

- 当前用户指令 > Skill > 记忆 > 默认偏好；记忆与当前任务冲突时以当前任务为准。
- 提问前先完成已授权且能产出可审查结果的工作。
- 用户建议不适合目标时直接说明，不迎合。
- 不因假想风险主动加警告、免责声明或审批流程。
- 无 CLI/API 的网页用已登录 Chrome；飞书优先 `lark-cli`。
