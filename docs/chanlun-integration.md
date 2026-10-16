# 原生缠论集成

TickFlow 内置缠论结构分析（包含处理 / 分型 / 笔 / 线段 / 中枢 / 买卖点），算法移植自
`openclarr-chanlun` 原型，直接运行在 TickFlow 后端，无需任何外部服务或 iframe。

## 架构

- **后端** `backend/app/chanlun/`：merge_klines、fractal、bi（czsc 引擎）、segment、
  zhongshu、macd、bsp 七层流水线；`pipeline.analyze(candles)` 一次输出全部图层。
- **API** `POST /api/chanlun/analyze`：body 为 `{"candles": [{time, open, high, low, close, volume}, ...]}`，
  返回全部结构层以及算法版本、数据指纹和末笔确认状态。
- **前端渲染**：个股分析页由 `UnifiedStockChart` 在唯一 ECharts 中叠加包含处理、分型、笔、段、中枢和买卖点；旧 `ChanlunKlineWorkbench` 暂留兼容，不再是页面入口。

## 扩展技术指标

60+ 指标公式移植于 openclarr-chanlun 前端，纯前端计算：

- `frontend/src/lib/indicator-formulas.ts`：全部公式（SMA/EMA/BOLL/BBI/SAR/ZIGZAG/
  TEMA/DEMA/HMA/WMA/VWMA/VWAP/Supertrend/Donchian/Keltner/Ichimoku/Alligator/LinReg/KDJCh/WRCh
  主图叠加 + KDJ/RSI/WR/CCI/BIAS/OBV/VR/ATR/DMI/MTM/ROC/MFI/CMF/CMO/TRIX/TSI/
  Stoch/StochRSI/PPO/DMA/UO/Vortex/PSY/Chop/AO/Aroon/PVT/DPO/ForceIndex/EMV/ADL/
  ChaikinOsc/ElderRay/TTMSqueeze/STC/CR/BRAR 副图）。
- `frontend/src/lib/indicator-params.ts`：各指标可调参数与默认值（localStorage 持久化）。
- 在统一个股图表的指标抽屉中多选、配置、排序、折叠和调整高度。

## 官方对比（ZenChart 直连）

统一工作台的缠论层提供**官方对比**开关：

- 后端 `GET /api/chanlun/official` 直连 ZenChart 公开接口
  （free 端点：笔/线段/中枢；配置 `TICKFLOW_ZENCHART_TOKEN`
  环境变量后走 Pro 端点，额外含官方买卖点）。
- 前端以红色系叠加渲染：红虚线=官方笔、红实线=官方线段、红框=官方中枢，
  与本地青色/橙色图层并排比对。
- 官方时间戳必须全部映射到当前本地 candles；存在任何无法对齐端点时拒绝整层叠加并显示原因。官方响应绝不替换本地 K 线底座。
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
