# GAMMA 阶段原生快视图设计

**日期：** 2026-10-16  
**状态：** 待用户审阅  
**范围：** Geodesy-Analysis 的干涉图生成、滤波和 GAMMA MCF 解缠，以及
Gansu_Jishishan_LT1 当前案例的快视图补齐

## 1. 目标

恢复旧 `GAMMA-InSAR/2-GAMMA-POST` 的生产语义：一个处理阶段在生成科学栅格后，
立即调用对应的 GAMMA DISP 命令生成质量检查图。用户只运行该阶段已有的 Analysis
命令和 CFG，不再运行第二个 Visualization 命令，也不为相位、相干性或强度图增加
额外 case。

本设计覆盖当前已经迁移完成的三个阶段：

1. GAMMA 差分干涉图与相干性生成；
2. NL-InSAR、GAMMA BM3D 和 GAMMA ADF 滤波；
3. GAMMA MCF 解缠。

去趋势、大气改正、DInSAR、Stacking 和 SBAS 尚未迁入 Geodesy-Analysis，不在本次
实现范围；以后迁移时沿用同一规则。基线网络图不是 GAMMA DISP 原生快视图，本次
不改变其已有归属。

## 2. 旧生产脚本依据

设计保持以下旧脚本行为，而不是重新发明独立绘图流程：

- `5-product` 在 `sub_phase` 和 `cc_wave` 后调用 `rasmph`、`rasdt_pwr`，同时对逐景
  MLI 和 `ave_mli` 调用 `raspwr`；
- `7-obs_prepare` 的 NL-InSAR、BM3D、ADF 分支在每个 pair 完成后立即生成滤波相位
  和滤波相干性 BMP；
- `8-1diff_mcf_NL_ISBAS` 在每个 `mcf` 成功后立即生成解缠相位 BMP；
- 后续旧脚本同样把去趋势、大气改正和形变显示作为各自阶段的一部分。

因此，“计算数据与图片位于不同顶层目录”不等于“计算和快视图使用两个独立执行
流程”。快视图由产生对应科学产品的 Analysis runner 负责。

## 3. 所有权边界

Geodesy-Analysis 拥有两类输出：

1. `ANALYSIS/` 下的科学计算产品、manifest 和 provenance；
2. 同一阶段通过 GAMMA `raspwr`、`rasmph`、`rasdt_pwr` 等命令生成的原生质量检查图。

GAMMA 原生快视图写入案例的 `VISUALIZATION/` 树，但仍由 Analysis 阶段同步生成。
Geodesy-Visualization 继续负责 PyGMT、地图排版、论文图和其他二次渲染，不接管
这些 GAMMA 原生质量检查图。

这项约定是对既有“Analysis 完全不生成任何图像”规则的限定性修正，并取代
`2026-10-14-project-driven-study-layout-design.md` 中关于 GAMMA 原生快视图必须由
Geodesy-Visualization 单独生成的部分。计算目录与项目级 `VISUALIZATION/` 目录仍然
保持分离。

## 4. 配置入口

不新增 `gamma_visualization.cfg`、绘图 CLI 或图片类型 case。三个现有 CFG 的每个
case 增加一个可选目录入口：

```ini
[case:main]
visualization_dir = S1/ASCENDING_128/VISUALIZATION/INTERFEROGRAM_GENERATION/GAMMA
```

```ini
[case:nl_insar]
visualization_dir = S1/ASCENDING_128/VISUALIZATION/FILTERING/NL_INSAR
```

```ini
[case:main]
visualization_dir = S1/ASCENDING_128/VISUALIZATION/UNWRAPPING/GAMMA_MCF
```

`visualization_dir` 未填写时，根据 `case_root`、阶段和方法自动产生上述标准目录；
用户显式填写时使用手动目录。手动目录可以使用项目相对路径或绝对路径，但解析后
必须位于当前案例根目录内，并且不得指向 Analysis 科学输出目录或输入目录。

`case` 继续表示轨道、数据组或滤波方法运行，不表示相位、相干性、强度图等图片
类别。同一方法需要保留另一组输出时，用户可同时手动修改 `output_dir` 和
`visualization_dir`；程序不自动引入 `main`、`test` 或 `run_id`。

快视图默认且始终生成，以保持旧 POST 生产流程。本阶段不增加关闭快视图的配置项。

## 5. 图片目录与命名

Analysis 科学产品继续使用 `pairs/<日期对>/pair.*`，因为一个 pair 拥有多个二进制
产品。快视图面向人工照片浏览器检查，不建立 `pairs/` 或日期对子目录；同一阶段或
方法的图片全部平铺。

### 5.1 干涉图阶段

```text
VISUALIZATION/INTERFEROGRAM_GENERATION/GAMMA/
├── 20231027.mli.bmp
├── 20231226.mli.bmp
├── 20240131.mli.bmp
├── ave_mli.bmp
├── 20231027-20231226.cc.bmp
├── 20231027-20231226.tflt.bmp
├── 20231226-20240131.cc.bmp
└── 20231226-20240131.tflt.bmp
```

强度、差分干涉相位和相干性不再拆分子目录。文件名以获取日期或日期对开头，照片
浏览器按名称排序时可以连续查看。

### 5.2 滤波阶段

```text
VISUALIZATION/FILTERING/
├── NL_INSAR/
│   ├── 20231226-20240131.coh.filt.bmp
│   └── 20231226-20240131.tflt.filt.bmp
├── GAMMA_BM3D/
│   ├── 20231226-20240131.coh.filt.bmp
│   └── 20231226-20240131.tflt.filt.bmp
└── GAMMA_ADF/
    ├── 20231226-20240131.coh.filt.bmp
    └── 20231226-20240131.tflt.filt.bmp
```

每种滤波方法拥有自己的平铺目录，相位和相干性不分开。

### 5.3 MCF 解缠阶段

```text
VISUALIZATION/UNWRAPPING/GAMMA_MCF/
└── 20231226-20240131.tflt.filt.unw.bmp
```

`final.mask.bmp` 同时是 GAMMA `mcf` 的真实计算输入，因此继续保留在
`ANALYSIS/UNWRAPPING/GAMMA_MCF/mask/`，不为展示重复复制。

## 6. GAMMA 命令契约

参数保持旧生产脚本的语义和色表，不改用 Matplotlib 重绘：

```text
raspwr <date-mli> <width> ... <date>.mli.bmp
raspwr <ave-mli> <width> ... ave_mli.bmp
rasmph <pair-tflt> <width> 1 - 1 1 1 .35 rmg.cm <pair>.tflt.bmp
rasdt_pwr <pair-cc> - <width> - - - - - - 2 cc.cm <pair>.cc.bmp
```

滤波阶段继续保留旧分支的显示差异：ADF/BM3D 相干图使用 `ave_mli` 强度背景，
NL-InSAR 的相位图与相干图都不使用强度背景。MCF 使用：

```text
rasdt_pwr <unwrapped> - <width> - - - - - - 2 rmg.cm <pair>.tflt.filt.unw.bmp
```

所有命令与科学计算在 `envInSAR` 中运行，不依赖 `envPlot`。

## 7. Manifest、发布与重跑

每个阶段 manifest 记录：

- `visualization_dir_project_path`；
- 每景 MLI、平均 MLI和每个 pair 对应的项目相对快视图路径；
- 使用的 GAMMA 显示命令及相关显示参数摘要。

新运行只有在科学资产和所有预期快视图均存在且非空后，才能发布
`status=complete`。快视图命令失败时保留失败日志，不把阶段报告为完整。

当前 Gansu manifest 是在“无快视图”规则下生成的。相同输入和科学参数重新运行时，
runner 应识别这种旧完整结果，只补齐缺失的快视图并原子更新 manifest/provenance，
不得重新计算或覆盖已有科学栅格。若科学资产本身不完整或输入摘要不同，仍按现有
冲突规则停止。

快视图写入唯一 staging 目录，全部成功后发布到目标 `visualization_dir`。正式目录
已存在且不属于同一输入时不覆盖；同一输入缺少部分图片时允许安全补齐。manifest
最后原子写入，使其成为计算与快视图共同完成的最终标志。

## 8. Gansu 项目调整

更新以下项目 CFG，显式暴露 `visualization_dir`，便于以后人工修改路径：

```text
S1/ASCENDING_128/config/analysis/gamma_interferogram.cfg
S1/ASCENDING_128/config/analysis/insar_filtering.cfg
S1/ASCENDING_128/config/analysis/gamma_mcf_unwrapping.cfg
```

使用新 runner 对现有真实科学产品执行只补图迁移，生成标准目录：

```text
S1/ASCENDING_128/VISUALIZATION/INTERFEROGRAM_GENERATION/GAMMA/
S1/ASCENDING_128/VISUALIZATION/FILTERING/NL_INSAR/
S1/ASCENDING_128/VISUALIZATION/FILTERING/GAMMA_BM3D/
S1/ASCENDING_128/VISUALIZATION/FILTERING/GAMMA_ADF/
S1/ASCENDING_128/VISUALIZATION/UNWRAPPING/GAMMA_MCF/
```

不删除或重新计算现有 `ANALYSIS/` 科学结果，不移动与本阶段无关的项目文件。

## 9. 文档和测试

仓库文档、示例 CFG 和架构测试同步修正，不再禁止 Analysis 调用 GAMMA DISP 或
写出原生快视图。仍禁止 Analysis 依赖 Matplotlib、PyGMT 或
`geodesy_visualization`。

只执行与本次修改直接相关的验证：

1. 配置默认路径、手动路径和项目边界检查；
2. GAMMA 命令参数和执行顺序；
3. 平铺文件命名，不产生 `pairs/` 快视图目录；
4. manifest 资产记录、缺图失败和旧结果补图；
5. Gansu 单对真实数据在 `envInSAR` 中生成强度、干涉相位、相干性、三种滤波和
   MCF 解缠 BMP，并检查文件存在且非空。

不重复运行无关仓库或环境测试。

## 10. 完成标准

1. 用户运行原有阶段命令即可同时得到科学产品和 GAMMA 原生快视图；
2. 不存在独立 `gamma_visualization.cfg`、绘图 CLI 或图片类型 case；
3. 所有快视图按阶段/方法平铺，强度、相位和相干性位于同一干涉图目录；
4. `visualization_dir` 有合理默认值，并可在每个 case 中手动覆盖；
5. Gansu 当前科学产品不重算，只补齐并登记真实快视图；
6. Geodesy-Analysis 的相关修改合并到 `main` 并推送远端。
