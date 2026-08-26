# 原型能力接入记录

> 日期：2026-08-24。范围仅限 `prototypes/tickflow`；参考项目保持只读。

## 1. 接入总览

| 来源 | 已接入 TickFlow 的能力 | 入口 | 数据口径 |
| --- | --- | --- | --- |
| `openclarr-chanlun` | 合并 K 线、分型、笔、线段、笔/线段中枢、MACD、买卖点；本地/ZenChart 官方/叠加三档 | 个股分析 → 缠论 | 图层与底层 K 线使用同一时间序列 |
| `openclarr-chanlun` | 全部 20 个主图叠加、39 个副图指标 | 所有 `EChartsCandlestick` 指标选择器 | 浏览器内纯函数计算，参数可持久化 |
| `onchart-top` | 板块资金趋势、板块雷达、宏观离散度、风险仓位、Kelly 与蒙特卡洛 | 市场实验室 | 优先复用本地 ETF/指数/股票日线 |
| `reference-prototype` 图一 | ETF 1/5/20/50 日收益、加权动量、斜率动量、量比、前日排名变化 | 市场实验室 → ETF 动量 | 收益单位为百分数 |
| `reference-prototype` 图二 | 近 3 日板块资金趋势、右端标签、正负语义、口径提示 | 市场实验室 → 板块资金 | 真资金流优先；否则明确标为代理 |

## 2. 缠论核心与进阶能力

核心流水线位于 `backend/app/chanlun/`，API 为：

- `POST /api/chanlun/analyze`：一次返回 `merged_klines / fenxing / bi / segments / zhongshu / zhongshu_seg / macd / bsp`。
- `GET /api/chanlun/candles`：先读本地；不足时通过**设置中当前选中的日线 provider**补齐且不落盘。第三方源失败时返回现有本地数据，不暗中换回 TickFlow。
- `GET /api/chanlun/official`：ZenChart 免费或 Pro 图层，仅用于结构对照。

OpenClarr 原型还列出了形态识别、信号面板、买卖点回测、多股扫描、回放、画线、截图和快捷键。接入策略如下：

| 进阶项 | TickFlow 接法 | 状态/边界 |
| --- | --- | --- |
| 五类形态（头肩顶/底、双顶/底、三角） | 新增独立 pattern detector，输出证据点后作为 ECharts marker/range | 设计完成，不能把启发式形态当缠论官方结果 |
| 信号面板 | 合并 BSP、技术指标与策略信号，保留 `source`、时间和是否确认 | 复用现有信号体系，不新增第二套互相矛盾的信号仓库 |
| BSP 回测 | 把 BSP 映射为现有 Backtest 策略输入 | 复用交易成本、停牌和涨跌停约束 |
| 多股扫描 | 把 BSP/形态字段接入现有 Screener | 必须基于已落地快照，避免页面请求逐股抓取 |
| 回放 | ECharts 窗口截断并逐 bar 重算，防止未来函数 | 前端交互项；回测结果仍以后端为准 |
| 画线/截图/快捷键 | 复用 `ChartPriceLine`、`ChartRange` 和浏览器导出 | 用户标注与算法图层分开存储 |
| 多周期 | 日线已接入；分钟周期走当前 minute provider | 周线/月线可由日线聚合，分钟质量取决于所选源 |

## 3. OpenClarr 指标完整对齐

主图 20 个：

`BOLL, EMA, SMA, BBI, SAR, ZIGZAG, TEMA, Supertrend, Donchian, Keltner, Ichimoku, VWAP, DEMA, HMA, Alligator, WMA, VWMA, LinReg, KDJCh, WRCh`

副图 39 个：

`MACD, KDJ, RSI, WR, CCI, BIAS, OBV, VR, ATR, DMI, MTM, ROC, MFI, CMF, CMO, TRIX, TSI, Stoch, StochRSI, PPO, DMA, UO, Vortex, PSY, Chop, AO, Aroon, PVT, DPO, ForceIndex, EMV, ADL, ChaikinOsc, ElderRay, TTMSqueeze, STC, CR, BRAR`

此前 TickFlow 已有全部副图和 18 个主图。本次补齐 `KDJCh`、`WRCh`：两者按 OpenClarr 原公式绘制对应周期的价格 HHV/LLV 通道，KDJ/WR 本身仍在副图中显示。

## 4. 市场实验室公式

### ETF 动量

- 区间收益：`(close_t / close_(t-n) - 1) × 100`。
- 加权动量：`1日×0.4 + 5日×0.3 + 20日×0.2 + 50日×0.1`。
- 斜率动量：最近 20 日对数收盘价线性回归，`(exp(slope×252)-1)×100×R²`。
- 量比：最近 5 日平均成交量 / 最近 20 日平均成交量。
- 同时计算前一交易日排名、排名变化和加权动量变化。

### 板块资金与雷达

- 若扩展数据含 `main_net_inflow / main_net / net_inflow`，按真实字段聚合并标记 `quality=observed`。
- 若无真实资金流，资金压力代理为：`((2C-H-L)/(H-L)) × amount`，标记 `quality=proxy`。它只表达收盘位置与成交额的联合压力，**不等于主力净流入**。
- 雷达收益优先按流通市值加权，无市值列时使用成分股等权收益。
- EMA 摆动使用 OpenChart 参数 `alpha_fast=0.24`、`alpha_slow=0.22`。
- 评分：收益分位 45% + 资金比分位 45% + EMA 摆动最多 10 分。所有分项同时返回，避免黑盒总分。

### 宏观离散度

- 对核心指数 20 日收益计算 `D = sqrt(sum((r_i - mean(r))²))`。
- 返回各指数有符号偏离与平方贡献占比、D 的 3 日均线和当前历史分位。
- D 衡量分化，不是上涨或下跌方向信号。

### 仓位与模拟

- 风险预算：`账户资金 × 单笔风险比例`。
- A 股整手仓位：`floor(风险预算 / 每股风险 / 100) × 100`。
- B1 勇气/敏感预设为目标 `10R/6R`、保本 `4R/2.5R`；B2 为目标 `5R/3R`、保本 `1R/2R`，与 OneChart 原型一致。
- 出坑目标：`坑口×2-坑底`；同时展示坑深和相对当前价的潜在空间。
- 回撤保护：实际盈亏比 `(最高价-买入价)/(买入价-止损价)`；保护退出价为 `最高价-(最高价-买入价)×回撤比例`。
- Kelly：`p - (1-p)/b`，同时展示半 Kelly、期望 R 与盈亏平衡胜率。
- 蒙特卡洛使用固定 seed，可复现地输出终值 P10/P50/P90、最大回撤 P50/P95、亏损概率及样例路径。

## 5. API 与空态

新增 API：

- `GET /api/market-lab/etf-momentum`
- `GET /api/market-lab/sector-flow?dimension=industry|concept`
- `GET /api/market-lab/sector-radar?dimension=industry|concept`
- `GET /api/market-lab/macro-dispersion`
- `POST /api/market-lab/position`
- `POST /api/market-lab/pit`
- `POST /api/market-lab/drawdown`
- `POST /api/market-lab/simulate`

没有本地 ETF、指数或板块维度时，接口返回 `available=false` 和明确原因；页面显示空态，不制造样例数据冒充真实行情。

## 6. QuantX / Quants / QuantT / 主面板协同

四者的源码边界、版本化 sidecar 契约、主线与形态交集评分、真实交易反馈回路，详见 [Quantall 协同接入与本地财务方案](system-integration-and-local-financials.md)。本次只完成分析设计，没有修改三个兄弟应用，也没有直接读取或写入它们的生产数据库。

## 7. 财务分析本地化

当前后端已经支持声明 `financial` 数据集的 custom provider，并会绕过 TickFlow Expert 的 `Cap.FINANCIAL` 门槛；现有财务 Parquet、API、页面和 AI 分析链路均可复用。stock-sdk 不提供该数据集。所需本地适配服务、字段契约、候选来源与质量门禁同样记录在 [Quantall 协同接入与本地财务方案](system-integration-and-local-financials.md)。本次未在未经验证的免费上游之上制造“可用”实现。

## 8. 验证清单

- 后端：公式、单位、确定性、API 成功/空态、provider 路由。
- 前端：TypeScript + Vite 生产构建。
- UI：独立 Python Playwright + Edge，拦截市场实验室 API 注入明确标识的合成数据，只验证渲染与交互；实际 API 空态另行验证。
- 数据风险：资金代理必须显示口径；百分数与小数、万元与元必须有回归测试。
