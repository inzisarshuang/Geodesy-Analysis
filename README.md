# Geodesy-Analysis / 大地测量分析

This repository is the target owner for scientific processing after sensor-level
preprocessing: baseline selection, interferogram generation, filtering,
unwrapping, atmosphere correction, and time-series analysis.

本仓库用于承接配准后的科学分析，包括基线选择、干涉、滤波、解缠、大气改正与
时序分析。F1 正在迁移已有 GAMMA Analysis 包；在兼容和真实工程影子验收完成前，
本仓库尚不是默认入口。

Version 0.1.0 packages the existing baseline and filtering implementation plus
the masking and time-series modules migrated in the next F1 step. Numerical
runtime dependencies are NumPy, SciPy, and the installed Data Adapter; plotting,
image I/O, and GNSS tables use explicit optional dependency groups.

0.1.0 版首先封装现有基线和滤波实现，随后在同一 F1 阶段迁入掩膜与时序模块。
数值运行依赖为 NumPy、SciPy 和已安装的 Data Adapter；绘图、图像 I/O 与 GNSS
表格使用明确的可选依赖组。

MintPy and DS-InSAR are deliberately deferred until the existing processing path
has been migrated and validated end to end.
