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

同时遵守以下规则：

- 先理解调用链和现有测试，再进行修改。
- 保持实现简单、改动范围最小，不处理无关问题。
- 不覆盖工作区已有修改，不虚构测试或审查结果。
- 以实际验证结果作为完成标准。
- 修改数据契约或权威文档后运行 `python scripts/validate_project_contracts.py`。
