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
