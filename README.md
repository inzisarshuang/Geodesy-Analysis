# Geodesy-Analysis / 大地测量数据分析

Scientific processing after sensor preprocessing: InSAR baseline selection,
interferogram generation, filtering, unwrapping, atmosphere correction, and
time-series analysis.

本仓库负责传感器预处理之后的科学分析。目前已建立从配准 RSLC 到基线网络、差分
干涉图和相干性的正式 GAMMA 工作流，并支持 NL-InSAR、GAMMA BM3D 与 GAMMA ADF
三种清单驱动滤波方法、GAMMA MCF 解缠和 quad 相位去趋势；大气改正和时序模块按后续阶段继续迁移。

## 1. Repository Scope / 仓库定位

This repository owns scientific processing after sensor preprocessing. Its current
implemented boundary runs from a validated registered stack through GAMMA quad phase
detrending. Atmosphere correction, MintPy, and DS-InSAR are not included in the
current completion claim.

本仓库负责传感器预处理之后的科学处理。当前已实现边界从通过校验的注册栈延伸到
GAMMA quad 相位去趋势；大气改正、MintPy 和 DS-InSAR 不在当前完成声明内。

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
│       └── detrending/gamma/quad/      # GAMMA quad 相位去趋势
├── config_examples/
│   └── analysis/                       # Analysis 阶段正式 CFG 示例
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
2. `geodesy-visualization-insar-baseline` 读取基线清单并生成网络图；该命令属于
   Geodesy-Visualization，在 `envPlot` 中运行。
3. `geodesy-analysis-gamma-interferogram` 按网络生成 MLI、差分干涉图和相干性。
4. `geodesy-analysis-filtering` 从干涉清单选择方法并发布统一滤波清单。
5. `geodesy-analysis-gamma-mcf` 从一个显式滤波清单生成掩膜并执行 MCF 解缠。
6. `geodesy-analysis-gamma-quad-detrend` 校验 MCF、滤波和干涉来源链，并对所选相位去趋势。

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
```

## 5. Quick Start / 快速开始

先复制并修改 `config_examples/analysis/gamma_baseline.cfg`，使用 `--dry-run` 检查，再正式
生成基线。随后复制 `config_examples/analysis/gamma_interferogram.cfg`，用同样方式检查和
运行干涉阶段。如需基线图，使用 Geodesy-Visualization 的
`config_examples/visualization/baseline_plot.cfg`。CFG 的 `[project] root` 决定全部相对路径，
与终端当前目录无关。每个 `[case:main]` 还必须声明类似
`case_root = S1/ASCENDING_128` 的正式 case 路径；`main` 只是 CLI 选择标签，不参与
目录命名。

```bash
geodesy-analysis-gamma-baseline --config /absolute/PROJECT/config/2analysis/gamma_baseline.cfg --case main --dry-run
geodesy-analysis-gamma-baseline --config /absolute/PROJECT/config/2analysis/gamma_baseline.cfg --case main
geodesy-analysis-gamma-interferogram --config /absolute/PROJECT/config/2analysis/gamma_interferogram.cfg --case main --dry-run
geodesy-analysis-gamma-interferogram --config /absolute/PROJECT/config/2analysis/gamma_interferogram.cfg --case main
geodesy-analysis-filtering --config /absolute/PROJECT/config/2analysis/insar_filtering.cfg --dry-run
geodesy-analysis-filtering --config /absolute/PROJECT/config/2analysis/insar_filtering.cfg --case nl_insar
geodesy-analysis-gamma-mcf --config /absolute/PROJECT/config/2analysis/gamma_mcf_unwrapping.cfg --case main
geodesy-analysis-gamma-quad-detrend --config /absolute/PROJECT/config/2analysis/gamma_quad_detrending.cfg --case main --dry-run
geodesy-analysis-gamma-quad-detrend --config /absolute/PROJECT/config/2analysis/gamma_quad_detrending.cfg --case main
```

## 6. Data And Output Behavior / 数据与输出行为

- PRE 输入：`<processing_root>/RSLC/registered_stack.json` 或 `RSLC/SUBSET/registered_stack.json`
- 基线结果：`<processing_root>/BASELINE/`
- 干涉结果：`<processing_root>/INTF/`，内部使用 `MLI/` 与
  `PAIRS/<日期对>/`
- 本次干涉视数的 GEO 几何结果：由 `gamma_geocoding.cfg` 的 `output_dir` 指定，包含
  匹配网格的 WGS84 radar height，以及 `gc_map2` 按 SAR 覆盖范围裁剪的
  `demcrop.dem` / `demcrop.dem_par`；地图坐标栅格使用该 `.dem_par` 执行 `data2geotiff`
- 科学结果：`FILTERING/<METHOD>/`、`UNW/GAMMA_MCF/`、`DETRENDING/GAMMA_QUAD/`
- 日志：`<processing_root>/LOG/ANALYSIS/<STAGE>/`
- 质检图：`<processing_root>/FIGURES/{INTF,FILTERING,UNW,DETRENDING}/...`

只有清单和所有核心文件通过检查后才发布正式目录。完整且签名一致的结果直接跳过；
只缺质检图时仅补图，不重跑科学命令。残缺结果或签名变化不会自动覆盖，用户检查后
删除对应结果目录或指定新的 `output_dir` 再运行。干涉科学、GEO 和快视图输出均可在 CFG 中指定
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
