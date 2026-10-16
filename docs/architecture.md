# Analysis Architecture / 分析架构

## Ownership / 职责

The input boundary is registered, analysis-ready sensor data. The output boundary
is scientific raster, interferometric, atmospheric, or time-series products that
can be exported through Data Adapter and rendered through Visualization.

输入为已配准且可分析的数据；输出为科学栅格、干涉、大气或时序结果，再经
Data Adapter 交换格式并由 Visualization 绘制。相干性是常规分析副产品，不是按
火灾场景定义的管线终点。

## F1 migration gates / F1 迁移门槛

1. Remove all imports from the legacy sibling `lib` tree or replace them with an installed package boundary.
2. Package tests must run without adding the GAMMA source tree to `PYTHONPATH`.
3. Numerical and command-contract tests must match the legacy implementation.
4. A real project shadow run must validate the complete existing processing path.
5. Workflow provenance and Adapter export boundaries must be explicit.
6. Keep legacy entry points until compatibility and rollback checks pass.

This repository is not yet the default implementation.

## Current source layout / 当前源码结构

- `common/`：跨工作流的路径限制、统一进度、命令日志和原子发布。
- `insar/common/registered_stack.py`：只读 PRE 的正式 RSLC 栈清单。
- `insar/baseline_selection/common/`：不绑定处理软件的基线读取与绘图。
- `insar/baseline_selection/gamma/`：GAMMA 基线配置、计划、执行和发布。
- `insar/interferogram_generation/gamma/`：GAMMA 干涉配置、跨阶段检查、逐对执行和发布。
- `insar/filtering/`：公共清单、配置、计划与发布；`methods/` 隔离 NL-InSAR、
  GAMMA BM3D 和 GAMMA ADF 的科学实现。
- `insar/unwrapping/gamma/mcf/`：读取一个显式滤波清单，构建掩膜和参考点并执行 MCF。

卫星差异在 PRE 结束前消化；进入 Analysis 后统一消费雷达坐标 RSLC。处理软件差异
则保留在 `gamma/`、未来的 `isce/` 等独立目录，避免混用命令和参数。

## Product boundaries / 产品边界

Analysis 只读取 `registered_stack.json`，不扫描 PRE 文件夹猜测影像。基线阶段发布
`baseline_manifest.json`，干涉阶段发布 `interferogram_manifest.json`。后续滤波与
解缠只读取后一份清单，因此各阶段可以独立检查、重跑和替换。

每个运行同时绑定研究项目根目录和两级大写正式 case 路径，例如
`S1/ASCENDING_128`。`--case main` 中的 `main` 只是配置段选择标签，绝不用于推导
目录身份。项目输入必须留在项目内，Analysis 输出与日志则必须留在正式 case 内；
解析后的符号链接同样接受边界检查。

当前 GAMMA 契约固定使用：

- `PRE/GAMMA/RSLC_SUBSET/registered_stack.json` 作为 Analysis 输入；
- `ANALYSIS/BASELINE_SELECTION/GAMMA/` 与 `ANALYSIS/INTERFEROGRAM_GENERATION/GAMMA/` 作为科学输出；
- `INTERFEROGRAM/MLI/` 与 `INTERFEROGRAM/PAIRS/<日期对>/` 组织自有资产；
- `LOG/ANALYSIS/BASELINE_SELECTION/GAMMA/` 与 `LOG/ANALYSIS/INTERFEROGRAM_GENERATION/GAMMA/` 保存日志。
- `ANALYSIS/FILTERING/<METHOD>/` 与 `LOG/ANALYSIS/FILTERING/<METHOD>/` 按滤波方法
  保存统一产品和日志；不引入 `main`、`test` 或强制 `run_id`。
- `ANALYSIS/UNWRAPPING/GAMMA_MCF/` 只表示当前解缠方法；上游滤波方法记录在清单
  lineage 中，不继续嵌套到目录名。
- `VISUALIZATION/INTERFEROGRAM_GENERATION/GAMMA/`、`VISUALIZATION/FILTERING/<METHOD>/`
  和 `VISUALIZATION/UNWRAPPING/GAMMA_MCF/` 保存对应 Analysis runner 同步生成的
  GAMMA DISP 原生质量检查 BMP；图片按阶段/方法平铺，不建立日期对子目录。

新 writer 只发布 portable schema v2：同一清单拥有的资产使用清单相对路径，跨阶段
引用使用明确命名的项目相对字段。迁移期 reader 仍接受 schema v1。Analysis 只拥有
与科学命令同步生成的 GAMMA DISP 质检图，不依赖 Matplotlib、PyGMT 或
Geodesy-Visualization。Geodesy-Visualization 独立负责地图排版、论文图和其他二次
渲染。以后迁移去趋势、大气改正等阶段时沿用同一阶段自带原生质检图的规则。
