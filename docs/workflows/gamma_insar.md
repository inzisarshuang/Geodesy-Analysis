# GAMMA InSAR：RSLC 到差分干涉图

本文说明当前正式流程的操作顺序。命令使用 `envInSAR` 内的绝对入口，因此可从
任意目录运行；CFG 内相对路径始终以 `[project] root` 为基准。示例的
`[case:main]` 使用 `case_root = S1/ASCENDING_128`：`main` 只是 `--case` 的选择
标签，正式目录身份完全由 `case_root` 决定。

## 1. 输入检查

Geodesy-Preprocessing 必须已经发布完整的 `registered_stack.json`。它应列出参考
日期、传感器、极化和每个日期的 RSLC/参数文件。正式输入位置为
`S1/ASCENDING_128/PRE/GAMMA/RSLC_SUBSET/registered_stack.json`。Analysis 不再
扫描目录猜测输入。

## 2. 基线选择

从 `config_examples/analysis/gamma_baseline.cfg` 复制一份到项目的 `config/analysis/`，填写
注册栈、极化、网络类型、基线阈值和结果目录。`output_dir` 可使用项目相对路径
或任意绝对路径，但不能覆盖注册栈输入或本阶段日志。

```bash
/home/yilun/miniconda3/envs/envInSAR/bin/geodesy-analysis-gamma-baseline \
  --config /absolute/PROJECT/config/analysis/gamma_baseline.cfg \
  --case main --dry-run

/home/yilun/miniconda3/envs/envInSAR/bin/geodesy-analysis-gamma-baseline \
  --config /absolute/PROJECT/config/analysis/gamma_baseline.cfg \
  --case main
```

完成后检查网络表和 `baseline_manifest.json`；Analysis 不再生成 PNG。若需绘制
或调整基线图，把 Geodesy-Visualization 的 `config_examples/visualization/baseline_plot.cfg`
复制到项目 `config/visualization/`，然后在 `envPlot` 中运行：

```bash
/home/yilun/miniconda3/envs/envPlot/bin/geodesy-visualization-insar-baseline \
  --config /absolute/PROJECT/config/visualization/baseline_plot.cfg --case main
```

该命令仅读取已完成的 `baseline_manifest.json` 及其中引用的网络表，不调用 GAMMA，
输出位置由 Visualization CFG 决定。基线图不是下一步干涉计算的必需输入。

## 3. 干涉图生成

从 `config_examples/analysis/gamma_interferogram.cfg` 和
`config_examples/analysis/gamma_geocoding.cfg` 复制项目 CFG。`baseline_manifest` 必须
来自上一步；地理编码 CFG 提供 DEM 和参数文件。干涉阶段使用当前 `range_looks` /
`azimuth_looks` 生成参考 MLI，再按相同网格重新地理编码，不再依赖 PRE 阶段的旧 `radar_height`。

```bash
/home/yilun/miniconda3/envs/envInSAR/bin/geodesy-analysis-gamma-interferogram \
  --config /absolute/PROJECT/config/analysis/gamma_interferogram.cfg \
  --case main --dry-run

/home/yilun/miniconda3/envs/envInSAR/bin/geodesy-analysis-gamma-interferogram \
  --config /absolute/PROJECT/config/analysis/gamma_interferogram.cfg \
  --case main
```

完成后检查 `interferogram_manifest.json`：状态应为 `complete`，日期和干涉对数量
应与 dry-run 一致，清单列出的 `MLI/`、`PAIRS/<日期对>/pair.tflt` 和 `pair.cc`
等文件均应非空。同时检查 geocoding CFG 的 `output_dir`：本次视数相关的地理编码几何文件集中保存在
`<processing_root>/GEOCODING`，包括 `demcrop.dem` 和 `demcrop.dem_par`。它们由 `gc_map2`
根据原始 DEM 自动裁剪到参考 SAR 覆盖范围；地图坐标栅格转 GeoTIFF 时使用
`demcrop.dem_par`，例如 `data2geotiff demcrop.dem_par <map-grid-data> 2 <output.tif>`。
不要用该地图网格参数转换雷达坐标的 `.hgt` 或 `.wgs84.hgt`。逐景 MLI、`ave_mli`、差分相位和相干性 BMP 则按原规定写入
干涉 CFG 的 `figure_dir`（`<processing_root>/FIGURES/INTF`）。
干涉科学、GEO 和快视图目录均可使用项目相对路径或任意绝对路径，且不能相互重叠。
Geodesy-Visualization 仍负责 PyGMT 地图、论文图和其他二次渲染。

## 4. 滤波

复制 `config_examples/analysis/insar_filtering.cfg` 到项目 `config/analysis/`。每个 case 显式
选择 `nl_insar`、`gamma_bm3d` 或 `gamma_adf`，并读取上一阶段完整的
`interferogram_manifest.json`。未填写 `output_dir` 时自动落到
`<processing_root>/FILTERING/<METHOD>`；填写后使用指定目录。

```bash
/home/yilun/miniconda3/envs/envInSAR/bin/geodesy-analysis-filtering \
  --config /absolute/PROJECT/config/analysis/insar_filtering.cfg --dry-run

/home/yilun/miniconda3/envs/envInSAR/bin/geodesy-analysis-filtering \
  --config /absolute/PROJECT/config/analysis/insar_filtering.cfg --case gamma_bm3d
```

指定 `--case` 时只验证并运行该 case；省略时按 CFG 顺序执行全部 case。同一方法的
不同参数若需并存，由用户手动指定不同的 `output_dir`；程序不生成 `main`、`test`
或编号 `run_id`。完整且签名一致时跳过；只缺快视图时只补图。三种方法
统一发布 `pairs/<日期对>/pair.tflt.filt`、`pair.coh.filt`、`coh_ave.coh` 和
`filtering_manifest.json`。
滤波时实际使用的方法参数保存在同目录的 `provenance.json`；manifest 主要描述产品、
pair 库存及上游来源摘要。
每个方法的 `figure_dir` 同时平铺保存滤波相位与相干性 BMP。未填写时按方法
自动生成标准路径；手动设置可使用项目相对路径或任意绝对路径，但不能与输入或科学
输出重叠。
若干涉图输出位于项目外，`interferogram_manifest` 使用该清单的绝对路径，并为滤波阶段
显式设置 `output_dir`。所有工具和运行依赖需在当前环境 `PATH` 中可用；`--dry-run`
会检查清单、MLI 参数和栅格尺寸，但不会检查 GAMMA 可执行文件是否能成功运行。

## 5. GAMMA MCF 解缠

复制 `config_examples/analysis/gamma_mcf_unwrapping.cfg`，并显式选择一个已完成的
`filtering_manifest.json`。解缠目录固定表达方法 `GAMMA_MCF`，上游是 NL-InSAR、
BM3D 还是 ADF 由 manifest lineage 记录，不叠加到目录层级。

```bash
/home/yilun/miniconda3/envs/envInSAR/bin/geodesy-analysis-gamma-mcf \
  --config /absolute/PROJECT/config/analysis/gamma_mcf_unwrapping.cfg --dry-run

/home/yilun/miniconda3/envs/envInSAR/bin/geodesy-analysis-gamma-mcf \
  --config /absolute/PROJECT/config/analysis/gamma_mcf_unwrapping.cfg --case main
```

`reference_mode=auto` 在最终掩膜内选择平均相干性最高的有限像元；`manual` 使用
零起始 `reference_range`、`reference_azimuth`，越界或被掩膜时停止。默认输出为
`<processing_root>/UNW/GAMMA_MCF`，也可通过 `output_dir` 指定项目相对路径或任意绝对路径。
解缠 BMP 由同一命令写入 `FIGURES/UNW/GAMMA_MCF/`；`final.mask.bmp`
是 MCF 计算输入，只保留在 Analysis 科学目录。

默认解缠 filtering manifest 中的全部干涉对。若只需选择其中一部分，在方法根目录
创建 `pairs.txt`（例如 `S1/ASCENDING_128/GAMMA/pairs.txt`），文本文件每行写一个完整的
`YYYYMMDD-YYYYMMDD` pair 名；空行和 `#` 注释行会忽略。程序先完整校验 filtering
manifest 及其与干涉 manifest 的来源、pair 集合和产品，再按列表挑选本次要解缠的 pair；
未知或重复 pair 会报错。没有该文件时仍处理全部 pair。这个 case 级 `pairs.txt` 是
后续可由滤波、解缠等阶段共享的选择入口；当前先由 MCF 读取，不需要在各阶段 CFG
重复设置列表路径。掩膜和自动参考点始终使用
完整 filtering manifest 的 `coh_ave.coh`，不会因只选部分 pair 而改变。解缠的
manifest/provenance 会记录可用 pair 数、本次选择、`pairs.txt` 路径及 SHA-256；
filtering manifest 保持原样，继续描述完整滤波产物。

## 6. Quad 相位去趋势

复制 `config_examples/analysis/gamma_quad_detrending.cfg` 到项目配置目录，并填写
已完成的 GAMMA MCF `unwrapping_manifest.json`。程序沿 manifest 校验 MCF 输出、
filtered coherence 与干涉阶段的主影像 MLI 参数，不需要手工填写这些输入路径。

```bash
/home/yilun/miniconda3/envs/envInSAR/bin/geodesy-analysis-gamma-quad-detrend \
  --config /absolute/PROJECT/config/analysis/gamma_quad_detrending.cfg \
  --case main --dry-run

/home/yilun/miniconda3/envs/envInSAR/bin/geodesy-analysis-gamma-quad-detrend \
  --config /absolute/PROJECT/config/analysis/gamma_quad_detrending.cfg \
  --case main
```

`coherence_threshold` 默认 `0.15`，`trend_model` 默认 GAMMA `quad_fit` model `0`，
允许值为 `0`–`7`。处理 pair 与 MCF 共用方法根目录的 `pairs.txt`：列表中任何
pair 若不在当前 MCF manifest 中都会明确报错，避免静默取交集；修改列表后须先让
MCF 输出与该列表同步。科学结果、掩膜和拟合数据写入
`<processing_root>/DETRENDING/GAMMA_QUAD/`，BMP 写入
`FIGURES/DETRENDING/GAMMA_QUAD/`。CFG 的 `intensity_background` 控制 BMP 快视图是否叠加主影像 MLI：默认 `true`
保持现有方式，设为 `false` 则使用与 MCF 一样的无强度底图方式；此项不影响 Analysis
科学相位数据。该阶段要求上游为 schema-v2 GAMMA MCF 解缠产物；尚未发布该 manifest 的
传感器流程不能直接配置运行。

## 7. 日志与重跑

日志统一位于 `<processing_root>/LOG/ANALYSIS/<STAGE>/`。失败日志目录会追加
`failed-logs-N`，终端报错会给出位置。

基线、干涉、滤波、解缠和去趋势命令遇到完整同签名结果时跳过，只缺快视图时仅补图；
残缺或签名变化时拒绝覆盖并提示删除对应结果或另设输出目录。CFG 指定 `--case` 时仅
验证和运行该 case，不因其他 case 的配置错误而阻塞。解缠前需保证所选过滤清单与当前
干涉清单的摘要和 pair 清单一致；若上游干涉结果已更新，应先重新运行对应滤波方法。

新生成的 baseline 和 interferogram 清单使用 schema v2；项目内跨阶段引用使用相对路径，
干涉输出若在项目外则记录为绝对路径。迁移期仍能读取已有 schema v1 基线清单。本次代码变更不会移动、
复制或删除已有研究项目数据。

## 8. 当前终点

当前链条止于 GAMMA quad 去趋势清单。大气改正和时序分析属于接下来
的 Analysis 阶段，不应把本流程的完成误解为完整 InSAR 反演已经完成。
