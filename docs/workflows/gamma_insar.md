# GAMMA InSAR：RSLC 到差分干涉图

本文说明当前正式流程的操作顺序。命令使用 `envInSAR` 内的绝对入口，因此可从
任意目录运行；CFG 内相对路径始终以 `[project] root` 为基准。

## 1. 输入检查

Geodesy-Preprocessing 必须已经发布完整的 `registered_stack.json`。它应列出参考
日期、传感器、极化和每个日期的 RSLC/参数文件。Analysis 不再扫描目录猜测输入。

## 2. 基线选择

从 `config_examples/gamma_baseline.cfg` 复制一份到项目的 `config/analysis/`，填写
注册栈、极化、网络类型、基线阈值和结果目录。

```bash
/home/yilun/miniconda3/envs/envInSAR/bin/geodesy-analysis-gamma-baseline \
  --config /absolute/PROJECT/config/analysis/gamma_baseline.cfg \
  --case main --dry-run

/home/yilun/miniconda3/envs/envInSAR/bin/geodesy-analysis-gamma-baseline \
  --config /absolute/PROJECT/config/analysis/gamma_baseline.cfg \
  --case main
```

完成后检查网络表、PNG 和 `baseline_manifest.json`。如果只想调整图形，不重算
网络，可运行：

```bash
/home/yilun/miniconda3/envs/envInSAR/bin/geodesy-analysis-baseline-plot \
  --config /absolute/PROJECT/config/analysis/baseline_plot.cfg --case main
```

## 3. 干涉图生成

从 `config_examples/gamma_interferogram.cfg` 复制项目 CFG。`baseline_manifest` 必须
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
应与 dry-run 一致，清单列出的 MLI、`pair.tflt` 和 `pair.cc` 等文件均应非空。

## 4. 日志与重跑

基线日志位于 `LOG/ANALYSIS/GAMMA/BASELINE/<case>/`，干涉日志位于
`LOG/ANALYSIS/GAMMA/INTERFEROGRAM/<case>/`。干涉失败日志会改名为
`<case>.failed-logs-N`，终端报错会给出位置。

相同输入和参数且结果完整时命令返回 `skipped`。已有目录不完整或来源、参数发生
变化时命令停止，不会覆盖。确认确需重算后，先由用户把旧结果移到备份目录。

## 5. 当前终点

当前链条止于差分干涉图与相干性清单。滤波、解缠、大气改正和时序分析属于接下来
的 Analysis 阶段，不应把本流程的完成误解为完整 InSAR 反演已经完成。

