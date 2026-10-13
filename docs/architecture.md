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

卫星差异在 PRE 结束前消化；进入 Analysis 后统一消费雷达坐标 RSLC。处理软件差异
则保留在 `gamma/`、未来的 `isce/` 等独立目录，避免混用命令和参数。

## Product boundaries / 产品边界

Analysis 只读取 `registered_stack.json`，不扫描 PRE 文件夹猜测影像。基线阶段发布
`baseline_manifest.json`，干涉阶段发布 `interferogram_manifest.json`。后续滤波与
解缠只读取后一份清单，因此各阶段可以独立检查、重跑和替换。
