# TickFlow 开发文档入口

## 人读全景报告

- [TickFlow 全景架构报告](tickflow-architecture-report.html)：面向产品、数据和二次开发者的可视化 HTML 导读，解释数据层、处理层、展示层、两类数据入口、存储、QuantX 独立流水线、插件与新增功能路径。报告帮助建立全局心智模型；具体契约仍以下方六份权威文档和当前源码为准。

本目录的文档按“当前事实、操作契约、历史记录”分层。AI 和开发者不得把历史规划当成当前实现，也不得因为文件名相似而跳过下表中的权威入口。

## 六份权威文档

| 文档 | 权威范围 | 何时必须阅读 |
| --- | --- | --- |
| [architecture.md](architecture.md) | 当前分层、模块边界、调用方向和扩展选择 | 修改跨层调用、目录结构、API 或前端数据流 |
| [data-foundation.md](data-foundation.md) | 数据集、来源、单位、分区、质量、发布和事实脚手架 | 新增数据、修改 schema、来源优先级或存储 |
| [custom-data-source.md](custom-data-source.md) | 自有 HTTP 行情接口的 YAML 配置 | 接入 daily、adj_factor、realtime、minute、financial |
| [plugin-development.md](plugin-development.md) | Python/Node 行情 Provider 插件 | SDK、复杂鉴权、分页或非 YAML 行情接入 |
| [analysis-development.md](analysis-development.md) | 新指标、分析、API、页面的端到端开发 | 新增确定性分析或展示功能 |
| [upstream-sync.md](upstream-sync.md) | 跟踪并合并 TickFlow 上游 | 当前差异快照、稳定性判断、fetch、升级预检、合并和发布 |

这些文档的优先级为：当前源码和测试 > 本索引中的权威文档 > 运维手册 > 实施记录 > 历史规划。

## 数据接入选择

```text
已有 K 线/实时/分钟/财务契约?
├─ 简单 HTTP 接口 -> custom-data-source.md
├─ SDK/复杂协议   -> plugin-development.md
└─ 否
   ├─ 仅用户自定义展示字段 -> ext_data
   └─ 可复用市场事实       -> data-foundation.md + analysis-development.md
```

QuantX 专项网页来源属于“市场事实来源”，统一通过 `app.quantx_data.source_manager.SourceManager` 注册和执行。不得在 pipeline、Repository、API 或前端直接 import 某个 scraper。

## 支持文档

- [stock-chart-workbench.md](stock-chart-workbench.md)：个股分析唯一 K 线实例、统一行情 API、20+38 指标、缠论/价位/九类形态/策略证据/派生事件/画线和验证契约。
- [quantx-data-pipeline.md](quantx-data-pipeline.md)：QuantX 运行、重试、重算和故障诊断手册。
- [quantx-single-day-canonical-view-plan.md](quantx-single-day-canonical-view-plan.md)：QuantX 单日富图表从兼容 JSON 迁移到权威事实与确定性 ViewBuilder 的分批执行计划和验收清单。
- [quantx-unified-dashboard-design.md](quantx-unified-dashboard-design.md)：QuantX 多日驾驶舱与单日富图表合并为统一高密度看板的内容、排版和零丢失设计。
- [quantx-static-export.md](quantx-static-export.md)：把指定日期 QuantX 看板导出为保留图表、筛选和下钻交互且无本地服务依赖的单文件 HTML，并通过 Edge 做断网验收。
- [quantx-unified-dashboard-execution-plan.md](quantx-unified-dashboard-execution-plan.md)：统一看板按可回滚批次实施的文件边界、数据调用链、验证矩阵和完成定义。
- [secondary-development.md](secondary-development.md)：原项目二次开发、插槽和扩展契约。
- [configuration.md](configuration.md)、[deployment.md](deployment.md)：配置与部署。

## 历史和审计文档

下列文件保留追溯价值，但不是当前架构入口：

- `architecture-and-extension.md/html`：2026-08-26 架构快照，已由 `architecture.md` 取代。
- `tickflow-unification-master-plan.md`：从 Quantall prototype 迁移到独立仓库的历史总规划。
- `quantx-unified-data-foundation-plan.md`：Market Facts 建设计划与逐阶段实施证据。
- [`quantx-independent-update-audit-20260828.md`](quantx-independent-update-audit-20260828.md)：2026-08-28 的 QuantX 目录独立、联网更新、Market Facts 覆盖和 JSON 兼容剩余审计快照。
- `prototype-integration.md`：原型阶段记录。

历史文件不得指导新代码路径；如与当前权威文档冲突，以当前源码、测试和六份权威文档为准。

## 文档变更规则

1. 行为或契约变化必须在同一提交更新对应权威文档。
2. 设计目标必须标记“未实现”，不能用示例暗示 API 已存在。
3. 命令必须能从仓库根目录或明确标注的工作目录执行。
4. 数据字段必须写明单位、空值、日期和来源语义。
5. 迁移完成后将计划移入历史区，不继续把运行说明追加到规划文件。
6. 只改文档也必须运行 `python scripts/validate_project_contracts.py` 和 `git diff --check`。
