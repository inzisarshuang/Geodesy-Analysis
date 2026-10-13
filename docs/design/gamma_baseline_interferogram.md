# GAMMA 基线选择与干涉图生成设计

## 1. 目标

本阶段把旧 `2-baseline_select` 和 `5-product` 中的生产逻辑迁入
`Geodesy-Analysis`，形成与 `Geodesy-Preprocessing` 一致的 CFG、命令行、进度、
日志和结果清单。用户从 PRE 发布的 `registered_stack.json` 开始，不再手工编写
`images`、建立 RSLC 链接或从文件名猜测参考日期。

本阶段只完成：

1. GAMMA DSI、SBAS、PSI 基线网络生成和自动基线图；
2. 按基线网络逐对生成原始干涉图、MLI、轨道基线、去平干涉图、去地形相位
   干涉图和相干性；
3. 提供独立基线重绘入口，迁入旧 `baselineplot_main.py` 的 CFG 和绘图参数；
4. 为后续滤波和解缠发布稳定的结果清单。

本阶段不包含网络相干性优选、滤波、解缠、大气改正或时序反演，也不把科学
处理放入 `Geodesy-Data-Adapter`。

## 2. 实现原则

采用“Python 管理流程，GAMMA 完成科学计算”的方案。Python 负责读取和检查
CFG、校验 PRE 清单、规划任务、调用命令、显示进度、保存日志以及发布清单；
`base_calc`、`SLC_intf`、`base_init`、`phase_sim_orb` 等 GAMMA 程序继续负责数值
计算。现有 `geodesy_analysis.insar.baseline` 中的绘图和网络解析函数继续复用。

旧 Shell 脚本只用于命令序列和结果对照，新入口不得在运行时调用
`GAMMA-InSAR/2-GAMMA-POST/2-baseline_select` 或 `5-product`。

## 3. 源码结构

```text
src/geodesy_analysis/
├── common/
│   ├── paths.py
│   └── progress.py
└── insar/
    ├── baseline_selection/
    │   ├── common/
    │   │   ├── plot_config.py
    │   │   └── plot_cli.py
    │   └── gamma/
    │       ├── cli.py
    │       ├── config.py
    │       ├── models.py
    │       ├── plan.py
    │       ├── publication.py
    │       └── runner.py
    └── interferogram_generation/
        ├── common/
        └── gamma/
            ├── cli.py
            ├── config.py
            ├── models.py
            ├── plan.py
            ├── publication.py
            └── runner.py
```

`common` 只存放与 GAMMA 无关的路径和进度协议。GAMMA 命令、参数及产物命名
只能出现在各功能的 `gamma` 目录中，给未来 ISCE 或自研实现保留并列位置。

## 4. 用户入口和 CFG

### 4.1 基线选择

```bash
geodesy-analysis-gamma-baseline \
  --config PROJECT/config/analysis/gamma_baseline.cfg \
  --case ascending --dry-run

geodesy-analysis-gamma-baseline \
  --config PROJECT/config/analysis/gamma_baseline.cfg \
  --case ascending
```

CFG 使用 PRE 的 `[project]`、`[defaults]` 和 `[case:name]` 结构。核心参数为：

- `registered_stack`：PRE 发布的 schema v2 完整注册栈；
- `polarization`：本次分析极化，必须存在于清单并覆盖全部日期；
- `network_type`：`DSI`、`SBAS` 或 `PSI`；
- `max_perpendicular_baseline`：SBAS/DSI 的空间基线阈值，单位 m；
- `max_temporal_baseline`：SBAS/DSI 的时间基线阈值，单位天；
- `output_dir`：基线阶段独立输出目录。

参考日期直接读取 `registered_stack.json`，不允许 CFG 再填写另一个不一致的值。

基线选择完成后默认自动生成 PNG。独立重绘不重新运行 `base_calc`：

```bash
geodesy-analysis-baseline-plot \
  --config PROJECT/config/analysis/baseline_plot.cfg \
  --case ascending

geodesy-analysis-baseline-plot \
  /absolute/path/baseline_select_SBAS \
  --master-date 20231222 \
  --out /absolute/path/baseline_select_SBAS.png
```

独立绘图 CFG 同样采用 `[project]`、`[defaults]` 和 `[case:name]`。它迁入旧脚本的
`baseline`、`master_date`、`orbit`、`out`、`title`、`dpi`、`figsize`、
`y_top_extra`、`y_bottom_extra` 和 `font_family` 能力。命令行显式参数覆盖 CFG；
所有输入和输出仍限制在项目根目录内。绘图属于来源无关的分析诊断，因此入口名
不含 `gamma`。

### 4.2 干涉图生成

```bash
geodesy-analysis-gamma-interferogram \
  --config PROJECT/config/analysis/gamma_interferogram.cfg \
  --case ascending --dry-run

geodesy-analysis-gamma-interferogram \
  --config PROJECT/config/analysis/gamma_interferogram.cfg \
  --case ascending
```

核心参数为：

- `registered_stack`：必须与基线阶段使用的清单相同；
- `baseline_manifest`：上一阶段发布的结果清单；
- `polarization`：必须与基线阶段一致；
- `range_looks`、`azimuth_looks`：干涉图和 MLI 的视数；
- `radar_height`：与当前 RSLC 及上述视数完全匹配的雷达坐标高程；
- `spectral_filter`：`auto`、`on` 或 `off`。`auto` 对 Sentinel-1 解析为
  `off`，其他传感器解析为 `on`，解析结果写入 provenance；
- `output_dir`：本阶段独立输出目录。

高级参数保留在 `[defaults]` 中并逐项注释，包括 `create_offset` 的初始偏移、
窗口、搜索范围、相关阈值，以及 `cc_wave` 的距离向和方位向窗口。默认值保持旧
生产脚本行为，用户通常不需要修改。

`radar_height` 必须显式填写，不根据文件名猜测。程序用 MLI 行列数和文件字节数
检查其网格是否匹配；裁剪 RSLC 必须使用同步裁剪或重新生成的雷达坐标高程。

## 5. 数据流

### 5.1 基线选择

1. 严格读取 `registered_stack.json`；
2. 检查 `status=complete`、`backend.name=gamma`、`geometry_type=radar_grid`；
3. 选出指定极化的全部日期资产，并检查参考日期存在；
4. 在工作目录生成 `images` 和 `SLC_tab`；
5. 按 DSI/SBAS/PSI 模式调用一次 `base_calc`；
6. 解析 `Berp_SC`，去除自干涉、标准化日期顺序并确定性排序；
7. 生成网络表和 PNG；
8. 最后发布 `baseline_manifest.json`。

输出目录：

```text
BASELINE/
├── images
├── image_pairs_SBAS
├── baseline_select_SBAS
├── baseline_select_SBAS.png
├── baseline_manifest.json
└── provenance.json
```

`SLC_tab`、`Berp_SC` 和 `itab_SC` 是临时文件，不进入正式结果。

### 5.2 干涉图生成

1. 同时校验注册栈和基线清单的来源摘要、参考日期、极化与网络表；
2. 每个日期只生成一次 MLI，不在不同干涉对之间重复计算；
3. 按网络表顺序逐对执行：
   `create_offset → SLC_intf → base_init → base_perp → ph_slope_base →`
   `phase_sim_orb → sub_phase → cc_wave`；
4. 全部 MLI 完成后生成 `ave_mli`；
5. 快视图属于辅助产物。快视图失败记录 warning，但不删除已经验证通过的科学
   产物；核心 GAMMA 命令失败则本阶段失败；
6. 全部干涉对通过后发布 `interferogram_manifest.json`。

输出目录不沿用含义模糊的旧 `project/PRODUCT`：

```text
INTERFEROGRAM/
├── mli/
├── pairs/
│   └── YYYYMMDD-YYYYMMDD/
│       ├── pair.int
│       ├── pair.off
│       ├── pair.baseline
│       ├── pair.int.flt
│       ├── pair.sim.topo.unw
│       ├── pair.tflt
│       └── pair.cc
├── quicklooks/
├── interferogram_manifest.json
└── provenance.json
```

后续滤波和解缠只读取 `interferogram_manifest.json`，不扫描目录猜测干涉对。

## 6. 进度与日志

进度沿用 PRE 的 `@@GEODESY_PROGRESS` 协议和人类可读终端格式。任务标识分别为：

- `ANALYSIS_GAMMA_BASELINE`
- `ANALYSIS_GAMMA_INTERFEROGRAM`

详细命令输出写入：

```text
PROJECT/LOG/ANALYSIS/GAMMA/BASELINE/<case>/
PROJECT/LOG/ANALYSIS/GAMMA/INTERFEROGRAM/<case>/
```

干涉阶段每个日期和每个干涉对使用独立日志，终端只显示统一进度和失败日志路径。
日志不得包含账号、密码、令牌或其他凭据。

## 7. 重跑、失败与发布

- 输入和参数摘要一致且结果清单完整时，整阶段返回 `skipped`；
- 已有输出目录缺少结果清单、清单损坏或摘要不同，程序停止并说明冲突，不静默
  覆盖；
- 输出先写入同一文件系统中的 staging 目录，所有核心产物检查通过后再原子发布；
- 失败时不发布正式结果，保留独立的 `*.failed-logs-<编号>` 供排错；
- 输入 RSLC、参数文件、基线清单和雷达高程始终只读；
- `--dry-run` 只校验并打印解析后的计划，不建立分析产品。

## 8. 验证

单元测试使用假的 GAMMA runner，不依赖许可证，覆盖：

- CFG 合并顺序、未知参数、越界路径、非法 case 和阈值；
- 注册栈状态、后端、网格类型、极化完整性和缺失文件；
- 三类 `base_calc` 命令及旧脚本等价的网络表解析；
- 基线选择自动出图，以及独立绘图入口的旧 CFG 参数、命令行覆盖和默认命名；
- Sentinel-1 与其他传感器的频谱滤波解析；
- MLI 去重、逐对命令顺序、错误停止、失败日志保留和原子发布；
- 相同输入跳过、不同输入冲突；
- CLI `--dry-run` 和退出码。

集成验证分两层：先在 `envInSAR` 用伪小文件验证安装后的入口和日志，再选择一个
已经完成配准的真实小栈运行。真实验证只处理少量干涉对，将新结果与旧
`2-baseline_select`、`5-product` 的文件尺寸、GAMMA 参数、网络表及关键数值摘要
对照；不重复运行已经验证过的 PRE。

## 9. 完成标准

1. 三个安装后命令可从任意目录使用绝对 CFG 路径运行；
2. CFG 示例包含功能、调用方法、运行示例、参数解释、易错项、结果、日志和完成
   判断；
3. 基线阶段从 PRE 清单生成确定性网络表和基线图，独立入口可在不重算基线的
   情况下重新绘图；
4. 干涉阶段按清单生成全部核心产物，并发布可供滤波阶段读取的清单；
5. 单元测试全部通过，`envInSAR` 安装入口通过，少量真实干涉对完成对照；
6. 不修改 PRE、Adapter 或旧生产脚本，也不声称滤波和解缠已经完成。
