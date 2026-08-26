# Quantall 协同接入与本地财务方案

> 核查日期：2026-08-24。本文只修改 TickFlow 文档；`apps/quantx`、`apps/quants`、`apps/quantt` 均为只读核查。事实来自当前源码，未落地的部分明确标为方案。

## 1. 结论

- TickFlow 适合作为统一行情与决策工作台，但不应直接写另外三个应用的数据库。
- QuantX 提供环境、主线与证据结论；Quants 提供形态候选和 5/10/20 日跟踪；QuantT 提供真实交易复盘与个人风格反馈。最有价值的连接点是 **QuantX 主线 × Quants 候选**，其次是 **交割单 → QuantT → 风格统计回流**。
- 财务分析页不需要重写。现有后端已经允许带 `financial` 数据集的 custom provider 绕过 TickFlow Expert 门槛；本地实现只缺适配服务、字段规范、质量门禁和可用的上游来源。
- stock-sdk 不声明 `financial`，因此把行情切到 stock-sdk 不能解锁财务页。

## 2. 当前四个工位的边界

| 工位 | 当前源码已具备 | 应交给 TickFlow 的最小产物 | 不应做的事 |
| --- | --- | --- | --- |
| QuantX | 每日环境、主线题材、研究报告、证据与关注名单 | 带交易日和证据链接的环境/题材/关注 JSON | TickFlow 不直接改写其报告、知识库或发布状态 |
| Quants（`ppgu`） | 五类形态候选、行业/概念标签、信号案例与 5/10/20 日跟踪 | 候选快照：symbol、strategy、score、industry、concepts、signal_date、run_id | TickFlow 不直连并写入 24GB 生产 DuckDB |
| QuantT | 盲 K 训练、结构化决策、AI 点评、画像、JSON/Markdown 导出 | 成交/复盘摘要和按风格聚合的胜率、盈亏比、纪律偏差 | 当前没有交割单导入，不得把模拟训练表现冒充真实交易反馈 |
| TickFlow 主面板 | 日/分钟/实时行情、本地 Parquet/DuckDB、选股/回测/个股分析/市场实验室 | 只读聚合前三者的决策卡，并维护来源、日期和新鲜度 | 不复制三个应用的内部状态机，不成为第二份事实库 |

以上与仓库当前 `docs/trading-system.md` 的“环境与深研 → 形态收敛 → 复盘进化”定位一致。该仓库文档同时确认：QuantX 与 Quants 的自动交集、QuantT 的真实交割单导入目前仍是缺口。

## 3. 推荐接入顺序

### 阶段 A：只读文件契约

每个应用在自己的正常流程结束后原子写出一个小型 sidecar；TickFlow 只读导入，不跨库查询：

```text
QuantX daily_context.v1.json ─┐
                              ├─> TickFlow decision-funnel service ─> 主面板“决策漏斗”
Quants candidates.v1.parquet ─┘

QuantT style_feedback.v1.json ──> TickFlow 风格校准卡
```

共同信封建议固定为：

```json
{
  "schema_version": 1,
  "producer": "quantx|quants|quantt",
  "as_of": "YYYY-MM-DD",
  "generated_at": "ISO-8601",
  "source_run_id": "...",
  "quality": "observed|derived|insufficient",
  "data": {}
}
```

TickFlow 导入时必须校验版本、交易日、重复 symbol、生成时间和来源 run id；过期产物应显示“已过期”，不能静默沿用。

### 阶段 B：主线与形态交集

先做确定性打分，不让 LLM 参与数值排序：

- 40% Quants 形态分；
- 25% QuantX 主线/行业命中；
- 15% TickFlow 板块雷达分；
- 10% 流动性与成交额质量；
- 10% 后续跟踪先验；新信号没有历史时标记缺失，不补零伪装。

结果保留每一分项、标签映射依据和未命中原因。短名单可以由用户手工送入 QuantX 待分析清单；自动写入属于跨应用写操作，应另设确认与幂等接口。

### 阶段 C：真实交易反馈

QuantT 当前可导出训练/点评 JSON，但仓库文档明确真实交割单导入尚未完成。因此当前只能展示训练侧反馈。待 QuantT 支持交割单后，再按 `strategy/style × market_regime` 聚合真实胜率、盈亏比、MAE/MFE 和纪律偏差，回流为阶段 B 的先验；样本量不足时不得参与打分。

### 为什么不直接合并数据库

- 四个应用的 schema、迁移、锁和永久数据规则不同。
- Quants 生产库体量大，TickFlow 页面请求直接查询会扩大锁竞争和性能耦合。
- 小型版本化产物可重放、可审计，也能清楚区分“来源事实”和 TickFlow 派生结果。

## 4. 财务页为何显示 Expert

观察到的当前实现：

1. `/api/financials/*` 默认检查 TickFlow `Cap.FINANCIAL`。
2. `backend/app/services/financial_sync.py::_financial_is_custom()` 会读取 `financial_data_provider`；若不是 `tickflow`，且 provider 声明 `financial` 数据集，则允许访问和同步。
3. `GenericHTTPProvider.get_financials()` 会把 `table` 注入上游请求，支持 `metrics / income / balance_sheet / cash_flow / shares`，随后沿用现有 Parquet、DuckDB 视图、API、页面与 AI 分析链路。
4. 前端也以 `status.available === true` 作为解锁条件，因此 custom provider 可真正显示面板；页面标题仍写“Expert”只是文案未区分数据源。
5. stock-sdk 的能力声明没有 `financial`，不会触发上述绕过路径。

因此，本地财务实现的最小闭环不是解除能力检查，而是新增一个真正提供 `financial` 数据集的 provider。

## 5. 本地财务适配服务设计

### 推荐形态

在本机运行一个只读 HTTP adapter，统一屏蔽各免费来源的参数、字段和反爬差异：

```text
TickFlow GenericHTTPProvider
  -> GET http://127.0.0.1:<port>/financials
     ?table=metrics|income|balance_sheet|cash_flow|shares
     &symbols=600519.SH,...
  -> {"data": [{"symbol": "600519.SH", "period_end": "2026-06-30", ...}]}
```

custom source YAML 只需配置一个 `financial` dataset、`response_path: data` 和字段映射。现有 loader 会从环境变量读取认证信息；本地无认证服务也应只绑定 `127.0.0.1`。

### 来源优先级

| 能力 | 首选候选 | 备用候选 | 备注 |
| --- | --- | --- | --- |
| 三大报表 | 交易所/巨潮定期报告结构化结果，或东财/新浪公开报表接口 | mootdx F10 | 免费网站接口无 SLA，字段与历史覆盖需逐项实测 |
| 核心指标 | 从三表本地计算 | 上游现成指标交叉核验 | ROE、毛利率、现金含量等应记录公式和报告期 |
| 股本历史 | mootdx F10/东财股本变动 | 公告解析 | 必须保留生效日，不能只留最新股本 |
| 公告证据 | 巨潮公告 | 交易所公告 | 原文链接与披露时间作为证据，不把抓取摘要当原始报表 |

这些是接入候选，不是本次已验证可长期调用的接口。网站接口的授权、反爬和字段稳定性仍需独立评估。

### 最小字段与质量门禁

所有表至少需要：`symbol`、`period_end`、`report_type`、`published_at`、`source`、`fetched_at`。金额统一为元，比例统一为小数，空值保持空值。

- `income`：营业收入、营业利润、利润总额、归母净利润、扣非归母净利润。
- `balance_sheet`：总资产、总负债、股东权益、货币资金、有息负债。
- `cash_flow`：经营/投资/筹资净现金流、资本开支。
- `shares`：总股本、流通股本及生效日。
- `metrics`：只从有来源的报表字段计算；返回公式版本。

写入前应拒绝 symbol/报告期缺失、同表同标的同报告期重复、累计值与单季值混淆、单位跳变、资产不等于负债加权益的异常。修订报表按 `published_at` 保留最新版本，并保存原始来源哈希。

## 6. 尚未实施与验收门槛

本次完成的是源码级接入设计，没有改动 QuantX、Quants、QuantT，也没有伪造它们的 sidecar；本地财务 adapter 也尚未实现，因为尚未选定并验证上游来源及字段授权。

后续实现的验收门槛：

- 用至少 10 只股票覆盖沪深北、金融/制造和不同报告期，逐字段与公告或第二来源核对。
- 连续四期三表勾稽、单位、累计/单季口径通过；股本变更能正确影响换手率计算。
- custom provider 断网、空结果或 schema 漂移时 fail closed，不回退并覆盖已有正确数据。
- 财务页明确显示 provider、报告期、披露时间和质量等级，不再笼统显示“Expert”。
- 跨应用产物只能读取，任何回写动作另设用户确认、幂等键和审计日志。
