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
注册栈、极化、网络类型、基线阈值和结果目录。

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

从 `config_examples/analysis/gamma_interferogram.cfg` 复制项目 CFG。`baseline_manifest` 必须
来自上一步；`radar_height` 必须是与当前裁剪 RSLC 和视数一致的雷达坐标高程。

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
等文件均应非空。同时检查 `visualization_dir`：逐景 MLI、`ave_mli`、差分相位和
相干性 BMP 应平铺在同一目录。它们是本阶段通过 GAMMA DISP 同步生成的原生质检图；
Geodesy-Visualization 仍负责 PyGMT 地图、论文图和其他二次渲染。

## 4. 滤波

复制 `config_examples/analysis/insar_filtering.cfg` 到项目 `config/analysis/`。每个 case 显式
选择 `nl_insar`、`gamma_bm3d` 或 `gamma_adf`，并读取上一阶段完整的
`interferogram_manifest.json`。未填写 `output_dir` 时自动落到
`ANALYSIS/FILTERING/<METHOD>`；填写后使用项目根内的指定目录。

```bash
/home/yilun/miniconda3/envs/envInSAR/bin/geodesy-analysis-filtering \
  --config /absolute/PROJECT/config/analysis/insar_filtering.cfg --dry-run

/home/yilun/miniconda3/envs/envInSAR/bin/geodesy-analysis-filtering \
  --config /absolute/PROJECT/config/analysis/insar_filtering.cfg --case gamma_bm3d
```

省略 `--case` 会按 CFG 顺序执行全部 case。同一方法的不同参数若需并存，由用户
手动指定新的 `output_dir`；程序不生成 `main`、`test` 或编号 `run_id`。三种方法
统一发布 `pairs/<日期对>/pair.tflt.filt`、`pair.coh.filt`、`coh_ave.coh` 和
`filtering_manifest.json`。
每个方法的 `visualization_dir` 同时平铺保存滤波相位与相干性 BMP。未填写时按方法
自动生成标准路径；手动设置时必须位于当前 case 且不能与输入或科学输出重叠。

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
`ANALYSIS/UNWRAPPING/GAMMA_MCF`，也可显式覆盖到项目根内的其他目录。
解缠 BMP 由同一命令写入 `VISUALIZATION/UNWRAPPING/GAMMA_MCF/`；`final.mask.bmp`
是 MCF 计算输入，只保留在 Analysis 科学目录。

## 6. 日志与重跑

基线日志位于 `S1/ASCENDING_128/LOG/ANALYSIS/BASELINE_SELECTION/GAMMA/`，干涉日志位于
`S1/ASCENDING_128/LOG/ANALYSIS/INTERFEROGRAM_GENERATION/GAMMA/`，滤波日志位于
`S1/ASCENDING_128/LOG/ANALYSIS/FILTERING/<METHOD>/`，解缠日志位于
`S1/ASCENDING_128/LOG/ANALYSIS/UNWRAPPING/GAMMA_MCF/`。失败日志目录会追加
`failed-logs-N`，终端报错会给出位置。

相同输入和参数且结果完整时命令返回 `skipped`。已有目录不完整或来源、参数发生
变化时命令停止，不会覆盖。确认确需重算后，先由用户把旧结果移到备份目录。

新生成的 baseline 和 interferogram 清单使用 portable schema v2，跨阶段引用均为
项目相对路径；迁移期仍能读取已有 schema v1 基线清单。本次代码变更不会移动、
复制或删除已有研究项目数据。

## 7. 当前终点

当前链条止于 GAMMA MCF 解缠清单。大气改正和时序分析属于接下来
的 Analysis 阶段，不应把本流程的完成误解为完整 InSAR 反演已经完成。
