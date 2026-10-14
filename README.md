# Geodesy-Analysis / 大地测量数据分析

Scientific processing after sensor preprocessing: InSAR baseline selection,
interferogram generation, filtering, unwrapping, atmosphere correction, and
time-series analysis.

本仓库负责传感器预处理之后的科学分析。目前已建立从配准 RSLC 到基线网络、差分
干涉图和相干性的正式 GAMMA 工作流；滤波、解缠和时序模块按后续阶段继续迁移。

## 1. Project Structure / 项目结构

```text
Geodesy-Analysis/
├── src/geodesy_analysis/
│   ├── common/                         # 日志、进度、命令和路径安全
│   └── insar/
│       ├── baseline_selection/         # 基线网络计算与选择
│       └── interferogram_generation/   # MLI、差分干涉图与相干性
├── config_examples/                    # 完整注释的正式 CFG 示例
├── docs/
│   ├── architecture.md                 # 仓库边界和模块职责
│   └── workflows/gamma_insar.md        # 从 PRE 到干涉结果的操作顺序
├── tests/                              # 命令契约、安全和回归测试
└── pyproject.toml                      # 安装信息与命令入口
```

## 2. Workflow Overview / 流程总览

正式输入是 Geodesy-Preprocessing 发布的 `registered_stack.json`。Analysis 不重新
下载数据、生成 SLC 或配准影像。

1. `geodesy-analysis-gamma-baseline` 生成 DSI、SBAS 或 PSI 网络及基线清单。
2. `geodesy-visualization-insar-baseline` 读取基线清单并生成网络图；该命令属于
   Geodesy-Visualization，在 `envPlot` 中运行。
3. `geodesy-analysis-gamma-interferogram` 按网络生成 MLI、差分干涉图和相干性。

详细操作见 [GAMMA InSAR workflow](docs/workflows/gamma_insar.md)。

## 3. Dependencies and Installation / 环境与安装

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
```

## 4. Quick Start / 快速开始

先复制并修改 `config_examples/gamma_baseline.cfg`，使用 `--dry-run` 检查，再正式
生成基线。随后复制 `config_examples/gamma_interferogram.cfg`，用同样方式检查和
运行干涉阶段。如需基线图，使用 Geodesy-Visualization 的
`config_examples/baseline_plot.cfg`。CFG 的 `[project] root` 决定全部相对路径，
与终端当前目录无关。

```bash
geodesy-analysis-gamma-baseline --config /absolute/PROJECT/config/analysis/gamma_baseline.cfg --case main --dry-run
geodesy-analysis-gamma-baseline --config /absolute/PROJECT/config/analysis/gamma_baseline.cfg --case main
geodesy-analysis-gamma-interferogram --config /absolute/PROJECT/config/analysis/gamma_interferogram.cfg --case main --dry-run
geodesy-analysis-gamma-interferogram --config /absolute/PROJECT/config/analysis/gamma_interferogram.cfg --case main
```

## 5. Outputs and Logs / 结果与日志

- 基线结果：`ANALYSIS/GAMMA/<case>/BASELINE/`
- 干涉结果：`ANALYSIS/GAMMA/<case>/INTERFEROGRAM/`
- 基线日志：`LOG/ANALYSIS/GAMMA/BASELINE/<case>/`
- 干涉日志：`LOG/ANALYSIS/GAMMA/INTERFEROGRAM/<case>/`

只有清单和所有核心文件通过检查后才发布正式目录。相同输入可安全跳过；输入或参数
变化时停止并要求用户处理旧结果，不静默覆盖。

## 6. Current Scope / 当前范围

本阶段完成到差分干涉图和相干性。滤波、解缠、大气改正、MintPy、DS-InSAR 不在
当前完成声明内。旧脚本在真实数据对照完成前保留为回退来源，但新代码不导入旧仓库。
