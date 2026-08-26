# TickFlow Stock Panel 源码级算法、数据流与数据源解构

> 审计日期：2026-08-23
> 上游仓库：https://github.com/shy3130/tickflow-stock-panel
> 审计提交：9b9538a70fa64d01314030b8823a508087f28c9d
> 项目版本：0.1.88
> 本地目录：D:\quantall\prototypes\tickflow
> 审计方法：源码静态追踪、无密钥启动、API 探测、standalone Playwright + Microsoft Edge 渲染检查、后端测试与前端构建验证。

## 1. 结论先行

TickFlow Stock Panel 是一个本地优先的 A 股研究工作台。它不是券商交易终端，也没有下单链路。核心价值不在单一策略，而在把数据接入、复权与指标、选股、回测、市场复盘、监控和 AI 文本分析放进同一套数据契约中。

源码显示的主链路是：

    TickFlow / stock-sdk / 自定义 HTTP / 扩展 CSV、Excel、JSON
        -> provider 能力检测与路由
        -> 字段归一化
        -> Parquet 分区与 DuckDB 视图
        -> 复权、技术指标、涨跌停与连续板特征
        -> 18 个内置策略 / 自定义信号 / 组合策略
        -> 选股、监控、策略回测、因子回测、市场状态与 AI 报告
        -> FastAPI REST/SSE
        -> React + TanStack Query + ECharts/lightweight-charts

本次无 API Key 运行成功，后端处于 None 档位，可启动、加载 18 个策略并提供全部 API；前端可正常完成首次引导并打开看板、策略、回测和设置页面。由于没有同步行情，页面展示为空状态，这不是算法结果为零的有效验证。

需要优先注意的源码事实：

1. 标准安装命令 uv sync --extra dev 当前会因 backend/pyproject.toml 的 readme = "../README.md" 被 Hatchling 拒绝；本次用 uv sync --no-install-project --extra dev 安装依赖后运行源码。
2. backend/uv.lock 落后于 pyproject.toml：锁文件项目版本仍为 0.1.83，并缺少 pypinyin；不能把 uv.lock 当作当前依赖声明的完整镜像。
3. README 声称 Docker 已内置 stock-sdk，但 Dockerfile 和 docs/deployment.md 明确默认 INCLUDE_STOCKSDK=0；实际默认镜像不含该插件依赖。
4. 断板反包策略的描述与实现不一致：实现没有检查“先连板、再断板 1–2 天”，只检查当日封板、量比和涨幅。
5. 连板接力策略的 ENTRY_SIGNALS 元数据写 signal_limit_up，但实际入场条件不要求当日封板，只要求涨幅和 consecutive_limit_ups。
6. 批量指标路径的 high_60d / low_60d 使用 60 日收盘价极值；盘中递推路径使用 high / low 极值，两个路径语义不完全一致。
7. 因子回测请求中的 weight、fees_pct、slippage_bps 会被回传，但计算过程没有使用它们；界面参数不等于已进入算法。
8. AI 策略文件会经过 AST 白名单检查，但最终仍由当前 FastAPI 进程 exec_module 执行；源码注释也明确说明它不是真正沙箱。

## 2. 安装与运行记录

### 2.1 环境与安装

本机检测到：

| 组件 | 实际环境 |
|---|---|
| Windows | PowerShell，工作区 D:\quantall |
| uv | 0.11.7 |
| Node.js | 20.15.0 |
| pnpm | 9.4.0 |
| 浏览器 | Microsoft Edge，Python Playwright headless |
| 后端虚拟环境 | uv 选择 CPython 3.14.4 |

实际执行路径：

    git clone https://github.com/shy3130/tickflow-stock-panel.git prototypes/tickflow

    cd prototypes/tickflow/backend
    uv sync --no-install-project --extra dev

    cd ../frontend
    pnpm install --frozen-lockfile

    cd ../backend/app/plugins/stocksdk
    npm ci

本次没有写入任何 API Key，也没有拉取真实行情。stock-sdk 仅完成本地依赖安装和 ping 自检。

### 2.2 当前启动方式

后端：

    cd D:\quantall\prototypes\tickflow\backend
    uv run --no-sync python -m uvicorn app.main:app --host 127.0.0.1 --port 3018

前端：

    cd D:\quantall\prototypes\tickflow\frontend
    pnpm dev --host 127.0.0.1 --port 3011

访问地址：

| 服务 | 地址 | 运行观察 |
|---|---|---|
| 前端 | http://127.0.0.1:3011 | 页面可渲染 |
| 后端 | http://127.0.0.1:3018 | health 正常 |
| OpenAPI | http://127.0.0.1:3018/docs | 187 条 path、208 个 operation |

健康响应：

    {"status":"ok","version":"0.1.88","mode":"none"}

后端启动观察：

- 激活 2 个基础能力。
- 加载 18 个内置策略。
- stock-sdk 插件 ping 成功并注册。
- 无行情数据时 instruments/enriched 预热会记录空 Parquet 警告，但不阻断启动。
- 内置概念和行业扩展定时任务启动后立即尝试访问 shy313.com；本机代理是 SOCKS，而依赖只安装了 httpx、未安装 socksio，因此拉取失败。核心服务仍保持 ready。

### 2.3 为什么没有直接使用 dev.ps1

dev.ps1 内部执行 uv sync。当前 pyproject 的 README 路径位于 backend 项目目录之外，Hatchling 报错：

    ValueError: Readme path must be within the project directory: ../README.md

因此 dev.ps1 在依赖阶段会退出。本次没有修改上游源码，而是以 no-install-project 安装依赖并直接从 backend 工作目录运行 app 包。若要长期使用，建议上游把 README 复制或链接进 backend，再让 pyproject 指向 backend 内部文件，同时重建 uv.lock。

## 3. 项目组成与职责边界

| 层 | 主要目录 | 实际职责 |
|---|---|---|
| Web/API | backend/app/api | FastAPI 请求校验、REST、SSE、任务入口与响应映射 |
| 业务服务 | backend/app/services | 同步、行情、市场总览、监控、分析、报告、扩展数据 |
| 数据源 | backend/app/data_providers、backend/app/tickflow | TickFlow、自定义 HTTP、插件发现、字段标准化和能力检测 |
| 数据仓库 | backend/app/tickflow/repository.py | Parquet、DuckDB 视图、内存缓存、增量合并 |
| 指标 | backend/app/indicators | 日线与盘中递推指标、信号、关键价位 |
| 策略 | backend/app/strategy | 策略注册、评分、组合、自定义信号、AI 生成 |
| 回测 | backend/app/backtest | 矩阵、撮合、成本、组合、优化、步进、因子检验 |
| 前端 | frontend/src | React 路由、查询缓存、图表、设置和任务 UI |
| 本地数据 | data | 行情、财务、扩展表、缓存和用户配置；被 Git 忽略 |

关键设计约束来自 CONTRIBUTING.md：

- API 与页面不应直接读取某个供应商。
- 数据源先转成统一数据集，再进入仓库和业务层。
- change_pct 在实时入口是小数，例如 0.0366 表示 3.66%。
- 实时入口 turnover_rate 是小数；enriched 中 turnover_rate 是百分数值，例如 5 表示 5%。
- enriched 的 open/high/low/close 是复权价；持久层另存 raw_close/raw_high/raw_low，涨跌停判断使用这些未复权列。当前窄表没有 raw_open。
- 交易日与调度统一采用北京时间。

## 4. 全部数据源与获取路径

### 4.1 TickFlow SDK

源码入口：

- backend/app/tickflow/client.py
- backend/app/tickflow/capabilities.py
- backend/app/data_providers/tickflow_provider.py

固定端点：

| 模式 | URL |
|---|---|
| 无 Key / 免费历史日线 | https://free-api.tickflow.org |
| 有 Key | https://api.tickflow.org |

使用的 SDK 数据能力：

| 数据集 | SDK 调用意图 | 下游 |
|---|---|---|
| 标的维表 | exchanges.get_instruments | 股票、指数、ETF universe 与名称 |
| 日 K | klines.batch，adjust=none | 原始 OHLCV |
| 复权因子 | klines.ex_factors | 前复权处理 |
| 实时行情 | quotes.get_by_universes / quotes.get | 盘中快照、SSE、监控 |
| 财务 | financials 下各表 | metrics、三张表、股本 |
| 分钟 K | 分钟行情能力 | 分钟图和下一分钟成交模拟 |

能力检测不是只读配置，而是按端点探测后生成能力集合，并缓存到 .capabilities.json。档位模型包括 none、Free、Starter、Pro、Expert；真正可用性以探测结果为准。自定义分钟源可以给全局能力集合补上分钟能力。

路由规则：

- 日 K：若用户选择且配置了 custom daily，则走自定义源，否则走 TickFlow。
- 复权因子：可选择 same_as_daily、单独 custom 或 TickFlow。
- 实时：支持 TickFlow 档位模式或自定义全市场源。
- 分钟：优先选择的 custom 源；请求失败时可回退 TickFlow。
- 财务：custom 源可绕过 TickFlow Expert 能力门槛；否则走 TickFlow。
- 指数和 ETF 的部分批量同步仍明确依赖 TickFlow capability，不是所有功能都已完全供应商无关。

### 4.2 stock-sdk 内置插件

源码入口：

- backend/app/plugins/stocksdk/plugin.yaml
- backend/app/plugins/stocksdk/provider.py
- backend/app/plugins/stocksdk/bridge.py
- backend/app/plugins/stocksdk/bridge.mjs

运行方式：

    Python provider
        -> subprocess 调用 Node bridge.mjs
        -> stock-sdk
        -> JSON stdout
        -> Python 标准化 DataFrame

插件声明 daily、adj_factor、minute、realtime 四类数据：

| 数据集 | stock-sdk 调用 | 处理方式 |
|---|---|---|
| 日 K | sdk.kline.cn | 返回未复权 OHLCV |
| 复权因子 | sdk.kline.cn 的 none 与 hfq | 以 close_hfq / close_none 合成因子 |
| 分钟 K | sdk.kline.cnMinute | 转为统一分钟字段 |
| 实时/标的 | sdk.batch.cn | 批量快照与标的列表 |

对已安装 stock-sdk 2.2.2 注入 fetchImpl 并阻断实际联网后，观察到它会构造以下第三方请求：

| 用途 | 主机 |
|---|---|
| 日线/分钟历史 | push2his.eastmoney.com |
| 单标的行情 | qt.gtimg.cn |
| A 股列表 | assets.linkdiary.cn |
| 批量实时行情 | qt.gtimg.cn |

这只是当前包在所测调用路径上的实际 URL，不应外推为 stock-sdk 所有接口的完整来源。

合规边界：

- stock-sdk 自身为 ISC License。
- 它抓取第三方财经站点接口，可能受站点条款和交易所行情版权约束。
- Dockerfile 默认 INCLUDE_STOCKSDK=0，只有显式构建参数才安装依赖。
- 本项目 README 中“镜像已内置 stock-sdk”与当前 Dockerfile 不一致，应以 Dockerfile 和 docs/deployment.md 为准。
- stock-sdk README 将实时数据定位为秒级/分钟级研究数据，不适合高频交易。

### 4.3 自定义 HTTP 数据源

源码入口：

- backend/app/data_providers/custom/config.py
- backend/app/data_providers/custom/provider.py
- backend/app/data_providers/custom/mapper.py
- backend/app/data_providers/custom/loader.py

支持的数据集：

| 数据集 | 必需统一字段 |
|---|---|
| daily | symbol、date、open、high、low、close、volume、amount |
| adj_factor | symbol、trade_date、ex_factor |
| realtime | symbol、last_price、prev_close、open、high、low、volume |
| minute | symbol、datetime、open、high、low、close、volume、amount |
| financial | symbol；其余字段由具体 table 约定 |

YAML 可配置：

- GET 或 POST。
- batch、rpm、timeout，timeout 限制在 0–300 秒。
- response_path 点路径取数组。
- field_map 映射上游字段。
- params、body 与 symbols/start/end/freq 参数名。
- none、bearer、header、query 四类鉴权。
- token 只引用 token_env 环境变量，不需要写进 YAML。
- 变换只接受受控表达式，例如乘除常数、parse_date、parse_datetime；没有 eval。

这类配置可让现有 REST API 直接变成日线、复权、实时、分钟或财务源，不需要改策略代码。

### 4.4 扩展数据：CSV、Excel、JSON 推送和 HTTP 拉取

源码入口：

- backend/app/services/ext_data.py
- backend/app/services/ext_pull.py
- backend/app/api/ext_data.py

扩展数据与行情 provider 是两条不同链：

- 行情 provider 提供核心 OHLCV、因子、实时和财务。
- ext_data 提供可附着到标的的任意维度、标签和时间序列。

接入方式：

| 方式 | 说明 |
|---|---|
| 上传 | CSV、XLSX/XLS；自动处理 UTF-8、GBK 等编码和股票代码归一化 |
| JSON ingest | API 直接写 rows |
| HTTP pull | URL、方法、headers、params、response_path、field_map |
| 定时 pull | 最短 60 秒，默认 1440 分钟 |

存储模式：

| 模式 | 路径 | 语义 |
|---|---|---|
| snapshot | data/ext_data/{id}/part.parquet | 当前快照覆盖写 |
| timeseries | data/ext_data/{id}/timeseries/date=YYYY-MM-DD/part.parquet | 按日期分区 |

系统内置两个扩展预设：

| ID | 数据 | URL |
|---|---|---|
| ext_gn_ths | 同花顺概念映射 | https://shy313.com/api/plugins/market_flow/exports/ths-concepts |
| ext_hy_ths | 同花顺行业映射 | https://shy313.com/api/plugins/market_flow/exports/ths-industries |

启动只创建配置；但是配置默认 enabled，PullScheduler 启动后会立即执行一次，然后按 1440 分钟循环。概念数组用分号连接，行业层级用连字符连接，并生成 symbol/code。

### 4.5 AI 与通知外部服务

AI provider：

- OpenAI-compatible Chat Completions：用户配置 base_url、model、API Key。
- 本地 Codex CLI：单次临时目录、隔离 CODEX_HOME、只复制登录状态，命令固定为 codex，sandbox=read-only，approval=never。
- 对不支持 temperature 的兼容端点，在命中对应 400 后去掉 temperature 重试一次。

通知出口：

- 本机系统通知。
- 飞书 Webhook，可带签名 secret。
- 企业微信 Webhook。
- 企业微信智能机器人长连接。

这些不是行情源，但会把监控和复盘结果发送到外部系统；配置时应把它们纳入隐私与密钥边界。

### 4.6 截图 OCR 与新闻输入

自选截图导入是另一类本地输入：

    PNG/JPEG bytes
        -> Pillow 预处理
        -> 本机 Tesseract OCR
        -> 正则提取六位代码
        -> instruments 股票/ETF 维表校验
        -> 返回候选，不自动写入自选

它不调用云端 OCR。正则会修复类似“5881 70”的 OCR 空格拆分，按出现顺序去重；只有能在本地 instruments 映射为 symbol 的代码才标为 matched。

市场复盘服务可以接收调用方预先提供的最多 8 条 news，并放入 LLM 提示词，但当前仓库没有已接通的新闻搜索或公告爬取器。源码注释把 news_search 留在未来 P3，因此不能把“AI 复盘”理解成系统会自行获取新闻。

自定义 HTTP 和扩展数据的测试、detect-url、手动拉取都会由后端访问用户提供的 URL，并允许跟随重定向。它是有意提供的服务器侧外连能力；若把面板暴露给不可信用户，必须先启用访问认证并限制谁能操作数据源设置，否则会形成内网 URL 探测面。

## 5. 数据落地、查询和缓存

### 5.1 目录

DataStore 会创建：

- kline_daily、kline_daily_enriched
- kline_index_daily、kline_index_enriched
- kline_etf_daily、kline_etf_enriched
- kline_minute、kline_etf_minute
- adj_factor、adj_factor_etf
- instruments、instruments_index、instruments_etf、instruments_ext
- financials/metrics、income、balance_sheet、cash_flow、shares
- ext_data、ai_cache、user_data

行情通常按日期分区写 Parquet。写入采用临时文件加 replace，并在 symbol/date 主键上做 merge-upsert，降低中断造成半文件的概率。

### 5.2 DuckDB 与 Polars

DuckDB 不承担主存储，而是给 Parquet 建 read_parquet 视图：

    Parquet partitions
        -> DuckDB union_by_name views
        -> KlineRepository
        -> Polars DataFrame
        -> 指标、筛选、回测

union_by_name 让历史 Parquet 缺新字段时仍可读取。策略和指标主体使用 Polars；回测矩阵转 NumPy/Numba。旧 BacktestService 边界仍保留 pandas/vectorbt 兼容路径，但当前策略回测主路径是自研矩阵引擎。

### 5.3 缓存层

实际存在的缓存包括：

- 最新 enriched 股票约 5,500 行。
- 完整 enriched 历史约 100 万行。
- 股票、指数、ETF instruments 缓存。
- 盘中聚合缓存。
- 策略结果缓存。
- 回测 MarketDataMatrix 内存/磁盘 memmap 缓存，默认上限 512 MB。
- 文件 mtime 与 generation ID。
- SSE 推送后的前端 TanStack Query 缓存。

服务启动时同步加载轻量维表，把 enriched 全历史的指标重算放进 daemon 线程；ETF 和指数 enriched 采用懒加载。

## 6. 盘后主数据流

daily_pipeline 的实际阶段：

    instruments
        -> resolve universe
        -> daily raw K
        -> adjustment factors
        -> halt-day filter
        -> preserve raw close/high/low
        -> forward-adjusted OHLC
        -> indicators + signals + limits + turnover
        -> narrow enriched Parquet
        -> optional index / ETF
        -> optional minute K
        -> optional market regime
        -> refresh DuckDB views and caches

关键行为：

- 有批量能力时 universe 使用 CN_Equity_A；否则退化为 demo、自选和已有标的，并排除指数。
- 首次日 K 默认拉约一年，之后补缺口。
- 停牌过滤条件是 open=0 且 high=0；因为有的数据源会把停牌 close 填成前收。
- 复权因子缺失时有短窗口兜底；前复权后的 OHLC 用于技术指标，raw_* 用于涨跌停。
- 首次或向历史左侧扩展时全量算 enriched；正常新增日期只重算增量和受影响标的。
- 源码注释仍写“14 列”，但当前 ENRICHED_STORAGE_COLS 实际有 15 列：symbol、date、复权 OHLC、volume、amount、raw_close/raw_high/raw_low、turnover_rate、连续涨跌停数和 quote_ts。完整指标在读取历史时重算。
- 管道任何阶段异常都会把 job 标为 failed，但此前成功阶段可能已经写盘，因此 failed 不等于零副作用。
- 默认工作日调度：标的维表 09:10、盘口定版 15:02、盘后管道 15:30、能力重探每小时。
- regime 默认关闭；财务默认只手动同步。

## 7. 指标算法

主实现：backend/app/indicators/pipeline.py。

| 指标 | 源码公式 |
|---|---|
| MA | close 的 rolling_mean，窗口 5/10/20/30/60 |
| EMA | alpha=2/(N+1)，adjust=False，窗口 5/10/20/30/60 |
| MACD DIF | EMA12 - EMA26 |
| MACD DEA | DIF 的 EMA9 |
| MACD histogram | 2 × (DIF - DEA) |
| Bollinger | MA20 ± 2 × rolling_std(close, 20) |
| KDJ RSV | 100 × (close - LLV9) / (HHV9 - LLV9) |
| K、D、J | K=RSV 的 EWM(alpha=1/3)，D=K 的同口径 EWM，J=3K-2D |
| True Range | max(high-low, abs(high-prev_close), abs(low-prev_close)) |
| ATR14 | TR 的 EWM(alpha=1/14) |
| 量比 | 当日 volume / 前 5 日平均 volume，不含当天 |
| 盘中量比 | 当前累计 volume × 240/已交易分钟 ÷ 前 5 日平均量 |
| 动量 | close / close.shift(N) - 1，N=5/10/20/30/60 |
| 涨跌幅 | close / prev_close - 1 |
| 振幅 | (high-low) / prev_close |
| 年化波动 | std(日收益,20) × sqrt(252) |
| RSI | Wilder 风格平均涨跌，alpha=1/N，N=6/14/24 |
| 换手率 | volume(手) × 10000 / float_shares(股)，结果是百分数值 |

原子信号包括：

- MA5/MA20、MA20/MA60 金叉与死叉。
- close 上穿/下穿 MA20。
- MACD DIF/DEA 金叉与死叉。
- 60 日新高/新低。
- Boll 上轨突破、下轨跌破。
- 量比大于等于 2 的放量。
- 涨停、跌停、炸板、跌停翘板和连续涨跌停。
- 用户自定义信号。

历史与实时计算并非完全同一实现：

- 历史批量直接 rolling/EWM。
- 实时路径保留 EMA、MACD、KDJ、ATR、RSI、部分和、历史 close 等状态递推。
- 历史 high_60d/low_60d 用 close 的极值；实时路径将历史状态与当日 high/low 比较。这是明确的语义差异，可能让盘中“新高/新低”与盘后重算不一致。

## 8. 复权、股本与涨跌停

### 8.1 股本的时点处理

财务 shares 表至少含 symbol、period_end、float_shares；有 announce_date 时优先把它作为可用日期，否则使用 period_end。历史计算通过 join_asof 只使用交易日当时已经可获得的最近股本，避免直接把当前股本回填到过去。当天则优先使用 instruments 当前股本。

### 8.2 涨跌停规则

backend/app/price_limits.py 在指标和回测间共享：

| 板块 | 比例 |
|---|---|
| 北交所 .BJ | 30% |
| 创业板 300/301、科创板 688/689 | 20% |
| 其他主板 | 10% |
| 主板 ST，2026-07-06 之前 | 5% |
| 主板 ST，2026-07-06 起 | 10% |

涨跌停价采用整数分和 half-up 规则，避免二进制浮点直接比较。若 instruments 中有与交易日匹配的权威涨跌停价则优先使用，否则按昨收和比例推导。

派生状态：

- signal_limit_up / signal_limit_down：收盘封住。
- limit_up_locked / limit_down_locked：一字或单价锁死。
- signal_broken_limit_up：最高触及涨停，但收盘未封住。
- signal_limit_down_recovery：最低触及跌停、收盘打开且收阳。
- consecutive_limit_ups / consecutive_limit_downs：按连续分组累计。

## 9. 18 个内置策略

所有当前内置策略都声明 EXECUTION_BACKEND = matrix_native。执行顺序统一为基础过滤、策略布尔掩码、候选集横截面评分、排序和 limit。

### 9.1 趋势、突破与均线

| ID | 入场核心条件 | 退出 | 默认风控 |
|---|---|---|---|
| trend_breakout | close>MA60；close>=60 日收盘新高；量比>=2；价格 5–200；市值>=20 亿；成交额>=1 亿；排除 ST 和上市不足 60 日 | 跌破 MA20 | 止损 -8%，最长 20 日 |
| ma_golden_cross | MA5 上穿 MA20；量比>=1.2；close>MA60 | MA5 下穿 MA20 | -6%，15 日 |
| bullish_alignment | MA5>MA10>MA20>MA60；20 日动量>0 | MA5 死叉或跌破 MA20 | -6%，20 日 |
| pullback_ma20_bounce | close 距 MA20 不超过 ±2%；MA5>MA20>MA60；当日上涨 | 跌破 MA20或 MA5 死叉 | -5%，15 日 |
| pullback_to_support | close 距 MA20 不超过 ±2%；量比<0.8；close>MA60；20 日动量>0 | 跌破 MA20 | -5%，20 日 |
| low_volatility_leader | 20 日动量>0；年化波动<0.30；close>MA20 | 跌破 MA20 | -5%，30 日 |

### 9.2 量价、动量与振荡

| ID | 入场核心条件 | 退出 | 默认风控 |
|---|---|---|---|
| volume_price_surge | close 上穿 MA20；量比>=2；收阳 | 跌破 MA20 | -6%，15 日 |
| high_turnover_surge | 换手率>5；涨幅>3% | 跌破 MA20 | -5%，10 日 |
| strong_open | open>prev_close×1.03；close>open；涨幅>3% | 跌破 MA20 | -5%，10 日 |
| macd_golden | DIF 上穿 DEA；量比>=1.5 | DIF 下穿 DEA | -7%，20 日 |
| boll_breakout | close>Boll 上轨；量比>=1.5 | close<Boll 下轨 | -6%，15 日 |
| n_day_low_reversal | close<=60 日收盘低点；收阳；量比>=1.5 | 跌破 MA20 | -6%，15 日 |
| oversold_bounce | RSI14<30；收阳；量比>=1.2 | 跌破 MA20 | -5%，15 日 |
| oversold_reversal | RSI14<30；涨幅>1%；close>MA5 | 跌破 MA20 | -5%，15 日 |

### 9.3 涨停与连板

| ID | 入场核心条件 | 退出 | 默认风控 |
|---|---|---|---|
| consecutive_limit_ups | 当日 locked 涨停；连续板数>=2 | 无显式策略退出 | -5%，5 日 |
| near_limit_up | 涨幅>7%，且距对应涨停幅度不超过 3 个百分点 | 跌破 MA20 | -5%，5 日 |
| limit_up_momentum | 涨幅>5%；consecutive_limit_ups>=1 | 无显式策略退出 | -5%，5 日 |
| broken_board_recovery | 可选要求当日 locked 涨停；量比>=1.5；涨幅>3% | 跌破 MA20 | -6%，10 日 |

所有策略当前 TAKE_PROFIT 均为空。

### 9.4 评分

每个评分字段只在当日候选集合内做 min-max：

    normalized = (x - candidate_min) / (candidate_max - candidate_min)
    score = 100 × sum(normalized_feature × normalized_weight)

行为细节：

- 无效或缺失字段被排除，剩余权重重新归一化。
- 某字段在候选中为常数时统一赋 0.5。
- 分数只表示同一批候选内的相对排名，不能跨日期、跨策略直接比较。
- 回测中同样按每个交易日横截面归一化。
- 所有内置权重均为正。oversold_bounce 与 oversold_reversal 对 RSI 也给正权重，因此在 RSI<30 的候选内，RSI 更高者反而得分更高；这不等同于“越超卖分越高”。

### 9.5 两个重要描述偏差

断板反包：

- META description 写“连板>=2 后断板 1–2 天，出现放量反包”。
- compute_signals 没有引用历史断板或前序连板，只看当日 limit_up_locked、vol_ratio_5d 与 change_pct。
- 所以当前算法更接近“当日涨停且放量”，不是严格的断板反包。

连板接力：

- ENTRY_SIGNALS 写 signal_limit_up。
- 实际 entry 只检查 change_pct 和 consecutive_limit_ups，没有与当日 limit_up_locked 做 AND。
- 若 consecutive_limit_ups 的输入来自历史状态，元数据展示和真实入场掩码可能不一致。

## 10. 自定义信号、组合策略与 AI 策略

### 10.1 自定义信号

定义存放在 data/user_data/custom_signals/*.json。

每个信号：

- ID 只能是 1–40 位小写字母、数字和下划线。
- 最多 8 条条件。
- 条件只允许白名单数值字段。
- 运算符仅有 >、>=、<、<=、==、!=。
- 右值只能是数值或另一个白名单字段。
- 支持左右字段最多回看 60 个交易日。
- 多条件首版只支持 AND。
- 编译为 Polars Expr，列名使用 csg_ 前缀。
- 盘中快照不支持 shift；含回看天数的整个信号会被跳过。

同一信号列注入 enriched 后可被选股、回测和监控共同使用。

### 10.2 组合策略

组合最多包含受限数量的叶子策略，不允许组合再嵌套组合；父子 asset_types 与 timeframes 必须兼容。

入口：

- union：任一子策略命中。
- intersect：命中数达到 min_confirm；min_confirm<=0 时要求全部命中。

组合分数：

- 每个子策略先把内部 score 转成候选 rank，最高接近 1、最低接近 0。
- 只在实际命中的子策略间按配置权重合成。
- 只有一个候选时该子策略 rank 为 0.5。

退出：

- 每个子策略的退出只投影到该子策略产生的 entry/max_hold 区间。
- 这样一个子策略不会无条件关闭另一个子策略创建的持仓。

### 10.3 AI 生成策略

流程：

    用户自然语言
        -> strategy-guide-compact.md
        -> OpenAI-compatible 或 Codex CLI
        -> 提取 Python fenced block
        -> ast.parse
        -> META literal_eval 与结构校验
        -> import/call/dunder 白名单检查
        -> 保存用户策略
        -> StrategyEngine reload

安全措施：

- 允许 import 的根模块主要是 polars、numpy、app.backtest.matrix、datetime。
- 阻止 open、exec、eval、compile、__import__、globals、locals、getattr 等调用。
- 阻止 __globals__、__builtins__、__class__、__subclasses__ 等 dunder 遍历。
- META 必须是字面量字典；评分权重必须非负、有限且总和为 1。
- reload 前和加载时都校验。

剩余风险：

- AST 规则是模式拦截，不是进程隔离。
- StrategyEngine 最终通过 importlib 的 exec_module 在 Web 服务进程执行策略文件。
- 项目注释明确把“受限子进程执行”列为后续 P0。因此只应运行可信或人工复核后的策略代码。

## 11. 回测系统

### 11.1 矩阵和信号

主路径把时间 × 标的展开为 NumPy 矩阵：

- OHLC、volume、amount、valid、suspended。
- 指标按策略依赖裁剪，不为每个策略重算全部字段。
- 涨跌停比例和价格矩阵按日期与股票名称生成。
- 支持内存缓存、磁盘 memmap、计算结果缓存和预热。
- 常规 warmup 至少覆盖约 120 个日历日；策略可声明更长所需 bar。

### 11.2 成交时序

默认策略回测采用严格 open_t+1：

- t 日信号只使用 t 日已完成数据。
- 最早在 t+1 开盘成交。
- 可选 close_t。
- 少量 MA 破位类卖出信号支持 signal_next_minute：当前分钟确认，下一分钟开盘模拟成交。

限制：

- A 股 T+1：当日买入仓位不能当日卖出。
- 同日退出后不立即重新入场。
- 一字涨停阻止买入，一字跌停阻止卖出。
- 停牌或非法价格阻止成交。
- 未成交退出进入 pending，后续交易日继续尝试。

### 11.3 成本与风控

默认兼容值：

- 买卖佣金各 0.02%。
- 印花税只在卖出侧，未设置时为 0。
- 滑点 5 bps，买卖两侧都计。
- 初始资金 1,000,000。
- 最大持仓数 10。
- 最大总暴露 100%。
- 100 股整数手。
- 权重支持 equal 或 score。

止损：

- 次日开盘已经跳过止损线时按开盘成交。
- 盘中 low 首次触发时按止损线成交。
- trailing stop 跟随持仓后的最高价。
- take profit 同样区分跳空开盘和盘中 high 触发。

### 11.4 两种策略统计模式

- position：真实组合资金曲线，受现金、仓位数、权重和 T+1 限制。
- full：把每个候选视作独立 100 股交易来统计，不是一个可直接执行的组合净值。

两者回答的问题不同，不能把 full 模式的累计交易收益当作资金组合收益。

### 11.5 指标

引擎输出：

- 总收益、年化收益。
- 最大回撤。
- 基于日收益的 Sharpe、Sortino、Calmar。
- 胜率、profit factor。
- 持仓天数、单笔收益和交易明细。
- 确定性 bootstrap Monte Carlo 最大回撤 p50/p95，随机种子 42，最多 1,000 次，并有 200 万单元保护。

### 11.6 参数优化

- 对配置的参数列表做笛卡尔积穷举。
- 最多 2,000 个组合。
- worker 内串行运行，共享只读市场矩阵。
- 支持多个 objective，默认 sortino。
- 搜索完成后对最优参数再跑一次完整结果。

它不是贝叶斯优化、遗传算法或在线学习。

### 11.7 Walk-forward

- 以固定日历天长度划分 train/test/step。
- test 从 train_end+1 开始，避免同一天重叠。
- 样本内强制 position 模式选择参数。
- 只聚合有效 fold。
- 样本外收益用复利连接。
- 输出样本内/外退化和正收益一致性；退化方向会根据 objective 的好坏方向处理。

这里按日历日而不是固定交易日切窗，节假日会改变每个 fold 的实际 bar 数。

### 11.8 因子回测

- 对每个截面计算 factor rank 与下一期收益 rank 的相关系数，即 Rank IC。
- forward return 支持日、周、月。
- 按因子分成 N 个分位组，各组等权平均。
- 多空组合是 top 组与 bottom 组各 50%。

确认的实现缺口：

- FactorBacktestConfig 有 weight、fees_pct、slippage_bps。
- 这三个字段会进入响应 config。
- 计算函数没有引用它们。
- 因此当前因子组收益与多空收益没有真正扣除这些费用，也没有实现 factor_weight。

## 12. 市场状态、情绪、轮动与关键价位

### 12.1 Regime 市场状态

regime_builder 计算四个分量：

- profit，权重 0.35。
- speculation，权重 0.25。
- resilience，权重 0.20。
- trend，权重 0.20。

每个分量按源码中硬编码的“2022–2026 p15/p85”阈值线性映射并截断，合成为 0–100：

| 分数 | 状态 |
|---|---|
| >=70 | strong |
| >=55 | lean_strong |
| >=45 | range |
| >=30 | lean_weak |
| <30 | weak |

回测按 T-1 的 regime mask 控制当日入场，避免把当日收盘才能知道的 regime 用于当日开盘。

阈值来源只有源码注释，没有看到生成阈值所用原始样本、脚本或分位数审计产物，因此“2022–2026 p15/p85”只能视作作者声明，不是本次独立复算结论。

### 12.2 市场总览与情绪雷达

market_overview_builder 汇总：

- 指数表现。
- 上涨/下跌/平盘家数。
- 成交额。
- 涨停、跌停、炸板、连板梯队。
- 趋势与活跃度。
- 概念、行业平均涨跌和领涨/落后成分。

六维雷达为 index、profit、money、speculation、resilience、mainline 等权维度，最终情绪仍用 70/55/45/30 阈值分级。

若有五档盘口，depth_service 可以把表面封板但 sealed_vol 不成立的“假封板”从统计中剔除。

### 12.3 RPS 轮动

这里的 RPS 不是常见的“某证券 N 日收益相对全市场百分位”。实际算法：

1. 每日对概念或行业成员的 change_pct 求平均。
2. 对所有板块的当日平均涨幅做横截面排名。
3. 保存最近 7–30 天排名矩阵。

预计算标签：

| 标签 | 规则 |
|---|---|
| persistent | 最近 3 日平均排名<=10 且最新<=10 |
| rising | 最早排名>30、最新<=20、名次提升>=20 |
| fading | 最早<=10、最新>30、名次下降>=20 |
| institutional | 排名标准差<=5 且平均排名<=20 |
| hot-money | 排名标准差>=20 |

“机构”和“游资”只是排名稳定性启发式标签，不是持仓、席位或资金流的直接证据。

### 12.4 关键价位

源码 LEVEL_TYPES 实际有 11 类，README 的“9 类”已经过时：

| 类型 | 算法 |
|---|---|
| chip / POC | 40 个价格桶；旧筹码按 1-turnover 衰减；当日量在 high-low 内均匀分布；取 POC 和两个高于均值的桶 |
| pivot | 最近一根 K 的标准 P、R1–R3、S1–S3 |
| extremes | 60/250 日高低点，加 ±5 bar 局部 swing；1% 内聚类，最近上下各 2 |
| Boll | MA20 ± 2σ |
| Keltner 短 | MA20 ± 2ATR |
| Keltner 中 | MA60 ± 2.5ATR |
| Keltner 长 | MA120 ± 3ATR |
| ATR | 当前 close ± 1.5ATR / 2ATR |
| gaps | 120 日内未回补缺口 |
| Fibonacci | 120 日 swing 的 0.236/0.382/0.5/0.618/0.786，按趋势方向映射 |
| round | 当前价 ±10% 内圆整数位，最多 8 个 |

筹码分布把成交量假设为在当日高低价间均匀分布，是近似模型，不是交易所逐笔真实筹码。

## 13. 实时行情与监控

### 13.1 实时数据流

    provider realtime snapshot
        -> normalize decimal fields
        -> QuoteService in-memory cache
        -> merge raw daily candle
        -> compute_enriched_today recursive update
        -> refresh latest caches
        -> evaluate monitor rules
        -> SSE quotes_updated / strategy_alert
        -> TanStack Query invalidation

轮询模式：

- none：无 Key，不启动实时。
- Free：主要覆盖自选，受数量限制。
- paid/custom full_market：全市场模式。

交易阶段使用北京时间，覆盖盘前、上午连续竞价、午间 final/pre-afternoon、下午连续竞价和收盘 final。告警只在连续竞价阶段触发，避免集合竞价噪声。

### 13.2 监控规则

支持：

- strategy：策略结果或买卖信号变化。
- signal：原子或自定义信号。
- price：价格、涨跌幅等字段条件。
- market：市场异动。
- ladder：连板梯队和封单。
- sector：概念/行业聚合。

规则最多 8 条条件，支持 AND/OR；字段和信号走白名单。scope 可为指定 symbols 或 all。通用 sector scope 当前 fail-closed，板块监控应使用专门的 sector rule type。

状态机细节：

- 第一次策略评估只建立 baseline，不报警。
- 后续产生 buy/sell、pool_entry/pool_exit。
- 同一批超过 5 条时合并。
- cooldown key 包括 rule、symbol、event，默认 3,600 秒。
- 告警追加到 data/user_data/alerts.jsonl，保留 7 天且最多 5,000 条。

盘中分钟信号：

- VWAP = 累计 amount / (累计 volume × 100)，检测价格上穿/下穿。
- 零轴使用昨收，检测价格跨越昨收。
- 只在出现新的完整分钟 bar 时判定。

板块异动：

- 对成员的 decimal return 求平均。
- 至少 5 个有效成员。
- 覆盖率至少 80%。
- 支持 1/3/5/10/15 分钟窗口。
- 通过阈值边缘 crossing 和 tolerance 防止每次轮询重复报警。

封单：

- 需要 depth sealed_vol>0 且满足阈值。
- 封单金额按 lots × 100 × close。

## 14. AI 分析的实际边界

### 14.1 个股技术分析

stock_analyzer 的确定性部分只做：

- 加载 K 线尾部。
- 加载轻量财务上下文。
- 计算上一节的关键价位。
- 构造提示词并让 LLM 输出 Markdown。

它不是一个有固定公式的目标价或估值模型。系统提示明确禁止买卖、仓位和操作建议，并要求引用输入数值。

### 14.2 财务分析

financial_analyzer：

- 读取 metrics、income、balance_sheet、cash_flow、shares。
- 生成简单摘要。
- 把数据交给 LLM 做财务质量报告。

没有看到 DCF、可比公司估值、盈利预测或目标价格的确定性实现。

### 14.3 市场复盘与轮动分析

- 市场复盘的数据与 /api/overview/market 同源，避免看板和提示词口径分叉。
- 轮动分析先运行确定性排名标签，再把标签和市场背景交给 LLM。
- 用户 focus 会经过敏感交易措辞 blocklist；命中后整段 focus 被丢弃。
- 系统提示持续要求只做客观描述，不给交易指令。

这些限制能降低直接建议输出，但不能证明任何第三方模型一定完全遵守提示词。

## 15. API 与前端数据流

### 15.1 后端 API

运行时 OpenAPI：

- 187 个 path。
- 208 个 GET/POST/PUT/DELETE operation。

主要 tag：

| Tag | Operation 数 |
|---|---:|
| settings | 54 |
| strategies | 18 |
| ext-data | 17 |
| kline | 15 |
| backtest | 11 |
| financials | 11 |
| screener | 9 |
| watchlist | 9 |
| monitor-rules | 7 |
| index | 6 |
| regime | 5 |
| stock-analysis | 5 |
| auth | 5 |

REST 承担快照和任务启动；SSE/流式响应承担：

- /api/intraday/stream 行情与监控事件。
- 参数优化和 walk-forward 进度。
- 个股、财务、市场复盘和轮动的 AI 文本流。
- AI 策略生成流。

### 15.2 前端

前端路由覆盖看板、自选、策略、回测、财务、数据、监控、连板梯队、指数、市场状态、个股/概念/行业分析、复盘和设置。

数据层：

- frontend/src/lib/api.ts 是统一 fetch 客户端。
- TanStack Query 默认 staleTime 5 秒，窗口重新聚焦不自动 refetch。
- 401 或未初始化密码由全局 QueryCache/Mutation 拦截跳转登录。
- useQuoteStream 只建立一个全局 EventSource。
- quotes_updated 按用户页面设置精确 invalidation。
- 策略结果、告警和复盘进度使用独立 SSE 事件。
- 开发时 Vite 把 /api 代理到 3018；生产时 FastAPI 同源托管 dist。
- 页面使用 lazy import 减少首屏加载 ECharts、lightweight-charts 和 framer-motion。

### 15.3 浏览器实测

用 standalone Python Playwright 启动 Microsoft Edge headless，并阻断 localhost 之外的浏览器请求：

| 路径 | 断言 |
|---|---|
| / | 标题“市场看板” |
| /screener | 标题“策略” |
| /backtest | 标题“回测工作台” |
| /settings?tab=data-sources | 标题“设置” |

结果：

- 首次引导可完成，未填任何 Key。
- 四个页面均正确渲染暗色界面。
- 页面 API 请求正常返回，没有 pageerror。
- 控制台只有 React Router future flag 警告。
- 外部字体被测试脚本主动阻断；导航时 SSE abort 属于页面切换行为。
- 无本地行情时策略页显示 18 个策略但 0 个结果；回测页能列出 18 个策略。

## 16. 可复现问题、风险与未知

### 16.1 已确认问题

| 严重度 | 问题 | 影响 |
|---|---|---|
| 高 | 标准 uv sync 因 README 越界失败 | 新用户无法按文档完成源码安装 |
| 高 | uv.lock 与 pyproject 版本/依赖不一致 | frozen 构建可能缺 pypinyin；可复现性下降 |
| 高 | AI/用户 Python 策略非进程沙箱 | 恶意或被污染代码可能接触服务进程权限 |
| 中 | 断板反包描述与算法不符 | 用户误解策略经济含义，回测名不副实 |
| 中 | 连板接力展示信号与掩码不完全一致 | 监控、解释和实际候选可能产生认知偏差 |
| 中 | high_60d/low_60d 历史与实时口径不同 | 盘中与盘后信号可能翻转 |
| 中 | 因子回测费用/权重参数未生效 | UI 给出已配置的错觉，收益可能偏高 |
| 中 | README 与 Dockerfile 的 stock-sdk 默认值冲突 | 部署后插件可用性与合规预期错误 |
| 中 | SOCKS 环境缺 socksio | 内置扩展拉取失败，但应用仍启动 |
| 中 | 自定义 URL 会触发后端外连且 detect-url 可跟随重定向 | 公网或多人部署必须用认证限制设置权限，防止被当作内网探测器 |
| 低 | frontend 声明 pnpm lint，但 devDependencies 没有 eslint | 前端 lint 命令无法执行 |
| 低 | 全仓 Ruff 当前有 1,257 项历史告警 | 仓库不满足自身全量 Ruff 配置，不能把 lint 表述为通过 |
| 低 | enriched 源码注释称 14 列，实际列表为 15 列 | 文档和 schema 认知容易漂移 |
| 低 | 无数据启动会记录 instruments 空 Parquet 警告 | 日志噪声，不影响 ready |

### 16.2 方法论风险

- 18 个策略都是规则与横截面排名，不是机器学习预测模型。
- 策略 score 是候选集内相对分，不是收益概率。
- 多数策略没有 take-profit，退出主要靠 MA、MACD、止损或最长持有期。
- market regime 的阈值样本与校准脚本未随仓库提供。
- RPS 的“机构/游资”是排名稳定性标签，不是资金身份识别。
- 筹码分布使用区间均匀成交假设。
- 回测虽处理 T+1、费用、滑点和涨跌停，但仍没有盘口冲击、排队成交、容量、真实撮合延迟和数据修订。
- 本次没有真实行情与财务授权，未验证供应商数据完整性、字段漂移、限频和大规模性能。
- 没有用真实样本独立复算任何策略收益，因此本报告不对 alpha、胜率或未来表现背书。

### 16.3 未知

- TickFlow 私有服务端如何生产、清洗和授权底层行情。
- shy313.com 概念/行业接口上游抓取、更新时间和授权链。
- 硬编码 regime 阈值的原始训练/校准样本。
- stock-sdk 第三方接口长期稳定性与正式授权。
- 在全 A 股多年数据上的真实峰值内存、回测耗时和告警延迟。

## 17. 验证记录

已执行的检查包括：

| 检查 | 命令/方法 | 结果口径 |
|---|---|---|
| 上游固定 | git ls-remote、git log -1 | main=9b9538a... |
| 后端依赖 | uv sync --no-install-project --extra dev | 依赖安装成功；记录标准安装缺陷 |
| 前端依赖 | pnpm install --frozen-lockfile | 成功 |
| stock-sdk | npm ci + 插件 ping | 插件可注册 |
| 后端启动 | uvicorn 127.0.0.1:3018 | ready，18 strategies |
| 前端启动 | Vite 127.0.0.1:3011 | ready |
| API | health、OpenAPI | health ok；187 paths / 208 ops |
| UI | Python Playwright + Edge | 4 个核心页面断言通过并截图 |
| 数据源反查 | stock-sdk 注入 fetchImpl、阻断联网 | 捕获实际构造 URL，不拉真实数据 |
| 源码审计 | provider 到前端逐层追踪 | 形成本文 |
| 后端全量测试 | 清除当前进程代理变量后，uv run --no-sync python -m pytest -q | 589 passed，15 warnings，19.47s |
| 代理环境复现 | 保留本机 ALL_PROXY 后执行同一测试 | 580 passed、9 failed；失败均为缺 socksio |
| 后端 lint | uv run --no-sync ruff check app tests | 未通过：1,257 个上游存量告警 |
| 前端构建 | pnpm build | 通过；2,690 modules，只有大 chunk 警告 |
| 前端 lint | pnpm lint | 未运行成功：package.json 有脚本，但项目未安装 eslint |
| Markdown | git -c core.autocrlf=false diff --no-index --check -- NUL PROJECT_ANALYSIS.md | 通过 |

截图位于本机临时目录 %LOCALAPPDATA%\Temp\tickflow-ui-audit-final，不属于项目源码。最终测试结果以本次终端实际输出为准，不以仓库 README 的历史声明代替。

## 18. 关键源码索引

| 主题 | 文件 |
|---|---|
| 应用装配 | backend/app/main.py |
| TickFlow 客户端与能力 | backend/app/tickflow/client.py、capabilities.py |
| Provider 契约 | backend/app/data_providers/base.py、schemas.py、registry.py |
| 自定义 HTTP | backend/app/data_providers/custom |
| stock-sdk | backend/app/plugins/stocksdk |
| 盘后管道 | backend/app/jobs/daily_pipeline.py |
| 仓库与缓存 | backend/app/tickflow/repository.py |
| 指标与信号 | backend/app/indicators/pipeline.py |
| 涨跌停 | backend/app/price_limits.py |
| 历史股本 | backend/app/share_capital.py |
| 策略引擎 | backend/app/strategy/engine.py |
| 评分 | backend/app/strategy/scoring.py |
| 组合策略 | backend/app/strategy/composite.py |
| 自定义信号 | backend/app/strategy/custom_signals.py |
| 18 个策略 | backend/app/strategy/builtin |
| 回测矩阵与撮合 | backend/app/backtest/matrix.py、engine.py、strategy.py |
| 参数优化与步进 | backend/app/backtest/optimizer.py、walkforward.py |
| 因子回测 | backend/app/backtest/factor.py |
| 市场状态 | backend/app/services/regime_builder.py |
| 市场总览 | backend/app/services/market_overview_builder.py |
| 轮动 | backend/app/services/rps_rotation.py、concept_rotation_analyzer.py |
| 关键价位 | backend/app/indicators/levels.py |
| 实时行情 | backend/app/services/quote_service.py |
| 监控 | backend/app/strategy/monitor.py、monitor_rules.py、intraday_signals.py |
| AI provider | backend/app/services/ai_provider.py |
| 个股/财务/复盘 AI | backend/app/services/stock_analyzer.py、financial_analyzer.py、market_recap.py |
| API 汇总 | backend/app/api |
| 前端路由 | frontend/src/router.tsx |
| 前端 API/SSE | frontend/src/lib/api.ts、useQuoteStream.ts |

## 19. 最终判断

这个项目的工程主线是清楚的：统一数据契约、Parquet 本地化、Polars/NumPy 矩阵计算、显式 T+1 撮合、REST/SSE 与可插拔数据源。它已经超过“演示面板”的复杂度，但仍是研究工具，而非经过实盘审计的交易系统。

如果用于后续二次开发，优先顺序应是：

1. 先修复 pyproject/uv.lock，让标准安装和 frozen 构建可复现。
2. 给历史与实时 high_60d/low_60d 建立唯一口径测试。
3. 修正断板反包、连板接力的实现或名称/描述。
4. 要么让因子回测真正使用费用与权重，要么从 UI 删除无效参数。
5. 把用户 Python 策略移入受限子进程。
6. 统一 README、deployment 和 Dockerfile 的 stock-sdk 默认行为。
7. 在有授权数据的隔离环境做数据完整性、样本外和容量验证，再讨论策略有效性。
