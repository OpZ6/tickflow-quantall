# TickFlow 开发文档入口

## 人读全景报告

- TickFlow 全景架构报告（本地可选产物 `docs/tickflow-architecture-report.html`）：面向产品、数据和二次开发者的可视化 HTML 导读，解释数据层、处理层、展示层、两类数据入口、存储、QuantX 独立流水线、插件与新增功能路径。该文件不属于源码仓库；具体契约仍以下方六份权威文档和当前源码为准。

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

- [量化研究与回测实战入门](../prompt/quant-backtest-primer.md)：面向交易新人的量化概念、A 股回测口径、因子检验、防过拟合和实盘执行速览；另有 [可视化 HTML 报告](../prompt/quant-backtest-primer.html)。
- [量化策略研发通用规范](research/strategy-development-methodology.md)：所有选股与交易策略共用的研究顺序、时间隔离、Alpha 评价、适用期验证、反过拟合和证据要求。
- [右侧中短线波段方向合同](research/right-side-swing-operating-system-20260910.md)：身份与停止边界。迭代用法见[策略迭代助手](research/strategy-iteration-assistant.md)。
- [量化选股策略迭代主计划](research/quant-development-plan.md)：当前策略队列、数据状态与阶段计划；具体正在执行的任务见根目录 `goal.md`。
- [VCP 研究记录](research/vcp/README.md)：交易闭环配置、独立运行归档、首轮诊断和正式优化的数据前置条件。

- [Quants 策略核心迁移验收](spec/quants-strategy-core-acceptance-20260905.md)：当前名称、V2 默认排除、核心语义回归证据与数据限制；用户已将要求调整为核心思路一致。原完整迁移计划已移入 [`archive/20260907/`](archive/20260907/)。
- [stock-chart-workbench.md](stock-chart-workbench.md)：个股分析唯一 K 线实例、统一行情 API、20+42 指标（含1AMV三副图、超跌与拐点）、缠论/价位/五类经典形态/正式结构策略/派生事件/画线和验证契约。
- [quantx-data-pipeline.md](quantx-data-pipeline.md)：QuantX 运行、重试、重算和故障诊断手册。
- [quantx-single-day-canonical-view-plan.md](quantx-single-day-canonical-view-plan.md)：QuantX 单日富图表从兼容 JSON 迁移到权威事实与确定性 ViewBuilder 的分批执行计划和验收清单。
- [quantx-unified-dashboard-design.md](quantx-unified-dashboard-design.md)：QuantX 多日驾驶舱与单日富图表合并为统一高密度看板的内容、排版和零丢失设计。
- [quantx-static-export.md](quantx-static-export.md)：把指定日期 QuantX 看板导出为保留图表、筛选和下钻交互且无本地服务依赖的单文件 HTML，并通过 Edge 做断网验收。
- [股票池正式实现与运行说明](research/stock-pools/implementation-plan.md)：九路召回、统一候选快照、题材与阶段工作台、API、每日发布和恢复入口。
- [quantx-unified-dashboard-execution-plan.md](quantx-unified-dashboard-execution-plan.md)：统一看板按可回滚批次实施的文件边界、数据调用链、验证矩阵和完成定义。
- [secondary-development.md](secondary-development.md)：原项目二次开发、插槽和扩展契约。
- [configuration.md](configuration.md)、[deployment.md](deployment.md)：配置与部署。

## 历史和审计文档

下列文件保留追溯价值，但不是当前架构入口：

- `archive/20260907/`：已归档的架构快照、迁移计划、数据源比较、QuantX 审计、原型记录和 v0.2.3 同步记录。

历史文件不得指导新代码路径；如与当前权威文档冲突，以当前源码、测试和六份权威文档为准。

## 文档变更规则

1. 行为或契约变化必须在同一提交更新对应权威文档。
2. 设计目标必须标记“未实现”，不能用示例暗示 API 已存在。
3. 命令必须能从仓库根目录或明确标注的工作目录执行。
4. 数据字段必须写明单位、空值、日期和来源语义。
5. 迁移完成后将计划移入历史区，不继续把运行说明追加到规划文件。
6. 只改文档也必须运行 `python scripts/validate_project_contracts.py` 和 `git diff --check`。

## 上游 0.4.1 文档导航（随上游合并引入）

以下入口来自上游 v0.4.1，以 `tsp-0.4.1` 候选工作区为准。安装器与公开镜像以 [Releases](https://github.com/shy3130/tick-stock-panel/releases) 中对应制品为准；本仓库的本地优先级仍以上方六份权威文档为准。

### 使用工作台

| 要完成的任务 | 文档 |
| :--- | :--- |
| 首次部署、升级、保留原数据 | [0.4.1 版本说明](./release-v0.4.1.md) · [部署指南](./deployment.md) · [访问密码](./deploy-password.md) · [环境和数据配置](./configuration.md) |
| 使用自选、看板、监控、模拟盘等页面 | [操作说明书](../操作说明书.md) · [功能手册](./features.md) · [截图索引](../screenshots/README.md) |
| 在个股详情配置字段、日 K 显示范围和指标 | [个股详情与自定义图表指标](./custom-chart-indicators.md) |
| 自建策略、因子、信号或导入资源 | [策略指南](./strategy.md) · [导入与备份](./extension-packages.md) |
| 分析市场阶段、挖掘因子与验证结果 | [市场环境](./market-phase.md) · [因子与策略挖掘](./mining.md) · [回测证据](./backtest-evidence.md) |
| 选择前复权、后复权或动态复权，运行归档研究任务 | [策略回测](./features.md#-回测引擎backtest) · [动态复权](./engine-platform/workbench-research-jobs.md#动态复权扩展) · [引擎研究](./engine-platform/workbench-research-jobs.md) |

### 让 AI 接入或开发

| 要完成的任务 | 文档 |
| :--- | :--- |
| 选择内置助手、外部 MCP、REST 或扩展开发 | [AI 接入与二次开发](./ai-integration.md) |
| 连接外部 AI 客户端、脚本或工具 | [MCP 客户端配置](../mcp-server/README.md) · [Open API 可运行示例](../examples/open-api/README.md) |
| 让 AI 生成和迭代策略 | [策略写法](./strategy.md) · [迭代、台账与验证](./strategy-iteration.md) |
| 让 AI 改源码、接入插槽或注册后端能力 | [AI 开发入口](../AGENTS.md) · [二次开发与任务模板](./secondary-development.md) · [贡献指南](../CONTRIBUTING.md) |

### 扩展契约与示例

| 扩展类型 | 开发与试装 |
| :--- | :--- |
| 自定义 HTTP 数据源 | [YAML 格式](./custom-data-source.md) · [示例与 mock 联调](./examples/custom-data-source/README.md) |
| Python 数据源插件 | [Provider 契约](./plugin-development.md) · [ZIP 模板](../examples/data-source-plugin/README.md) · [外部 ZIP 安装](./external-data-source-packages.md) · [双端数据源示例](../examples/dual-host-data-source/README.md) |
| 自定义数据表、页面与菜单 | [单表配置分享](./extension-packages.md#单个扩展数据配置分享) · [Page Pack SDK](./page-sdk.md) · [页面模板](../frontend/page-pack-template/README.md) · [源码页面目录](../frontend/src/custom/README.md) |
| 后端能力、通知、仓位和模拟盘 | [后端注册入口](../backend/app/custom/README.md) · [外部扩展包](./extension-packages.md#后端--前后端完整包) · [模拟盘执行契约](../backend/app/custom/paper_execution/README.md) |
| 指标公式与图表宿主 | [指标公式与适用范围](./custom-chart-indicators.md) · [模块边界与接入记录](./custom-chart-indicators-integration.md) |
| 引擎数据、规则、扩展和更新 | [数据与市场契约](./engine-platform/data-and-market-contracts.md) · [发行、授权及回退](./engine-platform/extensions-and-releases.md) |
| 独立组件接口 | [Tivelo Data](../packages/tivelo-data/README.md) · [Tivelo Backtest](../packages/tivelo-backtest/README.md) · [Contracts](../packages/tivelo-contracts/README.md) · [Extensions](../packages/tivelo-extensions/README.md) · [A 股规则](../packages/tivelo-market-cn/README.md) |
| 维护品牌资源与应用图标 | [品牌资产](../brand/README.md) |

### 设计和历史记录

接口、UI 操作和安装步骤以上面的使用及开发文档为准。以下材料保留设计取舍和当时的验证条件。

- [扩展分层设计](./ext-architecture-plan.md) · [开放接口路线图](./open-platform-plan.md)
- [因子系统设计](./factor-system-design.md) · [因子平台规划](./factor-platform-plan.md) · [自动策略实验室](./auto-strategy-lab-plan.md) · [稳健优化设计](./robust-optimizer-plan.md)
- [模拟盘设计](./paper-trading-plan.md) · [个股图表技术设计](./stock-detail-lightweight-charts-plan.md) · [后端性能计划](./backend-data-performance-plan.md)
- [TickFlow 早期探测](./tickflow-pro-phase1-probe.md) · [共享限流设计](./tickflow-pro-shared-rate-limit.md)

应用运行时使用的策略提示词见 [策略模板与编写规范](../backend/app/strategy/prompts/strategy-guide.md)。它们随代码使用，外部 AI 任务从 [AI 接入指南](./ai-integration.md)开始。
