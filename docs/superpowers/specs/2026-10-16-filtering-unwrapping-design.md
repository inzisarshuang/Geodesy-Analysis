# InSAR 滤波与解缠工作流设计

## 1. 目标与范围

本阶段把旧 `GAMMA-InSAR/2-GAMMA-POST/7-obs_prepare` 和
`8-1diff_mcf_NL_ISBAS` 的生产逻辑迁入 `Geodesy-Analysis`，形成正式的滤波与
解缠工作流。新工作流必须消费上一阶段发布的 manifest，不再解析基线表或扫描
旧 `PRODUCT` 目录猜测输入。

本阶段包含：

1. Python NL-InSAR、GAMMA BM3D 和 GAMMA ADF 三种滤波方法；
2. GAMMA MCF 解缠；
3. 方法明确的项目目录、CFG、日志、provenance 和阶段 manifest；
4. 使用 `Gansu_Jishishan_LT1` 的真实干涉对做迁移对照。

本阶段不实现其他解缠算法、大气改正、时序反演或通用可视化。旧脚本保留为迁移
对照和回退入口，直至兼容性验证完成。

## 2. 目录设计原则

目录采用“处理阶段优先、当前方法其次”。不得用顶层 `ANALYSIS/GAMMA` 包住所有
阶段，因为 NL-InSAR 并不是 GAMMA 方法。也不得把全部上游方法逐层编码进下游
目录，否则大气改正、去趋势和时序阶段会产生组合爆炸。

项目数据的标准结构为：

```text
ANALYSIS/
├── BASELINE_SELECTION/
│   └── GAMMA/
├── INTERFEROGRAM_GENERATION/
│   └── GAMMA/
├── FILTERING/
│   ├── NL_INSAR/
│   ├── GAMMA_BM3D/
│   └── GAMMA_ADF/
├── UNWRAPPING/
│   └── GAMMA_MCF/
└── ATMOSPHERIC_CORRECTION/
    └── <METHOD>/
```

`ATMOSPHERIC_CORRECTION` 只定义未来阶段的命名规则，不在本阶段实现。

现有项目目录随本阶段一次性迁移：

```text
ANALYSIS/GAMMA/BASELINE       → ANALYSIS/BASELINE_SELECTION/GAMMA
ANALYSIS/GAMMA/INTERFEROGRAM  → ANALYSIS/INTERFEROGRAM_GENERATION/GAMMA
```

相关项目 CFG、日志路径和 manifest 引用同步更新。仓库工作流不兼容性扫描旧目录；
旧项目如需继续运行，应先执行明确的目录迁移或继续使用旧入口。

标准目录不引入 `main`、`test` 或统一 `run_id`。`output_dir` 是可选参数：用户
没有填写时，程序从输入 manifest 向上定位当前案例的 `ANALYSIS` 目录，再根据
处理阶段和所选方法生成同级标准目录；用户显式填写时，以手动指定的目录为准。
自动映射为：

```text
nl_insar    → ANALYSIS/FILTERING/NL_INSAR
gamma_bm3d  → ANALYSIS/FILTERING/GAMMA_BM3D
gamma_adf   → ANALYSIS/FILTERING/GAMMA_ADF
gamma_mcf   → ANALYSIS/UNWRAPPING/GAMMA_MCF
```

例如输入位于
`S1/ASCENDING_128/ANALYSIS/INTERFEROGRAM_GENERATION/GAMMA/interferogram_manifest.json`，
NL-InSAR 默认输出就是 `S1/ASCENDING_128/ANALYSIS/FILTERING/NL_INSAR`。如果
输入 manifest 的祖先目录中没有标准 `ANALYSIS` 根，程序不猜测案例位置，必须由
用户显式填写 `output_dir`。

手动路径可以是项目根目录内的相对路径或绝对路径，并接受与自动目录不同的名称，
用于保留同一方法的多组输入或参数结果；路径仍必须通过项目根目录边界检查。框架
不会自动增加运行编号或额外目录层级。无论输出目录如何产生，manifest 都要记录
其直接上游 manifest、输入摘要、方法和参数，因此完整处理谱系由 manifest 串联，
而不是由路径推断。

## 3. 源码结构

源码同样按阶段组织，在阶段内部再区分实现来源：

```text
src/geodesy_analysis/insar/
├── filtering/
│   ├── __init__.py
│   ├── common/
│   ├── config.py
│   ├── models.py
│   ├── plan.py
│   ├── runner.py
│   ├── publication.py
│   ├── cli.py
│   └── methods/
│       ├── nl_insar.py
│       └── gamma/
│           ├── bm3d.py
│           └── adf.py
└── unwrapping/
    ├── common/
    └── gamma/
        └── mcf/
            ├── config.py
            ├── models.py
            ├── plan.py
            ├── runner.py
            ├── publication.py
            └── cli.py
```

现有 `insar/filtering.py` 转换为 `insar/filtering/` 包，其数值函数移入
`methods/nl_insar.py`，并从 `filtering/__init__.py` 继续导出，保持已有 Python
导入兼容。

滤波阶段共用一套配置、计划、发布和 CLI 协议；方法适配器只负责本方法的参数
检查和计算。GAMMA BM3D、ADF 的命令及默认参数不得进入 NL-InSAR 模块。

## 4. 滤波工作流

### 4.1 输入和选择

滤波 CFG 包含：

- `interferogram_manifest`：状态为 `complete` 的上一阶段 manifest；
- `method`：`nl_insar`、`gamma_bm3d` 或 `gamma_adf`；
- `output_dir`：可选；缺省时按 `method` 自动选择标准目录，显式设置时覆盖默认值；
- 方法专属参数。

工作流只从 `interferogram_manifest.json` 取得干涉对、MLI、宽度、行数和
`pair.tflt` 等资产，不重新读取基线网络，不依赖旧数字 `filt_flag`。文档保留
`0 → nl_insar`、`1 → gamma_bm3d`、`2 → gamma_adf` 的迁移对应关系，但新 CFG
只接受可读方法名。

### 4.2 NL-InSAR

NL-InSAR 复用仓库现有的非局部滤波数值核心，并迁移旧 `nonlocal_main.py` 的批量
执行、配置、门控和 coherent-points 产物。默认行为保持旧脚本：仅在原始相干性
不低于配置阈值的像元采用非局部结果。manifest 记录搜索窗、patch、最小等效视数、
likelihood bandwidth、门控阈值、tile 大小和随机种子。

### 4.3 GAMMA BM3D

BM3D 分支保持旧脚本的科学命令契约：

```text
bm3d <tflt> <width> <filtered> 1 6 10 - 8 16 3 0 - -
cc_wave <original-tflt> <master-mli> <slave-mli> <coherence> <width>
```

其中 block size 等参数进入 CFG，默认值保持旧脚本。相干性仍由原始 `tflt` 与两景
MLI 通过 `cc_wave` 计算，不能静默改成另一种估计器。

### 4.4 GAMMA ADF

ADF 分支保持旧脚本的两次滤波链：

```text
adf <tflt> <temporary-int> <temporary-coh> <width> 0.4 64 5
adf <temporary-int> <filtered-int> <filtered-coh> <width> 0.4 16 5
```

临时文件只存在于 staging 目录，成功后不发布。alpha、窗口和步数进入 CFG，默认
值保持上述生产参数。

### 4.5 滤波产物

三种方法使用统一的对外产品角色：

```text
FILTERING/<METHOD>/
├── pairs/
│   └── YYYYMMDD-YYYYMMDD/
│       ├── pair.tflt.filt
│       └── pair.coh.filt
├── coherent_points/          # 仅 NL-InSAR 有意义
├── coh_ave.coh
├── filtering_manifest.json
└── provenance.json
```

`coh_ave.coh` 对三种方法统一生成，避免下游因方法不同而改变输入协议。旧
`coherence_phase`、`coherence_phase1` 和 `coherence_phase2` 不进入新目录规范。

## 5. GAMMA MCF 解缠工作流

MCF CFG 必须显式提供一个 `filtering_manifest`，因此同一入口可以消费任意一种
滤波方法，而不通过目录名或旧 `filt_flag` 判断来源。工作流检查：

1. manifest 状态、schema、方法和全部 pair 产品；
2. 滤波清单与干涉图清单的 pair 集合、网格尺寸和来源摘要一致；
3. 掩膜尺寸与解缠网格一致；
4. 参考点位于有效掩膜内。

MCF 的 `output_dir` 同样可选：未填写时自动使用
`ANALYSIS/UNWRAPPING/GAMMA_MCF`，显式填写时使用项目根目录内的手动路径。

掩膜支持相干阈值自动生成和显式外部掩膜。参考点支持自动选择与手动指定；自动
模式在最终掩膜内依据平均相干性选择，最终坐标和选择方式写入 provenance。

每个 pair 保持旧脚本的 MCF 命令语义：

```text
mcf <filtered-int> <filtered-coh> <mask> <unwrapped> \
    <width> <mode> 0 0 - - 1 1 - <range-ref> <azimuth-ref>
```

输出结构为：

```text
UNWRAPPING/GAMMA_MCF/
├── mask/
├── pairs/
│   └── YYYYMMDD-YYYYMMDD/
│       └── pair.tflt.filt.unw
├── unwrapping_manifest.json
└── provenance.json
```

`unwrapping_manifest.json` 只指向其直接输入 `filtering_manifest.json` 并保存摘要。
未来的大气改正 manifest 再指向解缠 manifest，由此形成可验证的处理链，而不增加
目录嵌套。

## 6. 配置、命令和日志

项目配置位于：

```text
config/analysis/insar_filtering.cfg
config/analysis/gamma_mcf_unwrapping.cfg
```

滤波配置和入口不带 `gamma`，因为它们同时管理 Python NL-InSAR 与 GAMMA
BM3D/ADF；配置内的 `method` 决定实际适配器。安装后入口为：

```text
geodesy-analysis-filtering
geodesy-analysis-gamma-mcf
```

滤波 CLI 不带 `gamma`，因为它同时管理 Python NL-InSAR。MCF CLI 带 `gamma`，
明确其实现来源。

日志按阶段和当前方法组织：

```text
LOG/ANALYSIS/FILTERING/<METHOD>/
LOG/ANALYSIS/UNWRAPPING/GAMMA_MCF/
```

项目 CFG、日志和生成产品均留在研究项目中，不能写回代码仓库。

## 7. 发布、失败和重跑

- 运行前验证 manifest、文件存在性、文件大小、网格尺寸和外部命令；
- `--dry-run` 只解析配置并验证计划，不生成科学产品；
- 所有结果先写入同一文件系统的 staging 目录，整批成功后原子发布；
- 任一核心 pair 失败时不发布 `status=complete` 的正式 manifest；
- 失败日志保留到独立目录，输入和已发布的上游结果保持只读；
- 现有输出的输入摘要、方法和参数摘要完全相同时返回 `skipped`；
- 输出存在但 manifest 不完整、损坏或摘要不一致时明确报冲突，不静默覆盖；
- 默认输出冲突时不自动生成 `run_id` 或编号目录；同一方法确需保留另一组运行时，
  用户通过 CFG 手动指定新的 `output_dir`。

## 8. 验证策略

只执行与迁移风险相称的验证，不重复测试环境本身。

单元和命令契约测试覆盖：

- 三种方法的配置解析、方法选择和非法组合；
- manifest 串联、来源摘要、pair 集合与网格检查；
- NL-InSAR 已有数值行为和旧导入兼容；
- BM3D、`cc_wave`、两次 ADF 和 MCF 的准确命令顺序；
- 掩膜和自动/手动参考点；
- 原子发布、失败日志、跳过与冲突行为。

真实验证固定使用 `envInSAR`，以
`Gansu_Jishishan_LT1/S1/ASCENDING_128` 的 `20231226-20240131` 干涉对贯通三个
滤波分支和 GAMMA MCF。与旧脚本对照文件尺寸、数据类型、有效像元、相干性摘要和
解缠相位统计；浮点算法允许合理数值误差，不要求文件逐字节一致。

## 9. 完成标准

1. 新目录不再把 NL-InSAR 错误归类到顶层 GAMMA；
2. 三种滤波方法都从同一干涉图 manifest 生成统一产品角色和滤波 manifest；
3. GAMMA MCF 只依据显式滤波 manifest 选择输入；
4. `output_dir` 未设置时从输入 manifest 所属案例的 `ANALYSIS` 根按阶段和方法
   自动生成，手动设置时覆盖默认值；
5. 项目结构不引入强制或自动 `run_id`，完整谱系可由 manifest 逐级追溯；
6. Gansu 的既有基线、干涉图、CFG 和日志同步迁入阶段优先目录；
7. Gansu 单对真实数据完成三种滤波及 MCF 对照；
8. 旧入口仍可回退，且未提前实现大气改正、时序、通用可视化或其他解缠方法。
