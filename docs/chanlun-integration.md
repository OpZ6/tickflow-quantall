# 原生缠论集成

TickFlow 内置缠论结构分析（包含处理 / 分型 / 笔 / 线段 / 中枢 / 买卖点），算法移植自
`openclarr-chanlun` 原型，直接运行在 TickFlow 后端，无需任何外部服务或 iframe。

## 架构

- **后端** `backend/app/chanlun/`：merge_klines、fractal、bi（czsc 引擎）、segment、
  zhongshu、macd、bsp 七层流水线；`pipeline.analyze(candles)` 一次输出全部图层。
- **API** `POST /api/chanlun/analyze`：body 为 `{"candles": [{time, open, high, low, close, volume}, ...]}`，
  返回 `{merged_klines, fenxing, bi, segments, zhongshu, macd, bsp}`。
- **前端渲染**：ECharts 原生能力——笔/线段用 custom series，中枢用 markArea 半透明矩形，
  买卖点用 markPoint 三角标记。入口两处：
  - 个股分析页「缠论」视图（`ChanlunKlineWorkbench`）；
  - 行情浏览日 K 的「缠论」开关按钮（`StockDailyKChart`，开启时按需请求）。

## 扩展技术指标

60+ 指标公式移植于 openclarr-chanlun 前端，纯前端计算：

- `frontend/src/lib/indicator-formulas.ts`：全部公式（SMA/EMA/BOLL/BBI/SAR/ZIGZAG/
  TEMA/DEMA/HMA/WMA/VWMA/VWAP/Supertrend/Donchian/Keltner/Ichimoku/Alligator/LinReg/KDJCh/WRCh
  主图叠加 + KDJ/RSI/WR/CCI/BIAS/OBV/VR/ATR/DMI/MTM/ROC/MFI/CMF/CMO/TRIX/TSI/
  Stoch/StochRSI/PPO/DMA/UO/Vortex/PSY/Chop/AO/Aroon/PVT/DPO/ForceIndex/EMV/ADL/
  ChaikinOsc/ElderRay/TTMSqueeze/STC/CR/BRAR 副图）。
- `frontend/src/lib/indicator-params.ts`：各指标可调参数与默认值（localStorage 持久化）。
- 在 `EChartsCandlestick` 中通过副图按钮 / 主图叠加按钮切换。

## 官方对比（ZenChart 直连）

「个股分析 → 缠论视图」提供**官方对比**开关：

- 后端 `GET /api/chanlun/official` 直连 ZenChart 公开接口
  （free 端点：笔/线段/中枢；配置 `TICKFLOW_ZENCHART_TOKEN`
  环境变量后走 Pro 端点，额外含官方买卖点）。
- 前端以红色系叠加渲染：红虚线=官方笔、红实线=官方线段、红框=官方中枢，
  与本地青色/橙色图层并排比对。
- tickflow 是独立服务，不依赖任何本地 openclarr 进程。

## K 线窗口补全

`GET /api/chanlun/candles?symbol&days` 返回尽量补足 `days` 根的日 K：
本地 enriched 表优先，不足时经 TickFlow 实时拉取补齐但**不落盘**；
缠论分析与图表显示共用该序列，保证线与 K 线严格对齐。

本机若走 SOCKS 代理，需启用 socks extra：`uv sync --extra socks`。

## 时间约定

前后端 K 线时间统一为「当日本地午夜 unix 秒」；后端 czsc 输入为 naive-UTC datetime，
`bi._epoch()` 与其严格互逆，任意本地时区下索引往返一致。

## 边界

买卖点属于研究标注，与官方实现仍有已知对拍差异，不进入自动策略结果。
