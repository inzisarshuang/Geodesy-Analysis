# Geodesy-Analysis / 大地测量数据分析

Scientific processing after sensor preprocessing: InSAR baseline selection,
interferogram generation, filtering, unwrapping, atmosphere correction, and
time-series analysis.

本仓库负责传感器预处理之后的科学分析。目前已建立从配准 RSLC 到基线网络、差分
干涉图和相干性的正式 GAMMA 工作流，并支持 NL-InSAR、GAMMA BM3D 与 GAMMA ADF
三种清单驱动滤波方法、GAMMA MCF 解缠、quad 相位去趋势、大气改正，以及
GAMMA stacking、单对 DInSAR 和 `mb` SBAS/ISBAS 时序处理。

## 1. Repository Scope / 仓库定位

This repository owns scientific processing after sensor preprocessing. Its current
implemented boundary runs from a validated registered stack through GAMMA atmosphere
correction and the migrated stacking, DInSAR, and `mb` time-series workflows. MintPy
and DS-InSAR are not included in the current completion claim.

本仓库负责传感器预处理之后的科学处理。当前已实现边界从通过校验的注册栈延伸到
GAMMA 大气改正及 stacking、DInSAR、`mb` 时序处理；MintPy 和 DS-InSAR 不在当前完成声明内。

Legacy scripts remain a fallback reference until real-data comparison is complete,
but new code does not import the legacy repository. Refactoring changes contracts for
new runs and does not move, copy, or delete existing project data.

旧脚本在真实数据对照完成前保留为回退来源，但新代码不导入旧仓库。代码重构只改变
新运行的契约，不移动、复制或删除现有研究项目数据。

## 2. Project Structure / 项目结构

```text
Geodesy-Analysis/
├── src/geodesy_analysis/
│   ├── common/                         # 日志、进度、命令和路径安全
│   └── insar/
│       ├── baseline_selection/         # 基线网络计算与选择
│       ├── interferogram_generation/   # MLI、差分干涉图与相干性
│       ├── filtering/                  # NL-InSAR、GAMMA BM3D、GAMMA ADF
│       ├── unwrapping/gamma/mcf/       # GAMMA MCF 解缠
│       ├── detrending/gamma/quad/      # GAMMA quad 相位去趋势
│       ├── atmosphere/gamma/           # GAMMA 大气改正
│       └── time_series/gamma/          # stacking、DInSAR、GAMMA mb
├── config/GAMMA_mb/                    # 按处理方法归类的正式 CFG
├── docs/
│   ├── architecture.md                 # 仓库边界和模块职责
│   └── workflows/gamma_insar.md        # 从 PRE 到干涉结果的操作顺序
├── tests/                              # 命令契约、安全和回归测试
└── pyproject.toml                      # 安装信息与命令入口
```

## 3. Workflow Overview / 流程总览

正式输入是 Geodesy-Preprocessing 发布的 `registered_stack.json`。Analysis 不重新
下载数据、生成 SLC 或配准影像。

1. `geodesy-analysis-gamma-baseline` 生成 DSI、SBAS 或 PSI 网络及基线清单。
2. `geodesy-visualization baseline_plot` 读取基线清单并生成网络图；该命令属于
   Geodesy-Visualization，在 `envPlot` 中运行。
3. `geodesy-analysis-gamma-interferogram` 按网络生成 MLI、差分干涉图和相干性。
4. `geodesy-analysis-filtering` 从干涉清单选择方法并发布统一滤波清单。
5. `geodesy-analysis-gamma-mcf` 从一个显式滤波清单生成掩膜并执行 MCF 解缠。
6. `geodesy-analysis-gamma-quad-detrend` 校验 MCF、滤波和干涉来源链，并对所选相位去趋势。
7. `geodesy-analysis-gamma-atmosphere` 生成清单驱动的大气改正相位。
8. 选择 `geodesy-analysis-gamma-stacking`、`geodesy-analysis-gamma-dinsar` 或
   `geodesy-analysis-gamma-mb` 生成速度或累计 LOS 位移产品。

第 3–6 步在同一个 Analysis 命令中同步调用 GAMMA DISP，分别生成强度、相位、
相干性、滤波、解缠和去趋势 BMP 质检图；不需要独立的可视化 CFG 或第二次命令。

详细操作见 [GAMMA InSAR workflow](docs/workflows/gamma_insar.md)。

## 4. Dependencies And Installation / 环境与安装

- Python 3.10 或更高版本；当前统一测试环境为 `envInSAR`（Python 3.11）。
- GAMMA ISP、DIFF 等命令必须在 `PATH` 中。
- Python 核心依赖见 `pyproject.toml`。

```bash
/home/yilun/miniconda3/envs/envInSAR/bin/python -m pip install --no-deps -e \
  /mnt/beegfs/procesados/yiluntan/Geodesy-Analysis
```

安装后可在任意目录检查两个 Analysis 入口：

```bash
/home/yilun/miniconda3/envs/envInSAR/bin/geodesy-analysis-gamma-baseline --help
/home/yilun/miniconda3/envs/envInSAR/bin/geodesy-analysis-gamma-interferogram --help
/home/yilun/miniconda3/envs/envInSAR/bin/geodesy-analysis-filtering --help
/home/yilun/miniconda3/envs/envInSAR/bin/geodesy-analysis-gamma-mcf --help
/home/yilun/miniconda3/envs/envInSAR/bin/geodesy-analysis-gamma-quad-detrend --help
/home/yilun/miniconda3/envs/envInSAR/bin/geodesy-analysis-gamma-atmosphere --help
/home/yilun/miniconda3/envs/envInSAR/bin/geodesy-analysis-gamma-stacking --help
/home/yilun/miniconda3/envs/envInSAR/bin/geodesy-analysis-gamma-dinsar --help
/home/yilun/miniconda3/envs/envInSAR/bin/geodesy-analysis-gamma-mb --help
```

## 5. Quick Start / 快速开始

Use `--config` for the configuration, `--case` to select a named section, and
`--dry-run` to validate inputs and show the plan. Where supported, defaults for
`output_dir`, `figure_dir`, and `log_dir` derive from `processing_root`.

公开命令使用 `--config` 指定配置文件，`--case` 选择配置段，`--dry-run`
校验输入并显示计划。输出目录按用途使用 `output_dir`、`figure_dir` 和各步骤
支持的 `log_dir`，默认路径可由 `processing_root` 推导。

从仓库 `config/GAMMA_mb/` 复制或直接参考所需 CFG，使用 `--dry-run` 检查，再正式
生成基线。随后修改 `gamma_interferogram.cfg`，用同样方式检查和
运行干涉阶段。如需基线图，使用 Geodesy-Visualization 的
`config_examples/baseline_plot/baseline_plot.cfg`。CFG 的 `[project] root` 决定全部相对路径，
与终端当前目录无关。每个 `[case:main]` 还必须声明类似
`case_root = S1/ASCENDING_128` 的正式 case 路径；`main` 只是 CLI 选择标签，不参与
目录命名。

```bash
geodesy-analysis-gamma-baseline --config /absolute/PROJECT/config/GAMMA_mb/gamma_baseline.cfg --case main --dry-run
geodesy-analysis-gamma-interferogram --config /absolute/PROJECT/config/GAMMA_mb/gamma_interferogram.cfg --case main --dry-run
geodesy-analysis-filtering --config /absolute/PROJECT/config/GAMMA_mb/insar_filtering.cfg --case nl_insar
geodesy-analysis-gamma-mcf --config /absolute/PROJECT/config/GAMMA_mb/gamma_mcf_unwrapping.cfg --case main
geodesy-analysis-gamma-quad-detrend --config /absolute/PROJECT/config/GAMMA_mb/gamma_quad_detrending.cfg --case main
geodesy-analysis-gamma-atmosphere --config /absolute/PROJECT/config/GAMMA_mb/gamma_atmosphere.cfg --case main
geodesy-analysis-gamma-mb --config /absolute/PROJECT/config/GAMMA_mb/gamma_sbas_mb.cfg --case main --dry-run
```

## 6. Data And Output Behavior / 数据与输出行为

例如，`S1/ASCENDING_128/GAMMA/` 提供公共 SLC、RSLC 和配准几何；
`S1/ASCENDING_128/GAMMA_mb/` 是分析 CFG 声明的 `processing_root`。MintPy、
DSInSAR、StaMPS 等路线可在同一 case 下建立自己的目录，并通过 CFG 引用兼容的既有产品。

- PRE 输入：`registered_stack` 指向公共 `GAMMA/RSLC/registered_stack.json` 或
  `GAMMA/RSLC/SUBSET/registered_stack.json`
- 基线结果：`<processing_root>/BASELINE/`
- 干涉结果：`<processing_root>/INTF/`，内部使用 `MLI/` 与
  `PAIRS/<日期对>/`
- 本次干涉视数的 GEO 几何结果：由 `gamma_geocoding.cfg` 的 `output_dir` 指定，包含
  匹配网格的 WGS84 radar height，以及 `gc_map2` 按 SAR 覆盖范围裁剪的
  `demcrop.dem` / `demcrop.dem_par`；地图坐标栅格使用该 `.dem_par` 执行 `data2geotiff`
- 科学结果：`FILTERING/<METHOD>/`、`UNW/GAMMA_MCF/`、`DETRENDING/GAMMA_QUAD/`
- 大气和时序结果：`ATMOSPHERE/<METHOD>/`、`TIMESERIES/{STACKING,DINSAR,GAMMA_MB}/`
- 日志：`<processing_root>/LOG/ANALYSIS/<STAGE>/`
- 质检图：`<processing_root>/FIGURES/{INTF,FILTERING,UNW,DETRENDING}/...`

只有清单和所有核心文件通过检查后才发布正式目录。每次正式调用都会重新执行科学
命令；新结果完整通过验证后事务替换旧目录，计算或发布失败时恢复旧结果。输入签名
与全部参数继续写入 manifest/provenance 用于比较，但不参与跳过或阻止运行。若需同时
保留两组结果，用户可指定不同的 `output_dir`。干涉科学、GEO 和快视图输出均可在 CFG 中指定
项目相对路径或任意绝对路径。新写出的 Analysis 清单使用 schema v2；项目内路径采用
相对形式，外部输出路径记录为绝对形式。迁移期读端继续接受 schema v1。上述 GAMMA DISP BMP 是各科学阶段拥有的
原生质量检查图，按阶段/方法平铺。Geodesy-Visualization 继续负责基线网络图、
PyGMT 地图、论文图和其他二次渲染。

## 7. Verification And Development / 验证与开发

```bash
conda activate envInSAR
python -m compileall -q src/geodesy_analysis
python -m pytest -q
git diff --check
```

Development changes must preserve manifest validation, safe rerun behavior, explicit
method directories, and the separation between scientific quicklooks and publication
visualization.

开发改动必须保留清单校验、安全重跑、显式方法目录，以及科学质检图与最终制图之间
的职责边界。

## 8. Security / 安全说明

Review project roots, method roots, and output directories before running a command.
Do not commit credentials, private data, filled project CFG files, or restricted
scientific products.

运行命令前检查项目根目录、方法根目录和输出目录。不要提交凭据、私有数据、已填写的
项目 CFG 或受限制的科学产品。

## 9. License Notice / 许可说明

No standalone license file is currently included. Confirm usage and redistribution
terms before distributing this repository or derived software.

本仓库当前未包含独立许可证文件。在分发本仓库或衍生软件前，请先确认使用与再分发
条款。
