# Goal：TickFlow 统一 K 线形态、策略信号与证据图层

> 状态：Ready for execution
>
> 目标仓库：`D:\tickflow-quantall`
>
> 参考实现：`D:\quantall\apps\quants`，只用于算法和交互语义对拍，不得成为运行时依赖
>
> 执行方式：按 P0 → P4 连续完成实现、迁移、测试、页面验证、文档、提交和推送；不得只输出新方案或停在半成品脚手架

## 1. 最终目标

在 TickFlow 已有“唯一一张个股 K 线”基础上，增加统一、可追溯、可回放的形态和策略证据图层，使用户可以从策略面板点击股票后，直接在同一张 K 线上看到：

1. 客观市场事件；
2. 独立于策略的价格/量能形态；
3. 当前策略及历史策略的入场、离场、失效和再触发信号；
4. 策略为何命中的条件、指标、阈值、评分和关联形态；
5. 触发位、枢轴位、支撑位、失效位和观察区间；
6. 回测成交、实时监控触发与策略计算信号之间的明确区别。

最终用户链路必须形成闭环：

```text
策略面板命中结果
  → 点击股票
  → 打开个股统一 K 线
  → 自动激活来源策略图层
  → 显示该策略买卖信号与历史生命周期
  → 点击标记查看命中原因、参数版本和股票级证据
  → 可切换其他策略或查看多策略共振
```

完成后，统一 K 线应从“指标很多的图表”升级为：

```text
看见走势
→ 识别形态和市场结构
→ 理解策略为什么命中
→ 回看信号如何演变、何时失效
→ 核对每个结论的数据与算法证据
```

## 2. 执行前必须遵守

开始修改前必须完整阅读并遵守：

- `AGENTS.md`
- `CONTRIBUTING.md`
- `docs/README.md`
- `docs/architecture.md`
- `docs/data-foundation.md`
- `docs/analysis-development.md`
- `docs/secondary-development.md`
- `docs/stock-chart-workbench.md`
- `docs/upstream-sync.md`

先运行并记录：

```powershell
git status --short --branch
git fetch origin
```

保护任务开始前已有的修改和未跟踪文件。只暂存本任务文件，禁止使用 `git add .` 或 `git add -A`。

项目事实必须以当前源码和测试为准。本文中的拟议文件名、接口名和类型名属于目标设计；执行前必须确认现有调用链，必要时用更贴合当前代码的名称实现，但不得降低本文的行为契约和验收标准。

## 3. 当前基线与必须保留的能力

当前统一 K 线已经具备：

- 单一 ECharts 实例；
- 20 个主图指标、38 个副图和成交量；
- `1m/5m/15m/30m/60m/1d/1w/1mo` 周期；
- 不复权、前复权、后复权；
- 1 月、3 月、半年、1 年、3 年、5 年、全部和自定义日期范围；
- 关键价位；
- 本地缠论与可选官方对照；
- 头肩顶、头肩底、双顶、双底、三角形五类启发式形态；
- 涨停、炸板标记；
- 水平线、趋势线、文字、撤销、重做和清除；
- 截图；
- 逐根回放；
- 图表布局、指标参数、预设和画线持久化。

实施不得丢失或拆分上述能力，不得重新出现多个相互独立的 K 线实例。旧组件可以保留为兼容入口，但个股分析主路径只渲染一个统一图表实例。

执行前至少核对以下当前入口：

- `frontend/src/features/stock-chart/UnifiedStockChart.tsx`
- `frontend/src/features/stock-chart/indicatorRegistry.ts`
- `frontend/src/features/stock-chart/patterns.ts`
- `frontend/src/components/EChartsCandlestick.tsx`
- `backend/app/services/chart_data.py`
- `backend/app/strategy/engine.py`
- `backend/app/services/strategy_cache.py`
- `backend/app/api/screener.py`

## 4. 范围与非目标

### 4.1 本 Goal 必须完成

- 统一图层数据契约和前端渲染契约；
- 现有事件、价位、五类形态迁入统一图层；
- Quants 的 VCP、杯柄、高而紧旗形、启动后缩量回踩四类形态独立移植；
- 策略结果结构化证据；
- 策略面板与个股 K 线双向关联；
- 策略信号历史存储与查询；
- 入场、离场、失败、守轴、再触发和多策略共振展示；
- 回放无未来数据泄漏；
- 标注密度控制、证据抽屉、错误隔离；
- 对应后端、前端、API、契约和 Playwright 测试；
- 当前权威文档更新；
- 聚焦提交并推送当前分支。

### 4.2 本 Goal 不做

- 不引入 LLM 分析或让 LLM 决定形态和信号；
- 不给出个性化买卖建议；
- 不把策略信号描述为真实成交；
- 不把形态拟合分数描述为胜率或成功概率；
- 不复制第二套行情、复权、指标或 K 线 API；
- 不把 Quants 的 PySide/Matplotlib 界面迁入 TickFlow；
- 不在运行时 import、读取或调用 `D:\quantall\apps\quants`；
- 不让前端重新实现后端已有的策略业务算法；
- 不把用户策略派生事件误存为客观 Market Facts；
- 不顺带重构无关页面、策略引擎或数据流水线。

## 5. 四类标注的权威边界

四类标注必须在类型、存储、图例、详情和文案中明确区分：

| 类别 | 回答的问题 | 是否依赖策略 | 典型内容 |
| --- | --- | --- | --- |
| `event` | 当天客观发生了什么 | 否 | 涨停、炸板、市场事实事件 |
| `pattern` | OHLCV 形成了什么结构 | 否 | VCP、杯柄、旗形、双顶等 |
| `strategy` | 某策略为何在某日命中或离场 | 是 | 入场、离场、失败、评分、条件 |
| `plan` | 策略关注哪些价位和区间 | 是 | 触发、枢轴、支撑、失效、再触发窗口 |

示例：

```text
VCP 收缩形态成立                    ← pattern
趋势突破策略在 2026-08-28 命中      ← strategy
60 日新高且量比 1.82 ≥ 1.50         ← strategy evidence
枢轴 18.62、失效位 17.90            ← plan
```

不得把以上内容合并为一个没有来源、算法版本和条件证据的“VCP 买点”。

## 6. 目标图层结构

统一 K 线只保留一个图表实例，并提供以下图层层级：

```text
行情
├─ K线 / 成交量
├─ 技术指标
│  ├─ 趋势
│  ├─ 动量
│  ├─ 波动
│  └─ 量价
├─ 市场结构
│  ├─ 缠论
│  ├─ 关键价位
│  └─ 用户画线
├─ 形态研究
│  ├─ VCP
│  ├─ 杯柄
│  ├─ 高而紧旗形
│  ├─ 启动后缩量回踩
│  ├─ 头肩顶 / 头肩底
│  ├─ 双顶 / 双底
│  └─ 三角收敛
├─ 策略信号
│  ├─ 当前选中策略
│  ├─ 历史入场 / 离场
│  ├─ 失败 / 守轴 / 再触发
│  └─ 多策略共振
└─ 市场事件
   ├─ 涨停
   ├─ 炸板
   └─ 其他标准事件
```

## 7. 统一图层契约

### 7.1 图层响应

建立版本化、小粒度、与 ECharts 无关的领域契约。推荐形态如下：

```ts
interface ChartAnnotationLayer {
  schemaVersion: 1
  id: string
  category: 'pattern' | 'strategy' | 'event' | 'plan'
  title: string
  status: 'available' | 'insufficient_data' | 'unavailable' | 'error'
  algorithmVersion?: string
  inputFingerprint?: string
  priceBasis: 'none' | 'qfq' | 'hfq'
  markers: AnnotationMarker[]
  lines: AnnotationLine[]
  zones: AnnotationZone[]
  segments: AnnotationSegment[]
  evidence: AnnotationEvidence[]
  warnings: string[]
}
```

具体子类型必须至少支持：

- 稳定 `id` 和 `layerId`；
- 日期和可选精确价格；
- 语义角色，而不是后端任意颜色；
- `evidenceId`；
- 起止日期；
- 水平线、斜线、区间和多段线；
- `detectedAt`、`confirmedAt`、`invalidatedAt`；
- 多标记聚合数量；
- 空数据、数据不足和算法错误状态。

后端返回语义，前端统一把语义映射为图标、颜色、线型和层级。不得让每个策略自行定义一套视觉语言。

### 7.2 后端 Provider

增加职责单一的内部 Provider 协议，不继承或覆盖 `StrategyEngine`、`KlineRepository` 等大型核心类：

```python
class ChartLayerProvider(Protocol):
    layer_id: str

    def build(self, context: ChartLayerContext) -> ChartAnnotationLayer:
        ...
```

至少拆分为：

- `MarketEventLayerProvider`
- `PatternLayerProvider`
- `StrategySignalLayerProvider`
- `StrategyPlanLayerProvider`

注册顺序稳定；重复 ID、未知版本和加载失败必须 fail-closed。单个图层失败只影响自身，不能让 `/api/kline/chart` 返回模糊 500。

### 7.3 API 接入

复用并向后兼容现有：

```text
GET /api/kline/chart
```

增加可选图层和策略选择参数，例如：

```text
layers=pattern,strategy,event,plan
strategy_ids=trend_breakout,pullback_to_support
```

响应增加可选字段：

```json
{
  "rows": [],
  "levels": {},
  "annotation_layers": []
}
```

最终参数命名应遵循当前 API 风格，但必须满足：

- 未传新参数时保持旧调用兼容；
- 图层与 candles 使用同一 Repository 数据；
- 使用同一周期、复权、聚合、预热、范围和结束日期；
- 不为标注再请求或生成另一份 K 线；
- 响应明确实际价格口径、覆盖范围、算法版本和警告；
- 图层查询维度进入后端缓存键和 TanStack Query key。

## 8. 数据与计算权威链路

唯一允许的调用链：

```text
MarketDataProvider
→ DataStore / KlineRepository
→ 复权
→ 周期聚合
→ 隐藏区间预热
→ indicators / key levels
→ pattern detectors
→ strategy evidence / historical events
→ chart layer providers
→ /api/kline/chart
→ frontend api.ts + queryKeys.ts
→ UnifiedStockChart
```

要求：

- 形态检测必须消费最终图表同口径 candles；
- 策略证据引用统一指标和形态结果，不重复计算另一套 VCP 或均线；
- `patternRefs` 引用带版本的形态结果；
- API handler 只校验参数、调用 Service 和映射响应；
- 页面不读取本地 JSON、Parquet 或供应商响应；
- 比例、价格、复权、交易日和时间周期遵守项目现有数据契约。

## 9. Quants 形态移植要求

Quants 只作为行为参考和测试对拍来源。算法必须在 TickFlow 仓库内独立实现，使用 TickFlow 自身数据、依赖和测试。

### 9.1 VCP

必须支持：

- Base 起点；
- C1/C2/C3 等收缩低点；
- 每段回撤深度、持续时间和量能变化；
- Pivot；
- 收敛上沿、下沿和收敛区域；
- 突破；
- 突破后守轴、失败和再触发阶段；
- `confirmedAt` 和算法版本；
- 悬停/点击证据。

### 9.2 杯柄

必须支持左杯沿、杯底、右杯沿、杯体深度、杯沿差异、杯柄起止、杯柄深度、杯柄量能比例，以及颈线或潜在突破位。买点只能作为形态候选价位，除非被具体策略引用。

### 9.3 高而紧旗形

必须支持旗杆起止、旗杆涨幅和持续时间、整理区上下沿、整理深度和量能变化、突破点、确认与失效时间。

### 9.4 启动后缩量回踩

必须支持启动日、启动中位支撑线、缩量回调区和回调日、支撑测试与失效点。

不得直接把该形态等同于 TickFlow 现有“缩量回踩”策略。先对齐算法定义；形态是独立结果，策略可以引用它。

### 9.5 现有五类形态

将当前头肩顶、头肩底、双顶、双底、三角形迁入同一图层契约。迁移后：

- 不丢失现有图形；
- 继续明确为本地启发式研究标记；
- 与官方缠论结论分离；
- 不允许每类形态直接拼接私有 ECharts option；
- 切换周期、复权和回放日期后使用当前 candles 得到一致结果。

## 10. 策略证据与买卖点关联

### 10.1 结构化证据

给策略结果增加向后兼容的可选证据。推荐契约：

```ts
interface StrategyEvidence {
  schemaVersion: 1
  strategyId: string
  strategyVersion: string
  paramsFingerprint: string
  symbol: string
  eventDate: string
  eventType: 'candidate' | 'entry' | 'exit' | 'failure' | 'support' | 'retrigger'
  score?: number
  reasonCodes: string[]
  metrics: EvidenceMetric[]
  anchors: EvidenceAnchor[]
  levels: EvidenceLevel[]
  patternRefs: string[]
  sourceRunId?: string
  provenance: 'observed_run' | 'recomputed'
}
```

其中：

- `reasonCodes` 保存稳定机器标识；
- `metrics` 保存实际值、阈值、单位和通过状态；
- `anchors` 指向具体交易日及 OHLC 锚点；
- `levels` 保存触发、枢轴、支撑和失效价位；
- `patternRefs` 引用形态结果，不重新运行形态算法；
- `paramsFingerprint` 隔离不同参数版本；
- `sourceRunId` 追踪策略运行批次；
- `provenance` 区分真实运行记录和历史重新计算。

### 10.2 所有策略的最低展示

每个内置、自定义或 AI 策略至少能显示候选/入选、入场信号、离场信号、策略名称和版本、参数指纹、分数，以及可获得的主要命中条件和失败条件。

没有专属适配器时使用通用标注，不能导致策略执行、策略页面或 K 线失败。

### 10.3 专属策略表达

| 策略族 | 图上证据 |
| --- | --- |
| 趋势突破、N 日新高 | 突破水平线、突破点、量能证据 |
| 布林突破 | 上轨突破、突破前收敛区 |
| MA 金叉、均线多头 | 交叉点、均线排列变化 |
| MACD 金叉 | K 线信号与 MACD 副图对应点联动 |
| 缩量回踩、MA20 反弹 | 回调区、MA20 支撑测试和缩量证据 |
| 超跌反转 | 超跌区间和反转确认点 |
| 连板接力、断板反包 | 涨停、断板、反包事件链 |
| 量价齐升、高换手拉升 | 放量柱、价格突破和量比阈值 |

### 10.4 策略面板强制闭环

策略面板中的股票必须提供明确的“查看 K 线/查看信号”入口。打开个股分析时必须携带或恢复：

- `strategyId`；
- `asOf`；
- 当前可用的 `sourceRunId`；
- 当前可用的 `paramsFingerprint`；
- 股票代码和资产类型。

统一 K 线随后必须：

1. 自动激活来源策略图层；
2. 定位目标信号日期；
3. 显示当前策略入场、离场和失败点；
4. 支持查看该策略历史信号；
5. 支持切换其他策略；
6. 支持显示同日多策略共振；
7. 返回策略面板时保留原筛选上下文。

必须支持直接刷新或复制链接后恢复策略上下文，不能只依赖不可恢复的组件内临时状态。

### 10.5 三类“买卖点”不得混淆

| 类型 | 含义 | 推荐视觉 |
| --- | --- | --- |
| 策略信号 | 算法条件在当时成立 | 实心三角 |
| 回测成交 | 模拟撮合器按交易约束产生的成交 | 带“回测”标签的独立标记 |
| 实时监控触发 | 盘中监控即时触发 | 带时间戳的闪电/圆点 |

前端文案、图例、tooltip 和证据抽屉必须使用准确名称。不得把策略信号或回测成交描述成真实账户成交。

## 11. 策略历史事件存储

现有 `strategy_cache.json` 继续承担当前页面快速缓存，但不能作为跨日历史事件权威来源。

新增 TickFlow 自有、分区化、可查询的派生策略事件存储。建议物理路径：

```text
data/strategy_signal_events/date=YYYY-MM-DD/part.parquet
```

最终路径可按现有 DataStore 约定调整，但必须满足：

- 不属于 Market Facts；
- 不进入 Git；
- 原子写入；
- 策略成功运行后幂等追加/覆盖同主键事件；
- 可按股票、策略、日期范围和事件类型查询；
- schema 版本化；
- 历史字段缺失可兼容读取；
- 写入后处理 Repository 缓存、generation/version、SSE 和前端 query invalidation。

建议唯一键至少包含：

```text
strategy_id
strategy_version
params_fingerprint
symbol
event_date
event_type
source_run_id
```

至少持久化入选、入场、离场、失败、守轴、再触发、分数、原因代码、指标证据、关键价位、关联形态 ID、策略版本、参数指纹、输入数据指纹和来源类型。

历史回填只能重算当前可重建的策略版本和参数。无法恢复的历史参数、当时数据源和运行环境必须显式标记未知，禁止伪装成真实历史运行记录。

## 12. 回放和防未来函数

每个形态必须有 `confirmedAt`。图形锚点可以出现在确认日之前，但回放日期早于确认日时不得展示完整形态。

显示规则至少满足：

```text
pattern.confirmedAt <= replayDate
strategy.eventDate <= replayDate
backtest.fillDate <= replayDate
realtime.triggeredAt <= replayTimestamp
```

要求：

- 杯柄不能在右杯沿和杯柄尚未形成时提前显示；
- VCP 不能利用回放日期之后的收缩或突破确认；
- 失效状态不能提前泄漏；
- 后续失效的历史形态可保留，但显示“已确认 → 后续失效”；
- 回放计算继续复用 `rowsAtReplay` 或等价的单一时间截断契约；
- 回放不得重新请求另一份行情；
- 必须用固定样本测试确认无未来数据泄漏。

## 13. 前端体验要求

### 13.1 图层管理器

将当前指标管理扩展为：

```text
技术指标 | 缠论 | 形态 | 策略 | 事件 | 画线
```

策略页签至少支持默认只显示来源策略、显示所有策略、仅入场、离场/失败、多策略共振、按策略筛选和恢复默认。

布局和选择状态继续进入版本化图表布局持久化；股票、周期和复权相关状态必须正确隔离。

### 13.2 统一视觉语义

- 空心节点：客观形态锚点；
- 实心向上三角：策略入场；
- 实心向下三角：策略离场；
- 红叉：失败或失效；
- 蓝点：支撑确认或再触发；
- 菱形：同日多策略共振；
- 淡色区域：形态、整理或观察区；
- 虚线：候选、触发或枢轴；
- 红色点划线：失效位；
- 黄色旗标：市场事件。

### 13.3 证据抽屉

点击形态或策略标记后显示日期、类别、状态、算法/策略版本、命中条件、实际值、阈值、单位、分数、关联形态、关键价位、参数指纹、运行批次、来源，以及数据不足或重新计算警告。

信息层级统一为：

```text
当前结论 → 历史趋势 → 结构解释 → 股票级证据
```

### 13.4 密度控制

- 同日多策略默认聚合为一个菱形并显示数量；
- 缩放较远时只显示高优先级事件；
- 缩放靠近时展开详细节点；
- 默认只开启来源策略和少量最高质量形态；
- 标签默认隐藏，悬停或选中后展开；
- 历史同类信号可限制最近 N 次，但不得删除底层事件；
- 标注不能遮挡主要蜡烛、坐标轴或副图数值；
- 桌面常用宽度和窄屏均无页面级横向溢出。

## 14. 分阶段执行与退出条件

### P0：统一图层底座

任务：

- 建立前后端版本化图层契约；
- 扩展 marker/line，增加 zone、segment 和 evidence；
- 增加小粒度图层 Provider 和失败隔离；
- 把涨停/炸板、关键价位和现有五类形态迁入统一契约；
- 实现图层管理器和证据抽屉；
- 保持现有 UI 行为和布局兼容。

退出条件：新旧视觉信息无丢失；旧 API 仍可用；页面只有一个 ECharts 实例；单层错误不会造成整图 500；定向后端测试、前端测试和构建通过。

### P1：四类 Quants 形态

按 VCP、启动后缩量回踩、杯柄、高而紧旗形顺序实现。每类必须在 TickFlow 内独立实现、使用统一 candles、输出统一图层、标记算法版本和确认日期、有正常/边界/数据不足/错误测试，并用固定样本与 Quants 行为对拍。

退出条件：四类形态均可独立开关、证据可读、复权/周期切换正确、回放无未来泄漏。

### P2：策略证据与策略面板关联

任务：

- 向后兼容扩展 `StrategyResult`；
- 统一 `entry_signal_hits`、`exit_signal_hits` 和结构化证据；
- 为所有策略提供通用适配；
- 为优先策略族补专属证据；
- 策略面板股票入口携带稳定上下文；
- K 线自动激活、定位并展示对应策略；
- 支持策略切换和多策略共振；
- 区分策略信号、回测成交和实时监控触发。

退出条件：至少对一个入场策略、一个离场策略、一个形态关联策略和一个自定义降级策略完成端到端验证；刷新深链接后仍能恢复策略上下文。

### P3：历史策略事件

任务：建立版本化派生事件存储和 Repository；策略成功运行后幂等持久化；提供按股票/策略/日期查询；接入 K 线；实现内置策略可控回填；区分真实运行和重新计算；完成缓存、SSE 和前端失效链路。

退出条件：重启后历史标记仍可读取；重复运行不产生重复事件；策略参数变化不会污染旧版本；真实运行和回填记录可辨认。

### P4：交互、回放、导出和性能收口

任务：标注聚合和密度控制；回放按确认时间过滤；形态—策略—事件联动；截图和已有导出路径保留标注；图表状态隔离；加载/空/错/数据不足状态；缓存键、请求数和大范围性能验证；更新权威文档和上游同步热点。

退出条件：完整验收矩阵和 standalone Playwright 通过，无控制台错误、失败网络请求、遮挡或横向溢出。

## 15. 测试与验收矩阵

### 15.1 后端

必须覆盖：

1. 图层 schema 序列化与向后兼容；
2. Provider 注册、排序、重复 ID 和失败隔离；
3. 四类新形态固定样本断言；
4. 五类旧形态迁移等价性；
5. 日、周、月和支持的分钟周期；
6. none/qfq/hfq 价格坐标一致性；
7. 数据不足、字段缺失和空数据；
8. `confirmedAt` 和回放无未来泄漏；
9. 策略证据、参数指纹和运行批次；
10. 策略事件幂等写入与查询；
11. `observed_run` 与 `recomputed`；
12. 单层异常不影响行情和其他图层；
13. 无 Quants 目录外依赖；
14. 缓存命中、精确失效和并发读取。

### 15.2 前端

必须覆盖：

1. 图层管理器六类页签；
2. 四类标注的视觉区分；
3. 策略面板到 K 线的上下文传递；
4. 自动激活和定位来源策略；
5. 策略切换和多策略聚合；
6. 证据抽屉字段与警告；
7. 回测成交、策略信号、实时触发三类图例；
8. 切换纯前端图层不重复请求行情；
9. 周期、复权、范围变化进入查询键；
10. 布局刷新恢复；
11. 加载、空、错、不可用和数据不足；
12. 浅色、深色、桌面和窄屏。

### 15.3 浏览器验证

必须使用 standalone Python Playwright 和 Microsoft Edge：

```python
p.chromium.launch(channel="msedge", headless=True)
```

至少验证：

- 个股分析只有一个图表 canvas；
- 从策略面板点击股票可打开并定位策略信号；
- 页面刷新后策略上下文恢复；
- 形态和策略图层可开关；
- 标注点击可打开正确证据；
- 周期、复权、范围和回放正常；
- 同日多策略聚合正常；
- 截图包含当前可见标注；
- 无 console error、失败网络请求和页面级横向溢出；
- 关键文字、标记和价位未被裁切。

保存关键阶段和最终页面截图作为验证证据，但不得提交临时截图或运行时数据。

## 16. 建议验证命令

根据最终改动补充精确测试文件，至少执行：

```powershell
cd D:\tickflow-quantall\backend
uv run --frozen pytest tests/test_chart_data.py tests/test_chanlun_pipeline.py -q
uv run --frozen pytest <新增图层、形态、策略事件和API测试> -q
uv run --frozen ruff check app/<本次模块> tests/<本次测试>

cd D:\tickflow-quantall\frontend
pnpm test:indicators
pnpm build

cd D:\tickflow-quantall
python scripts/verify_stock_chart.py
python scripts/validate_project_contracts.py
git diff --check
git status --short --branch
```

不能把未运行的检查写成通过。若仓库当前测试名或命令变化，使用当前权威命令并在最终报告中列出实际执行内容。

## 17. 硬性完成标准

只有同时满足以下条件才能声明 Goal 完成：

1. 策略面板命中股票可以进入统一 K 线并自动显示来源策略买卖信号；
2. 入场、离场、失败、守轴、再触发和多策略共振至少有真实端到端数据验证；
3. VCP、杯柄、高而紧旗形、启动后缩量回踩全部接入；
4. 现有五类形态、缠论、关键价位、指标、画线和回放没有丢失；
5. 策略证据包含版本、参数指纹、条件和来源；
6. 历史策略事件可跨重启读取，重复运行不重复写入；
7. 回放没有未来数据泄漏；
8. 策略信号、回测成交和实时触发不会混淆；
9. 图层异常不会造成整张 K 线失败；
10. TickFlow 可在没有 `D:\quantall`、Quants 服务和 Quants 虚拟环境时独立运行；
11. API 和历史数据向后兼容，或提供了经过测试的迁移；
12. 后端定向测试、前端构建、契约检查和 Playwright 验证实际通过；
13. 文档与当前实现一致；
14. 最终提交不夹带任务开始前用户改动；
15. 提交已推送，且本地 HEAD 与上游同步。

## 18. 回退、兼容与上游合并

- 开始实施前记录基线 commit；
- 每个阶段保持可单独回退；
- 新响应字段默认可缺失，前端能读取旧响应；
- 未启用新图层时，图表行为与当前版本一致；
- 新存储只追加派生资产，不覆盖原始行情和历史用户数据；
- schema 变化提供版本和兼容读取；
- 不删除旧组件或旧字段，除非已有迁移、调用方清零和回归证据；
- 在当前上游同步文档记录修改过的高冲突热点；
- 合并上游前使用仓库只读升级预检脚本检查重叠文件。

## 19. 执行纪律

- 不在完成 P0 后停止并重新输出规划；
- 不用 mock 图形或静态假数据冒充完成；
- 不因某类形态困难就静默跳过；
- 不把缓存 JSON 当作历史策略事实；
- 不在 API handler、React 页面或 ECharts option 中复制策略算法；
- 不引入第二套 Query key、行情请求或图表状态；
- 不用宽泛异常捕获把金融计算错误伪装为空结果；
- 不覆盖、回滚、删除或提交任务开始前已有改动；
- 遇到真正阻塞时，先穷尽仓库内安全路径，再报告具体证据和最小所需决策。

## 20. 最终交付报告格式

完成时只报告实际结果：

1. 实现了哪些形态、策略和事件图层；
2. 策略面板如何关联 K 线买卖点；
3. Repository → Service → API → 前端完整调用链；
4. 数据存储、schema、主键、版本和来源；
5. 回放和防未来函数设计；
6. 缓存、SSE 和前端失效路径；
7. 实际执行的测试、构建和 Playwright 结果；
8. 独立运行和无目录外依赖证据；
9. 剩余风险或明确未完成项；
10. 提交 SHA、推送结果，以及未触碰的用户原有修改。
