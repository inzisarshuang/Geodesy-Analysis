"""
geodesy_analysis.insar.timeseries
==================================

功能概述:
    提供 GAMMA MB 时序结果发现、目标区域抽样、相位到 LOS 形变转换、
    时间基准校正、多轨 CSV 读写、GNSS ENU 读取与 LOS 投影等可复用功能。
    大型 lookup 和 TPF 栅格均通过内存映射按需读取，避免构建完整三维数组；
    不负责 CLI/cfg 合并或最终图件编排。

数据结构:
    ``GammaMBResult``:
        保存一个 ``RESULT_mb_*`` 目录的文件路径、日期、雷达尺寸和波长信息。
    ``TargetTimeSeries``:
        保存多个目标区域的 LOS 时序、有效像元数、单位和时间参考日期。
    ``GNSSTimeSeries``:
        保存完成每日平均和时间归零后的 GNSS 东、北、垂直分量。
    ``SeriesAlignment``:
        保存候选时序与参考时序的偏移量、公共日期和 RMSE。

函数说明:
    ``read_rmli_dates``:
        从 ``RMLI_tab`` 逐行提取影像日期。
    ``discover_gamma_mb_result``:
        检查 MB 结果目录并建立 TPF、基线网络与日期之间的对应关系。
    ``target_regions_from_config``:
        读取与 PyGMT-Plotter 相同格式的目标区域配置。
    ``phase_to_los_displacement``:
        将解缠相位转换为带符号的 LOS 形变。
    ``temporal_reference_index``:
        根据模式解析时间参考期索引。
    ``apply_temporal_reference``:
        沿指定数组轴减去一个参考期。
    ``extract_target_timeseries``:
        通过 lookup 从全部 TPF 中抽取目标区域稳健统计时序。
    ``write_target_timeseries_csv``:
        将目标时序写为日期按行排列的 CSV。
    ``read_target_timeseries_csv``:
        兼容读取日期行表、多轨长表和旧目标点宽表。
    ``reference_target_timeseries``:
        对目标时序的所有列应用统一时间参考。
    ``read_gnss_timeseries``:
        读取 CSV/Excel GNSS 表、执行每日平均、单位转换和时间归零。
    ``project_enu_to_los``:
        按卫星航向角和入射角将 ENU 形变投影到 LOS。
    ``moving_mean_outlier_mask``:
        使用滑动均值和局部标准差识别 GNSS 粗差。
    ``align_series_on_common_dates``:
        使用公共日期对齐两条时序并计算 RMSE。
"""

from __future__ import annotations

import csv
import re
import warnings
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Mapping, Optional, Sequence, Tuple

import numpy as np

from insar_data_adapter import (
    gamma_par_shape,
    radar_indices_from_lookup,
    read_binary_raster,
    read_complex_binary_raster,
    read_gamma_par_value,
)

from geodesy_analysis.insar.network import read_interferogram_pairs
from geodesy_analysis.io import atomic_output_path


DATE_PATTERN = re.compile(r"(?<!\d)(\d{8})(?!\d)")
TPF_INDEX_PATTERN = re.compile(r"TS_tpf_(\d+)\.tpf$")
LIGHT_SPEED_M_S = 299_792_458.0
UNIT_SCALE = {"m": 1.0, "cm": 100.0, "mm": 1000.0}


@dataclass(frozen=True)
class GammaMBResult:
    """
    GAMMA MB 结果目录的路径和元数据。

    字段:
        result_dir:
            ``RESULT_mb_*`` 目录。
        reference_date:
            用于命名 DEM 参数、MLI 参数和 lookup 的参考影像日期。
        radar_par_file, geo_par_file:
            雷达网格和地理网格 GAMMA 参数文件。
        lookup_file, mask_file:
            地理网格到雷达网格的 lookup，以及可选雷达掩膜。
        baseline_file, rmli_tab_file:
            实际解算基线网络和全部 RMLI 列表。
        tpf_files, dates:
            按时期顺序排列的 TPF 文件及其 ``YYYYMMDD`` 日期。
        radar_shape:
            雷达网格 ``(行数, 列数)``。
        radar_frequency_hz:
            雷达载频，单位 Hz。
    """

    result_dir: Path
    reference_date: str
    radar_par_file: Path
    geo_par_file: Path
    lookup_file: Path
    mask_file: Optional[Path]
    baseline_file: Optional[Path]
    rmli_tab_file: Path
    tpf_files: Tuple[Path, ...]
    dates: Tuple[str, ...]
    radar_shape: Tuple[int, int]
    radar_frequency_hz: float

    @property
    def wavelength_m(self) -> float:
        """返回由光速和雷达载频计算的波长，单位为米。"""
        return LIGHT_SPEED_M_S / self.radar_frequency_hz


@dataclass(frozen=True)
class TargetTimeSeries:
    """
    目标区域 LOS 形变时序。

    字段:
        dates:
            与数组行一一对应的 ``YYYYMMDD`` 日期。
        values:
            ``目标名称 -> 一维 LOS 时序`` 映射。
        pixel_counts:
            每个目标区域参与统计的有效 SAR 像元数。
        unit:
            形变单位，支持 ``m``、``cm`` 或 ``mm``。
        reference_date:
            已减去的时间参考期；未重新归零时为 ``None``。
    """

    dates: Tuple[str, ...]
    values: Mapping[str, np.ndarray]
    pixel_counts: Mapping[str, int]
    unit: str
    reference_date: Optional[str]


@dataclass(frozen=True)
class GNSSTimeSeries:
    """
    采用明确 ENU 顺序的 GNSS 日尺度形变时序。

    字段:
        dates:
            每日观测日期。
        east, north, up:
            东、北、垂直三个方向的形变分量。
        unit:
            分量单位。
        reference_date:
            ENU 三个分量共同使用的时间参考日期。
    """

    dates: Tuple[str, ...]
    east: np.ndarray
    north: np.ndarray
    up: np.ndarray
    unit: str
    reference_date: Optional[str]


@dataclass(frozen=True)
class SeriesAlignment:
    """
    候选时序相对于参考时序的对齐结果。

    字段:
        candidate_values:
            加入常量偏移后的完整候选时序。
        offset:
            应用于候选时序的常量偏移。
        common_dates:
            两条时序中具有有限值的公共日期。
        reference_common, candidate_common:
            公共日期上的配对值。
        rmse:
            公共日期配对值的均方根误差。
    """

    candidate_values: np.ndarray
    offset: float
    common_dates: Tuple[str, ...]
    reference_common: np.ndarray
    candidate_common: np.ndarray
    rmse: float


def _find_one(path: Path, pattern: str, description: str) -> Path:
    """在目录中查找唯一匹配文件；匹配数量不为一时抛出异常。"""
    matches = sorted(path.glob(pattern))
    if len(matches) != 1:
        raise ValueError(
            f"expected one {description} in {path}, found {len(matches)}: {matches}"
        )
    return matches[0]


def _tpf_index(path: Path) -> int:
    """从 ``TS_tpf_NNN.tpf`` 文件名解析整数时期编号。"""
    match = TPF_INDEX_PATTERN.search(path.name)
    if match is None:
        raise ValueError(f"invalid TPF filename: {path.name}")
    return int(match.group(1))


def read_rmli_dates(path: str | Path) -> Tuple[str, ...]:
    """
    从 ``RMLI_tab`` 每行第一个路径中提取影像日期。

    参数:
        path:
            ``RMLI_tab`` 文件路径。

    返回:
        dates:
            按文件行顺序排列的 ``YYYYMMDD`` 日期元组。

    说明:
        空行和注释行会被忽略；无法解析日期、没有有效日期或日期重复时抛出异常。
    """
    dates = []
    with Path(path).open("r", encoding="utf-8", errors="replace") as stream:
        for raw_line in stream:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            match = DATE_PATTERN.search(Path(line.split()[0]).name)
            if match is None:
                raise ValueError(f"cannot parse acquisition date from RMLI_tab row: {line}")
            dates.append(match.group(1))
    if not dates:
        raise ValueError(f"no acquisition dates found in {path}")
    if len(set(dates)) != len(dates):
        raise ValueError(f"duplicate acquisition dates found in {path}")
    return tuple(dates)


def discover_gamma_mb_result(
    result_dir: str | Path,
    reference_date: Optional[str] = None,
    tpf_subdir: str = "TS_TPF_DIFF",
    mask_file: Optional[str | Path] = None,
) -> GammaMBResult:
    """
    发现并校验一个 GAMMA ``RESULT_mb_*`` 目录的标准时序文件。

    参数:
        result_dir:
            MB 结果目录。
        reference_date:
            可选参考影像日期。未提供时从唯一的 ``*.dem.cropped.par`` 推断。
        tpf_subdir:
            TPF 时序子目录名称，默认 ``TS_TPF_DIFF``。
        mask_file:
            可选雷达网格掩膜。未提供时自动使用目录中的 ``final.mask.bin``。

    返回:
        result:
            包含路径、日期、网格尺寸、载频和波长信息的 ``GammaMBResult``。

    说明:
        TPF 日期优先由唯一的 ``baseline_scelect*`` 或 ``shortbaseline*``
        中的实际网络日期确定。这样可排除存在于 ``RMLI_tab``、但未进入最终
        解算网络的影像，避免按 RMLI 行数简单截断造成时期错位。
    """
    root = Path(result_dir).expanduser().resolve()
    if not root.is_dir():
        raise NotADirectoryError(f"GAMMA MB result directory not found: {root}")

    if reference_date is None:
        geo_par = _find_one(root, "*.dem.cropped.par", "geographic DEM parameter file")
        match = DATE_PATTERN.search(geo_par.name)
        if match is None:
            raise ValueError(f"cannot infer reference date from {geo_par.name}")
        reference_date = match.group(1)
    else:
        reference_date = str(reference_date).replace("-", "")
        geo_par = root / f"{reference_date}.dem.cropped.par"
    radar_par = root / f"{reference_date}.mli.par"
    lookup = root / f"{reference_date}.lookup_table_final"
    rmli_tab = root / "RMLI_tab"
    for required in (geo_par, radar_par, lookup, rmli_tab):
        if not required.exists():
            raise FileNotFoundError(f"required GAMMA MB file not found: {required}")

    tpf_dir = root / tpf_subdir
    tpf_files = tuple(sorted(tpf_dir.glob("TS_tpf_*.tpf"), key=_tpf_index))
    if not tpf_files:
        raise FileNotFoundError(f"no TS_tpf_*.tpf files found in {tpf_dir}")
    indexes = [_tpf_index(path) for path in tpf_files]
    if indexes != list(range(indexes[0], indexes[0] + len(indexes))):
        raise ValueError(f"TPF sequence is not contiguous in {tpf_dir}")

    rmli_dates = read_rmli_dates(rmli_tab)
    baseline_candidates = sorted(root.glob("baseline_scelect*"))
    if not baseline_candidates:
        baseline_candidates = sorted(root.glob("shortbaseline*"))
    baseline_file = baseline_candidates[0] if len(baseline_candidates) == 1 else None
    network_dates: Tuple[str, ...] = ()
    if baseline_file is not None:
        pairs = read_interferogram_pairs(str(baseline_file))
        network_dates = tuple(
            sorted({date for pair in pairs for date in pair.split("-")})
        )

    if len(network_dates) == len(tpf_files):
        missing_from_rmli = sorted(set(network_dates) - set(rmli_dates))
        if missing_from_rmli:
            raise ValueError(
                f"baseline dates are absent from RMLI_tab in {root}: {missing_from_rmli}"
            )
        dates = network_dates
        excluded = tuple(date for date in rmli_dates if date not in set(network_dates))
        if excluded:
            warnings.warn(
                f"RMLI_tab dates excluded from the solved baseline network: {excluded}"
            )
    elif len(rmli_dates) == len(tpf_files):
        dates = rmli_dates
    elif len(rmli_dates) < len(tpf_files):
        raise ValueError(
            f"RMLI dates ({len(rmli_dates)}) are fewer than TPF files "
            f"({len(tpf_files)}) in {root}"
        )
    else:
        raise ValueError(
            f"cannot map {len(tpf_files)} TPF files to dates: RMLI_tab has "
            f"{len(rmli_dates)} dates and baseline network has {len(network_dates)} "
            f"unique dates in {root}"
        )

    if mask_file is None:
        default_mask = root / "final.mask.bin"
        resolved_mask = default_mask if default_mask.exists() else None
    else:
        resolved_mask = Path(mask_file).expanduser().resolve()
        if not resolved_mask.exists():
            raise FileNotFoundError(f"SAR mask file not found: {resolved_mask}")

    radar_shape = gamma_par_shape(str(radar_par))
    frequency = read_gamma_par_value(str(radar_par), "radar_frequency:")
    if frequency <= 0:
        raise ValueError(f"invalid radar frequency in {radar_par}: {frequency}")
    return GammaMBResult(
        result_dir=root,
        reference_date=reference_date,
        radar_par_file=radar_par,
        geo_par_file=geo_par,
        lookup_file=lookup,
        mask_file=resolved_mask,
        baseline_file=baseline_file,
        rmli_tab_file=rmli_tab,
        tpf_files=tpf_files,
        dates=dates,
        radar_shape=radar_shape,
        radar_frequency_hz=frequency,
    )


def target_regions_from_config(
    config: Mapping[str, str],
) -> Dict[str, Tuple[float, float, float, float]]:
    """
    从配置字典读取与 PyGMT-Plotter 共用的目标区域。

    参数:
        config:
            key-value 配置字典。需要包含 ``target_regions``，以及每个目标的
            ``target_<名称>_west/east/south/north``。

    返回:
        regions:
            ``目标名称 -> (西, 东, 南, 北)`` 的有序字典。
    """
    labels = [
        value.strip()
        for value in config.get("target_regions", "").replace(";", ",").split(",")
        if value.strip()
    ]
    if not labels:
        raise ValueError("target_regions must contain at least one target label")

    regions: Dict[str, Tuple[float, float, float, float]] = {}
    for label in labels:
        keys = [
            f"target_{label}_west",
            f"target_{label}_east",
            f"target_{label}_south",
            f"target_{label}_north",
        ]
        missing = [key for key in keys if key not in config]
        if missing:
            raise ValueError(f"missing target bounds for {label}: {missing}")
        regions[label] = tuple(float(config[key]) for key in keys)
    return regions


def phase_to_los_displacement(
    phase: np.ndarray | float,
    wavelength_m: float,
    unit: str = "mm",
) -> np.ndarray:
    """
    将解缠相位转换为带符号的 LOS 形变。

    参数:
        phase:
            相位标量或数组，单位为弧度。
        wavelength_m:
            雷达波长，单位为米。
        unit:
            输出单位，可选 ``m``、``cm`` 或 ``mm``。

    返回:
        displacement:
            与输入形状一致的 LOS 形变数组。

    说明:
        使用 ``phase * wavelength / (-4*pi)``。该符号约定与本模块
        ``project_enu_to_los`` 的朝向卫星为正保持一致。
    """
    unit = unit.lower()
    if unit not in UNIT_SCALE:
        raise ValueError("unit must be 'm', 'cm', or 'mm'")
    return (
        np.asarray(phase, dtype=np.float64)
        * float(wavelength_m)
        / (-4.0 * np.pi)
        * UNIT_SCALE[unit]
    )


def temporal_reference_index(
    dates: Sequence[str],
    mode: str = "first",
    reference_date: Optional[str] = None,
    reference_index: Optional[int] = None,
) -> Optional[int]:
    """
    根据日期、模式或显式索引解析时间参考期。

    参数:
        dates:
            时序日期，允许 ``YYYYMMDD`` 或含连字符格式。
        mode:
            ``none``、``first``、``date`` 或 ``index``。
        reference_date:
            ``date`` 模式使用的参考日期。提供该参数时会自动采用 ``date`` 模式。
        reference_index:
            ``index`` 模式使用的数组索引，支持 Python 负索引。

    返回:
        index:
            参考期索引；``none`` 模式返回 ``None``。

    说明:
        ``first`` 表示日期最早的时期，不假定输入数组已经按时间排序。
    """
    normalized = tuple(str(date).replace("-", "") for date in dates)
    mode = mode.strip().lower()
    if reference_date is not None:
        mode = "date"
    if reference_index is not None:
        mode = "index"
    if mode == "none":
        return None
    if mode == "first":
        return min(range(len(normalized)), key=normalized.__getitem__)
    if mode == "date":
        wanted = str(reference_date).replace("-", "")
        if wanted not in normalized:
            raise ValueError(f"temporal reference date {wanted} is not in the time series")
        return normalized.index(wanted)
    if mode == "index":
        index = int(reference_index)
        if index < 0:
            index += len(normalized)
        if not 0 <= index < len(normalized):
            raise IndexError(f"temporal reference index {reference_index} is out of range")
        return index
    raise ValueError("temporal reference mode must be 'none', 'first', 'date', or 'index'")


def apply_temporal_reference(
    values: np.ndarray,
    dates: Sequence[str],
    mode: str = "first",
    reference_date: Optional[str] = None,
    reference_index: Optional[int] = None,
    axis: int = 0,
) -> Tuple[np.ndarray, Optional[str]]:
    """
    沿指定轴减去一个时间参考期。

    参数:
        values:
            任意维数值数组。
        dates:
            与 ``axis`` 轴长度一致的时期日期。
        mode, reference_date, reference_index:
            传递给 ``temporal_reference_index`` 的时间参考设置。
        axis:
            时期所在数组轴，默认第 0 轴。

    返回:
        referenced:
            完成时间归零后的 float64 数组。
        applied_date:
            实际使用的参考日期；未归零时为 ``None``。
    """
    array = np.asarray(values, dtype=np.float64)
    if array.shape[axis] != len(dates):
        raise ValueError(
            f"date count {len(dates)} does not match values axis length {array.shape[axis]}"
        )
    index = temporal_reference_index(dates, mode, reference_date, reference_index)
    if index is None:
        return array.copy(), None
    reference = np.take(array, index, axis=axis)
    return array - np.expand_dims(reference, axis=axis), str(dates[index]).replace("-", "")


def extract_target_timeseries(
    result: GammaMBResult,
    target_regions: Mapping[str, Tuple[float, float, float, float]],
    unit: str = "mm",
    statistic: str = "median",
    region_shape: str = "ellipse",
    max_pixels_per_target: Optional[int] = 1500,
    temporal_reference: str = "first",
    temporal_reference_date: Optional[str] = None,
    temporal_reference_index_value: Optional[int] = None,
    invalid_abs_max: float = 1.0e5,
) -> TargetTimeSeries:
    """
    从全部 TPF 时期抽取多个目标区域的 LOS 形变时序。

    参数:
        result:
            ``discover_gamma_mb_result`` 返回的 MB 结果描述。
        target_regions:
            ``目标名称 -> (西, 东, 南, 北)`` 映射。
        unit:
            LOS 输出单位，可选 ``m``、``cm`` 或 ``mm``。
        statistic:
            区域统计方式，可选 ``median`` 或 ``mean``。
        region_shape:
            在地理网格内使用 ``ellipse`` 或 ``rectangle`` 选区。
        max_pixels_per_target:
            每个区域最多抽取的 SAR 像元数；``None`` 表示不限制。
        temporal_reference:
            时间参考模式。
        temporal_reference_date:
            指定参考日期。
        temporal_reference_index_value:
            指定参考时期索引。
        invalid_abs_max:
            相位绝对值有效上限，用于剔除异常填充值。

    返回:
        series:
            包含日期、各目标 LOS 时序、像元数量、单位和参考日期的结果。

    说明:
        lookup、掩膜和每期 TPF 均采用内存映射。全部目标像元索引先合并排序，
        每个时期只执行一次离散读取，再按目标区域分组统计。
    """
    statistic = statistic.strip().lower()
    if statistic not in {"median", "mean"}:
        raise ValueError("statistic must be 'median' or 'mean'")

    lookup_shape = gamma_par_shape(str(result.geo_par_file))
    lookup = read_complex_binary_raster(
        str(result.lookup_file), lookup_shape, memmap=True
    )
    radar_mask = None
    if result.mask_file is not None:
        radar_mask = read_binary_raster(
            str(result.mask_file),
            result.radar_shape,
            dtype="uint8",
            memmap=True,
        )

    target_indices = {
        name: radar_indices_from_lookup(
            lookup,
            str(result.geo_par_file),
            bounds,
            result.radar_shape,
            radar_mask=radar_mask,
            region_shape=region_shape,
            max_pixels=max_pixels_per_target,
        )
        for name, bounds in target_regions.items()
    }
    empty = [name for name, indices in target_indices.items() if indices.size == 0]
    if empty:
        raise ValueError(f"target regions contain no valid SAR pixels: {empty}")

    all_indices = np.unique(np.concatenate(list(target_indices.values())))
    target_positions = {
        name: np.searchsorted(all_indices, indices)
        for name, indices in target_indices.items()
    }
    phase_values = np.full(
        (len(result.tpf_files), len(target_indices)), np.nan, dtype=np.float64
    )
    reducer = np.nanmedian if statistic == "median" else np.nanmean
    for epoch, tpf_file in enumerate(result.tpf_files):
        phase = read_binary_raster(
            str(tpf_file), result.radar_shape, memmap=True
        ).reshape(-1)
        sampled = np.asarray(phase[all_indices], dtype=np.float64)
        for target_index, name in enumerate(target_indices):
            values = sampled[target_positions[name]]
            valid = np.isfinite(values) & (np.abs(values) < invalid_abs_max)
            if np.any(valid):
                phase_values[epoch, target_index] = reducer(values[valid])

    displacement = phase_to_los_displacement(
        phase_values, wavelength_m=result.wavelength_m, unit=unit
    )
    referenced, applied_date = apply_temporal_reference(
        displacement,
        result.dates,
        mode=temporal_reference,
        reference_date=temporal_reference_date,
        reference_index=temporal_reference_index_value,
        axis=0,
    )
    series = {
        name: referenced[:, index].copy()
        for index, name in enumerate(target_indices)
    }
    return TargetTimeSeries(
        dates=result.dates,
        values=series,
        pixel_counts={name: int(indices.size) for name, indices in target_indices.items()},
        unit=unit.lower(),
        reference_date=applied_date,
    )


def write_target_timeseries_csv(series: TargetTimeSeries, output_file: str | Path) -> Path:
    """
    将目标 LOS 时序写为日期按行排列的 CSV。

    参数:
        series:
            目标时序对象。
        output_file:
            输出 CSV 路径。

    返回:
        output:
            展开并解析后的实际输出路径。

    输出格式:
        第一列为 ``date``，其余列按 ``series.values`` 顺序保存各目标值。
    """
    output = Path(output_file).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    labels = list(series.values)
    with atomic_output_path(output) as temporary:
        with temporary.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream)
            writer.writerow(["date", *labels])
            for epoch, date in enumerate(series.dates):
                writer.writerow(
                    [date, *[f"{series.values[label][epoch]:.9g}" for label in labels]]
                )
    return output


def read_target_timeseries_csv(
    input_file: str | Path,
    unit: str = "mm",
    track: Optional[str] = None,
) -> TargetTimeSeries:
    """
    兼容读取三种目标时序 CSV。

    参数:
        input_file:
            输入 CSV 路径。
        unit:
            输入形变值的单位标签。
        track:
            多轨长表中的轨道名称。文件只含一个轨道时可省略。

    返回:
        series:
            统一转换为日期按时期排列的 ``TargetTimeSeries``。

    支持格式:
        - ``date,P1,P2,...``
        - ``track,date,P1,P2,...``
        - ``target,...,d20240101,d20240113,...``

    说明:
        CSV 本身不执行单位换算，``unit`` 仅记录输入数值的物理单位。
    """
    path = Path(input_file).expanduser().resolve()
    with path.open("r", newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        fieldnames = reader.fieldnames or []
        rows = list(reader)
    if not rows:
        raise ValueError(f"target time-series CSV is empty: {path}")

    if fieldnames[:1] == ["date"] or fieldnames[:2] == ["track", "date"]:
        if fieldnames[0] == "track":
            available = list(dict.fromkeys(row["track"] for row in rows))
            if track is None:
                if len(available) != 1:
                    raise ValueError(
                        f"{path} contains tracks {available}; select one with track="
                    )
                track = available[0]
            rows = [row for row in rows if row["track"] == str(track)]
            if not rows:
                raise ValueError(f"track {track} not found in {path}")
            value_fields = fieldnames[2:]
        else:
            value_fields = fieldnames[1:]
        dates = tuple(_normalize_date_text(row["date"]) for row in rows)
        values = {
            label: np.asarray([float(row[label]) for row in rows], dtype=np.float64)
            for label in value_fields
        }
    elif "target" in fieldnames:
        date_fields = [
            field for field in fieldnames if re.fullmatch(r"d\d{8}", field or "")
        ]
        if not date_fields:
            raise ValueError(f"no dYYYYMMDD columns found in legacy CSV: {path}")
        dates = tuple(field[1:] for field in date_fields)
        values = {
            row["target"]: np.asarray(
                [float(row[field]) for field in date_fields], dtype=np.float64
            )
            for row in rows
        }
    else:
        raise ValueError(f"unsupported target time-series CSV layout: {fieldnames}")

    if len(set(dates)) != len(dates):
        raise ValueError(f"duplicate dates found in {path}")
    return TargetTimeSeries(
        dates=dates,
        values=values,
        pixel_counts={label: 0 for label in values},
        unit=unit.lower(),
        reference_date=None,
    )


def reference_target_timeseries(
    series: TargetTimeSeries,
    mode: str = "first",
    reference_date: Optional[str] = None,
    reference_index: Optional[int] = None,
) -> TargetTimeSeries:
    """
    对目标时序的所有目标列应用同一个时间参考期。

    参数:
        series:
            输入目标时序。
        mode:
            时间参考模式。
        reference_date:
            可选参考日期。
        reference_index:
            可选参考时期索引。

    返回:
        referenced_series:
            日期、单位和像元统计不变，所有目标列完成归零的新对象。
    """
    labels = list(series.values)
    matrix = np.column_stack([series.values[label] for label in labels])
    referenced, applied_date = apply_temporal_reference(
        matrix,
        series.dates,
        mode=mode,
        reference_date=reference_date,
        reference_index=reference_index,
        axis=0,
    )
    return TargetTimeSeries(
        dates=series.dates,
        values={
            label: referenced[:, index].copy()
            for index, label in enumerate(labels)
        },
        pixel_counts=series.pixel_counts,
        unit=series.unit,
        reference_date=applied_date,
    )


def _normalize_date_text(value) -> str:
    """将常见表格日期值标准化为 ``YYYYMMDD``，无效日期抛出异常。"""
    if isinstance(value, datetime):
        return value.strftime("%Y%m%d")
    text = str(value).strip()
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    digits = re.sub(r"\D", "", text)
    if len(digits) >= 8:
        candidate = digits[:8]
        datetime.strptime(candidate, "%Y%m%d")
        return candidate
    raise ValueError(f"cannot parse date value: {value!r}")


def _try_normalize_date_text(value) -> Optional[str]:
    """尝试标准化日期；表格单元无效时返回 ``None``。"""
    try:
        return _normalize_date_text(value)
    except (TypeError, ValueError):
        return None


def _table_column(frame, selector: str | int, role: str):
    """按列名或零基整数索引选择 Pandas 表格列。"""
    if isinstance(selector, int) or str(selector).strip().lstrip("-").isdigit():
        index = int(selector)
        if index < 0:
            index += frame.shape[1]
        if not 0 <= index < frame.shape[1]:
            raise IndexError(f"{role} column index {selector} is out of range")
        return frame.iloc[:, index]
    name = str(selector)
    if name not in frame.columns:
        raise KeyError(f"{role} column {name!r} not found; columns={list(frame.columns)}")
    return frame[name]


def read_gnss_timeseries(
    input_file: str | Path,
    date_column: str | int,
    east_column: str | int,
    north_column: str | int,
    up_column: str | int,
    input_unit: str = "mm",
    output_unit: str = "mm",
    date_format: Optional[str] = None,
    sheet_name: str | int = 0,
    daily_average: bool = True,
    temporal_reference: str = "first",
    temporal_reference_date: Optional[str] = None,
) -> GNSSTimeSeries:
    """
    读取 GNSS 表格并生成日尺度 ENU 形变时序。

    参数:
        input_file:
            CSV、TSV、TXT、XLS、XLSX 或 XLSM 文件。
        date_column:
            日期列名或零基列索引。
        east_column, north_column, up_column:
            东、北、垂直分量的列名或零基列索引。三个方向必须显式指定，
            避免旧 MATLAB 代码中 E/N 列交换的问题。
        input_unit:
            原始 ENU 数值单位。
        output_unit:
            输出 ENU 数值单位。
        date_format:
            可选 Pandas 日期格式字符串；未提供时自动提取 ``YYYYMMDD``。
        sheet_name:
            Excel 工作表名称或零基索引。
        daily_average:
            是否对同一天的多次观测取平均。
        temporal_reference:
            ENU 三个分量共同使用的时间参考模式。
        temporal_reference_date:
            可选参考日期。

    返回:
        series:
            按日期排序、完成单位转换和时间归零的 ``GNSSTimeSeries``。

    说明:
        Excel 输入由 Pandas 读取，需要环境安装 ``openpyxl`` 等相应引擎；
        CSV/TSV/TXT 不依赖 Excel 引擎。
    """
    try:
        import pandas as pd
    except ImportError as exc:
        raise ImportError("pandas is required to read GNSS tables") from exc

    path = Path(input_file).expanduser().resolve()
    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xls", ".xlsm"}:
        try:
            frame = pd.read_excel(path, sheet_name=sheet_name)
        except ImportError as exc:
            raise ImportError(
                "Excel GNSS input requires an Excel engine such as openpyxl; "
                "CSV input works without it"
            ) from exc
    elif suffix in {".csv", ".txt", ".tsv"}:
        separator = "\t" if suffix == ".tsv" else None
        frame = pd.read_csv(path, sep=separator, engine="python")
    else:
        raise ValueError("GNSS input must be CSV, TSV, TXT, XLS, XLSX, or XLSM")

    date_source = _table_column(frame, date_column, "date")
    if date_format:
        parsed_dates = pd.to_datetime(date_source.astype(str), format=date_format, errors="coerce")
    else:
        date_text = date_source.map(
            lambda value: _try_normalize_date_text(value) if not pd.isna(value) else None
        )
        parsed_dates = pd.to_datetime(date_text, format="%Y%m%d", errors="coerce")

    components = {
        "east": pd.to_numeric(_table_column(frame, east_column, "east"), errors="coerce"),
        "north": pd.to_numeric(_table_column(frame, north_column, "north"), errors="coerce"),
        "up": pd.to_numeric(_table_column(frame, up_column, "up"), errors="coerce"),
    }
    clean = pd.DataFrame({"date": parsed_dates, **components}).dropna()
    if clean.empty:
        raise ValueError(f"no valid GNSS rows parsed from {path}")
    clean["date"] = clean["date"].dt.normalize()
    if daily_average:
        clean = clean.groupby("date", as_index=False)[["east", "north", "up"]].mean()
    clean = clean.sort_values("date")

    input_unit = input_unit.lower()
    output_unit = output_unit.lower()
    if input_unit not in UNIT_SCALE or output_unit not in UNIT_SCALE:
        raise ValueError("GNSS units must be 'm', 'cm', or 'mm'")
    scale = UNIT_SCALE[output_unit] / UNIT_SCALE[input_unit]
    enu = clean[["east", "north", "up"]].to_numpy(dtype=np.float64) * scale
    dates = tuple(value.strftime("%Y%m%d") for value in clean["date"])
    referenced, applied_date = apply_temporal_reference(
        enu,
        dates,
        mode=temporal_reference,
        reference_date=temporal_reference_date,
        axis=0,
    )
    return GNSSTimeSeries(
        dates=dates,
        east=referenced[:, 0],
        north=referenced[:, 1],
        up=referenced[:, 2],
        unit=output_unit,
        reference_date=applied_date,
    )


def project_enu_to_los(
    east: np.ndarray,
    north: np.ndarray,
    up: np.ndarray,
    incidence_deg: float,
    heading_deg: float,
) -> np.ndarray:
    """
    将 GNSS ENU 形变投影到地面指向卫星的 LOS 方向。

    参数:
        east, north, up:
            形状一致的东、北、垂直形变数组，三者单位必须相同。
        incidence_deg:
            雷达入射角，单位为度。
        heading_deg:
            卫星飞行航向角，从正北顺时针为正，单位为度。

    返回:
        los:
            与输入数组形状和单位一致的 LOS 形变。

    符号约定:
        LOS 正值表示朝向卫星，与迁移的 MATLAB 公式及
        ``phase * wavelength / (-4*pi)`` 保持一致。
    """
    east = np.asarray(east, dtype=np.float64)
    north = np.asarray(north, dtype=np.float64)
    up = np.asarray(up, dtype=np.float64)
    if east.shape != north.shape or east.shape != up.shape:
        raise ValueError("east, north, and up arrays must have identical shapes")
    incidence = np.deg2rad(float(incidence_deg))
    heading = np.deg2rad(float(heading_deg))
    return (
        -np.cos(heading) * np.sin(incidence) * east
        + np.sin(heading) * np.sin(incidence) * north
        + np.cos(incidence) * up
    )


def moving_mean_outlier_mask(
    values: Sequence[float],
    window: int = 25,
    threshold: float = 3.0,
) -> np.ndarray:
    """
    使用中心滑动均值和局部标准差识别一维时序粗差。

    参数:
        values:
            待检查的一维数值序列。
        window:
            中心滑动窗口长度，必须不小于 3。
        threshold:
            允许偏离局部均值的标准差倍数。

    返回:
        keep:
            与输入等长的布尔掩膜；``True`` 表示保留。

    说明:
        非有限值始终标记为不保留。局部有效样本少于 3 时不额外判为粗差。
    """
    array = np.asarray(values, dtype=np.float64)
    if window < 3:
        raise ValueError("outlier window must be at least 3")
    if threshold <= 0:
        raise ValueError("outlier threshold must be positive")
    half = int(window) // 2
    keep = np.isfinite(array)
    for index, value in enumerate(array):
        if not np.isfinite(value):
            continue
        local = array[max(0, index - half) : min(array.size, index + half + 1)]
        local = local[np.isfinite(local)]
        if local.size < 3:
            continue
        standard_deviation = float(np.std(local, ddof=1))
        if standard_deviation > 0:
            keep[index] = abs(value - float(np.mean(local))) <= threshold * standard_deviation
    return keep


def align_series_on_common_dates(
    reference_dates: Sequence[str],
    reference_values: Sequence[float],
    candidate_dates: Sequence[str],
    candidate_values: Sequence[float],
    method: str = "first_common",
) -> SeriesAlignment:
    """
    根据公共日期为候选时序估计常量偏移并计算 RMSE。

    参数:
        reference_dates, reference_values:
            参考时序的日期和值。
        candidate_dates, candidate_values:
            待对齐时序的日期和值。
        method:
            ``first_common`` 使用首个有效公共日期对齐；
            ``mean_common`` 使用全部有效公共日期差值的均值对齐。

    返回:
        alignment:
            包含完整对齐时序、偏移量、有效公共日期、配对值和 RMSE。

    说明:
        只用日期完全相同且两侧均为有限值的观测计算偏移和 RMSE。
    """
    reference_dates = tuple(_normalize_date_text(date) for date in reference_dates)
    candidate_dates = tuple(_normalize_date_text(date) for date in candidate_dates)
    reference_array = np.asarray(reference_values, dtype=np.float64)
    candidate_array = np.asarray(candidate_values, dtype=np.float64)
    if reference_array.size != len(reference_dates):
        raise ValueError("reference dates and values length mismatch")
    if candidate_array.size != len(candidate_dates):
        raise ValueError("candidate dates and values length mismatch")

    reference_lookup = {date: index for index, date in enumerate(reference_dates)}
    candidate_lookup = {date: index for index, date in enumerate(candidate_dates)}
    common_dates = tuple(
        date for date in reference_dates if date in candidate_lookup
    )
    if not common_dates:
        raise ValueError("reference and candidate series have no common dates")
    reference_common = np.asarray(
        [reference_array[reference_lookup[date]] for date in common_dates]
    )
    candidate_common_raw = np.asarray(
        [candidate_array[candidate_lookup[date]] for date in common_dates]
    )
    valid = np.isfinite(reference_common) & np.isfinite(candidate_common_raw)
    if not np.any(valid):
        raise ValueError("common dates contain no finite paired observations")

    method = method.strip().lower()
    if method == "first_common":
        first = int(np.flatnonzero(valid)[0])
        offset = float(reference_common[first] - candidate_common_raw[first])
    elif method == "mean_common":
        offset = float(np.mean(reference_common[valid] - candidate_common_raw[valid]))
    else:
        raise ValueError("alignment method must be 'first_common' or 'mean_common'")

    aligned = candidate_array + offset
    candidate_common = candidate_common_raw + offset
    residual = reference_common[valid] - candidate_common[valid]
    rmse = float(np.sqrt(np.mean(residual**2)))
    return SeriesAlignment(
        candidate_values=aligned,
        offset=offset,
        common_dates=tuple(date for date, is_valid in zip(common_dates, valid) if is_valid),
        reference_common=reference_common[valid],
        candidate_common=candidate_common[valid],
        rmse=rmse,
    )
