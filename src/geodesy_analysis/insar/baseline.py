"""
geodesy_analysis.insar.baseline
================================

功能概述:
    读取 ``shortbaseline`` 或 ``baseline_select_*`` 文件，求解各 SLC
    相对主影像的垂直基线，并绘制包含 SLC 节点和干涉对连线的
    时空基线网络图。网络解析、基线求解、相干评分和优选属于科学分析；网络图
    是依赖分析状态的处理诊断，不负责通用论文地图或跨领域可视化。

函数说明:
    ``clean_label``:
        清理轨道号或数据标签，使其可安全用于输出文件名。
    ``infer_orbit_label_from_name``:
        从基线文件名中识别轨道方向或相对轨道号。
    ``default_baseline_output``:
        根据基线文件名、轨道标签和输出目录生成默认 PNG 路径。
    ``resolve_baseline_output``:
        合并用户指定的输出文件名与输出目录。
    ``parse_yyyymmdd``:
        将 yyyymmdd 日期整数转换为 ``datetime`` 对象。
    ``read_baseline_file``:
        解析基线文件中的主从影像日期、垂直基线和时间基线。
    ``collect_dates``:
        汇总并排序基线网络中的所有 SLC 日期。
    ``solve_perpendicular_baselines``:
        沿干涉对网络求解各 SLC 相对指定主影像的垂直基线。
    ``plot_baseline_network``:
        绘制时空基线网络并输出 PNG 图像。
    ``build_amplitude_quadtree``:
        按振幅变异系数递归分块，复现 TCP 的自适应四叉树。
    ``estimate_block_coherence``:
        在每个四叉树块内选择同质像元，去趋势后估计样本相干性。
    ``coherence_quality_ratio``:
        计算每幅干涉图中超过相干阈值的块比例。
    ``select_interferogram_network``:
        先以最大相干性生成树保证连通，再按评分补足目标干涉对。
"""

import re
import sys
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

BaselineRow = Tuple[int, int, float, float]


def _matplotlib_modules():
    """Load the optional plotting stack only for a diagnostic figure."""
    import os

    os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt
    from matplotlib.collections import LineCollection

    return mdates, plt, LineCollection


def clean_label(text: str) -> str:
    """
    将轨道号或数据标签转换为可安全用于文件名的字符串。

    参数:
        text:
            用户输入的轨道号或从文件名中提取出的标签。

    返回:
        只保留字母、数字、下划线和短横线的标签；首尾下划线会被删除。
    """
    label = re.sub(r"[^0-9A-Za-z_-]+", "_", str(text).strip())
    return label.strip("_")


def infer_orbit_label_from_name(path: str) -> str:
    """
    从基线文件名中识别轨道方向或相对轨道号。

    支持示例:
        baseline_select_SBAS_060
        baseline_select_SBAS_orbit060
        baseline_select_SBAS_Orbit_060
        baseline_select_SBAS_asc060
        baseline_select_SBAS_desc162

    参数:
        path:
            基线文件路径；仅检查不含扩展名的文件名。

    返回:
        清理后的轨道标签。未识别到 ``orbit/asc/ascending/desc/descending``
        或独立数字标签时返回空字符串。
    """
    stem = Path(path).stem
    patterns = [
        r"(?i)(orbit[_-]?\d{2,4})",
        r"(?i)((?:asc|ascending|desc|descending)[_-]?\d{2,4})",
        r"(?:^|[_-])(\d{2,4})(?:$|[_-])",
    ]
    for pattern in patterns:
        m = re.search(pattern, stem)
        if m:
            return clean_label(m.group(1))
    return ""


def default_baseline_output(
    baseline_file: str,
    orbit: str = "",
    out_dir: str = "",
) -> str:
    """
    根据基线文件名、轨道标签和输出目录生成默认 PNG 路径。

    命名规则:
        baseline_select_SBAS + orbit=060 -> baseline_select_SBAS_orbit060.png
        baseline_select_SBAS_060        -> baseline_select_SBAS_060.png

    参数:
        baseline_file:
            输入基线文件。
        orbit:
            用户显式指定的轨道号；为空时尝试从 baseline_file 文件名推断。
        out_dir:
            输出目录；为空时写到当前目录。

    返回:
        默认 PNG 路径。如果基线文件名已包含轨道标签，不会重复追加。
    """
    baseline_stem = Path(baseline_file).stem
    orbit_label = clean_label(orbit) if orbit else ""
    inferred_label = infer_orbit_label_from_name(baseline_file)
    if not orbit_label and inferred_label:
        filename = f"{baseline_stem}.png"
    elif orbit_label:
        if not orbit_label.lower().startswith(("orbit", "asc", "ascending", "desc", "descending")):
            orbit_label = f"orbit{orbit_label}"
        if baseline_stem.lower().endswith(orbit_label.lower()) or baseline_stem.lower().endswith(clean_label(orbit).lower()):
            filename = f"{baseline_stem}.png"
        else:
            filename = f"{baseline_stem}_{orbit_label}.png"
    else:
        filename = f"{baseline_stem}.png"

    if out_dir:
        return str(Path(out_dir) / filename)
    return filename


def resolve_baseline_output(out_file: str, out_dir: str = "") -> str:
    """
    合并显式输出文件名与可选输出目录。

    参数:
        out_file:
            用户指定的输出路径。
        out_dir:
            输出目录，仅当 out_file 是不含目录的相对文件名时生效。

    返回:
        展开 ``~`` 并按上述规则合并后的输出路径。
    """
    out_path = Path(out_file).expanduser()
    if out_dir and not out_path.is_absolute() and out_path.parent == Path("."):
        return str(Path(out_dir).expanduser() / out_path)
    return str(out_path)


def parse_yyyymmdd(value: int) -> datetime:
    """
    将 yyyymmdd 整数转换为 Python 的 datetime。

    参数:
        value:
            日期整数，例如 20231222。

    返回:
        对应日期的 ``datetime`` 对象。

    异常:
        ValueError:
            value 不是有效的 8 位公历日期。
    """
    return datetime.strptime(str(int(value)), "%Y%m%d")


def read_baseline_file(path: str) -> List[BaselineRow]:
    """
    读取 GAMMA ``shortbaseline`` 或 ``baseline_select_*`` 基线记录。

    参数:
        path:
            输入文本文件路径。

    返回:
        基线记录列表，每项为 ``(master_date, slave_date, pbase, tbase)``。

    支持格式:
        1) master slave pbase tbase
        2) master-slave pbase tbase

    数据约定:
        - pbase 是垂直基线，单位通常是米。
        - tbase 是时间基线，单位通常是天；如果文件没有第 4 列，会自动用日期差计算。
        - 空行和 # 开头的注释行会被忽略。

    异常:
        FileNotFoundError:
            输入文件不存在。
        ValueError:
            存在无法解析的记录，或文件中没有有效基线记录。
    """
    rows: List[BaselineRow] = []
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"baseline file not found: {path}")

    with file_path.open("r", encoding="utf-8", errors="replace") as f:
        for line_no, raw_line in enumerate(f, start=1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue

            parts = line.split()
            pair_token = parts[0]

            if len(pair_token) == 17 and pair_token[8] == "-":
                master = int(pair_token[:8])
                slave = int(pair_token[9:17])
                rest = parts[1:]
            elif len(parts) >= 2:
                master = int(parts[0])
                slave = int(parts[1])
                rest = parts[2:]
            else:
                raise ValueError(f"cannot parse line {line_no} in {path}: {line}")

            # 第 3 列是垂直基线；没有时设为 0，仍然可以画出网络拓扑。
            pbase = float(rest[0]) if len(rest) >= 1 else 0.0

            if len(rest) >= 2:
                tbase = float(rest[1])
            else:
                tbase = float((parse_yyyymmdd(slave) - parse_yyyymmdd(master)).days)

            rows.append((master, slave, pbase, tbase))

    if not rows:
        raise ValueError(f"no baseline rows parsed from {path}")
    return rows


def collect_dates(rows: Sequence[BaselineRow]) -> List[int]:
    """
    汇总基线记录中所有 master/slave SLC 日期。

    参数:
        rows:
            read_baseline_file() 返回的基线记录。

    返回:
        去重并按时间升序排列的 ``yyyymmdd`` 日期列表。
    """
    dates = set()
    for master, slave, _, _ in rows:
        dates.add(master)
        dates.add(slave)
    return sorted(dates)


def solve_perpendicular_baselines(
    rows: Sequence[BaselineRow],
    dates: Sequence[int],
    master_date: int,
) -> Dict[int, float]:
    """
    沿干涉对网络求解每个 SLC 相对指定主影像的垂直基线。

    参数:
        rows:
            基线记录。``pbase`` 符号遵循模块顶部的基线约定。
        dates:
            所有影像日期。
        master_date:
            作为 0 米基准的主影像日期。

    返回:
        以 SLC 日期为键、相对垂直基线（m）为值的字典。

    求解方法:
        每条干涉对生成一对正反向带权边，然后从 master_date 开始广度优先
        遍历并累加基线差。与主影像不连通的日期无法求得相对基线，
        函数会向标准错误输出警告，并将该日期暂设为 0 m。
    """
    graph: Dict[int, List[Tuple[int, float]]] = {date: [] for date in dates}
    for master, slave, pbase, _ in rows:
        graph[master].append((slave, pbase))
        graph[slave].append((master, -pbase))

    pbase_by_date: Dict[int, float] = {master_date: 0.0}
    queue: deque[int] = deque([master_date])

    while queue:
        current = queue.popleft()
        current_pbase = pbase_by_date[current]

        for neighbor, delta in graph[current]:
            if neighbor in pbase_by_date:
                continue
            pbase_by_date[neighbor] = current_pbase + delta
            queue.append(neighbor)

    for date in dates:
        if date not in pbase_by_date:
            print(
                f"[vis baseline] warning: {date} is not connected to master {master_date}; set pbase=0",
                file=sys.stderr,
            )
            pbase_by_date[date] = 0.0

    return pbase_by_date


def plot_baseline_network(
    baseline_file: str,
    master_date: Optional[int] = None,
    out_file: str = "perpendicular_baselines_history.png",
    title: str = "Perpendicular Baselines History",
    dpi: int = 300,
    figsize: Tuple[float, float] = (10.5, 6.2),
    y_top_extra: float = 50.0,
    y_bottom_extra: float = 0.0,
    font_family: str = "TeX Gyre Heros",
) -> str:
    """
    解析基线文件并绘制 SLC 时空基线网络图。

    参数:
        baseline_file:
            输入 shortbaseline / baseline_select_* 文件。
        master_date:
            主影像日期。若不提供，则使用文件第一行的 master 日期。
        out_file:
            输出 PNG 文件路径。
        title:
            图标题。
        dpi:
            输出图片分辨率。
        figsize:
            图片尺寸，单位为 inch。
        y_top_extra:
            在自动 y 轴上边界之外额外增加的空间，单位为 m。
        y_bottom_extra:
            在自动 y 轴下边界之外额外增加的空间，单位为 m。
        font_family:
            工具箱内置字体名称，默认使用 ``TeX Gyre Heros``。

    返回:
        实际写出的 PNG 路径。

    处理内容:
        以蓝色节点表示普通 SLC、红色节点表示基准 SLC，以连线表示参与
        解算的干涉对。输出目录不存在时会自动创建。

    异常:
        ValueError:
            master_date 未出现在基线文件中，或输入基线数据无效。
    """
    mdates, plt, LineCollection = _matplotlib_modules()
    from geodesy_visualization.backends.matplotlib import configure_plot_font

    configure_plot_font(font_family)
    rows = read_baseline_file(baseline_file)
    dates = collect_dates(rows)

    if master_date is None:
        master_date = rows[0][0]
        print(f"[vis baseline] --master-date not given; use first master date: {master_date}")

    if master_date not in dates:
        raise ValueError(f"master_date={master_date} is not in baseline file")

    pbase_by_date = solve_perpendicular_baselines(rows, dates, master_date)

    date_to_x = {date: mdates.date2num(parse_yyyymmdd(date)) for date in dates}
    date_to_y = {date: pbase_by_date[date] for date in dates}

    segments = []
    for master, slave, _, _ in rows:
        segments.append(
            [
                (date_to_x[master], date_to_y[master]),
                (date_to_x[slave], date_to_y[slave]),
            ]
        )

    fig, ax = plt.subplots(figsize=figsize, constrained_layout=True)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("#f7f8fa")

    # 所有干涉对使用统一线色。基线图的重点是网络连接关系，
    # 不额外使用 colorbar 表示长短，避免图面信息过载。
    collection = LineCollection(
        segments,
        colors="#4b5563",
        linewidths=1.75,
        alpha=0.78,
        zorder=1,
    )
    ax.add_collection(collection)

    xs = np.array([date_to_x[date] for date in dates], dtype=float)
    ys = np.array([date_to_y[date] for date in dates], dtype=float)

    normal = [date for date in dates if date != master_date]
    ax.scatter(
        [date_to_x[date] for date in normal],
        [date_to_y[date] for date in normal],
        s=62,
        facecolor="#2f80ed",
        edgecolor="#1f2937",
        linewidth=0.8,
        zorder=3,
        label="SLC images",
    )
    ax.scatter(
        [date_to_x[master_date]],
        [date_to_y[master_date]],
        s=86,
        facecolor="#ef4444",
        edgecolor="#111827",
        linewidth=1.1,
        zorder=4,
        label=f"master SLC ({master_date})",
    )

    ax.set_title(title, fontsize=15, fontweight="bold", pad=12)
    ax.set_xlabel("SLC Acquisition Date", fontsize=12, fontweight="bold")
    ax.set_ylabel("Perpendicular Baseline (m)", fontsize=12, fontweight="bold")

    ax.set_axisbelow(True)
    ax.grid(True, which="major", color="white", linewidth=1.2, zorder=0)
    ax.grid(True, which="minor", color="white", linewidth=0.5, alpha=0.65, zorder=0)
    ax.tick_params(axis="both", labelsize=10)

    ax.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=4, maxticks=8))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    fig.autofmt_xdate(rotation=25, ha="right")

    x_pad = 30.0
    y_span = float(np.nanmax(ys) - np.nanmin(ys))
    y_pad = max(40.0, y_span * 0.12)
    ax.set_xlim(float(np.nanmin(xs) - x_pad), float(np.nanmax(xs) + x_pad))
    ax.set_ylim(
        float(np.nanmin(ys) - y_pad - y_bottom_extra),
        float(np.nanmax(ys) + y_pad + y_top_extra),
    )

    legend = ax.legend(loc="upper left", frameon=True, framealpha=0.96)
    legend.get_frame().set_edgecolor("#d1d5db")

    out_path = Path(out_file)
    if out_path.parent:
        out_path.parent.mkdir(parents=True, exist_ok=True)

    fig.savefig(out_path, dpi=dpi, facecolor="white")
    plt.close(fig)
    return str(out_path)


def build_amplitude_quadtree(
    amplitude_mean: np.ndarray,
    minimum_dimension: int,
    variation_threshold: float = 0.2,
) -> np.ndarray:
    """按块内振幅变异系数构建自适应四叉树分块。"""
    values = np.asarray(amplitude_mean, dtype=np.float64)
    if values.ndim != 2:
        raise ValueError("amplitude_mean must be a 2-D array")
    if minimum_dimension <= 0:
        raise ValueError("minimum_dimension must be positive")

    integral = np.pad(
        np.cumsum(np.cumsum(values, axis=0), axis=1), ((1, 0), (1, 0))
    )
    integral_square = np.pad(
        np.cumsum(np.cumsum(values * values, axis=0), axis=1),
        ((1, 0), (1, 0)),
    )
    stack = [(0, 0, values.shape[0], values.shape[1])]
    blocks: List[Tuple[int, int, int, int]] = []

    while stack:
        row, col, height, width = stack.pop()
        area = height * width
        total = (
            integral[row + height, col + width]
            - integral[row, col + width]
            - integral[row + height, col]
            + integral[row, col]
        )
        total_square = (
            integral_square[row + height, col + width]
            - integral_square[row, col + width]
            - integral_square[row + height, col]
            + integral_square[row, col]
        )
        mean = float(total / area)
        variance = max(float(total_square / area - mean * mean), 0.0)
        coefficient = (
            np.sqrt(variance) / mean
            if mean != 0.0
            else (np.inf if variance > 0.0 else np.nan)
        )
        should_split = (
            height > minimum_dimension
            and width > minimum_dimension
            and coefficient > variation_threshold
        )

        if not should_split:
            blocks.append((row, col, height, width))
            continue

        upper_height = height // 2
        lower_height = height - upper_height
        left_width = width // 2
        right_width = width - left_width
        stack.extend(
            [
                (row, col, upper_height, left_width),
                (row, col + left_width, upper_height, right_width),
                (row + upper_height, col, lower_height, left_width),
                (
                    row + upper_height,
                    col + left_width,
                    lower_height,
                    right_width,
                ),
            ]
        )

    # MATLAB find(S1) returns sparse entries in column-major order.
    blocks.sort(key=lambda block: (block[1], block[0]))
    return np.asarray(blocks, dtype=np.int32)


def estimate_block_coherence(
    interferogram: np.ndarray,
    master_amplitude: np.ndarray,
    slave_amplitude: np.ndarray,
    blocks: np.ndarray,
) -> np.ndarray:
    """在四叉树块内选择同质像元，去二次趋势后估计相干性。"""
    ifg = np.asarray(interferogram)
    amplitude_1 = np.asarray(master_amplitude, dtype=np.float64)
    amplitude_2 = np.asarray(slave_amplitude, dtype=np.float64)
    if ifg.shape != amplitude_1.shape or ifg.shape != amplitude_2.shape:
        raise ValueError("interferogram and amplitude rasters must share one shape")

    nlines, width = ifg.shape
    ifg_amplitude = np.abs(ifg)
    phase = np.angle(ifg)
    pair_amplitude = (amplitude_1 + amplitude_2) / 2.0
    amplitude_similarity = np.exp(
        -np.abs(amplitude_1 - amplitude_2) / (2.0 * pair_amplitude + np.finfo(float).eps)
    )
    pair_amplitude = pair_amplitude.copy()
    pair_amplitude[ifg_amplitude == 0.0] = 0.0
    output = np.zeros(len(blocks), dtype=np.float64)
    lower_factor = 0.286
    upper_factor = 2.04301

    for block_index, (row, col, height, block_width) in enumerate(blocks):
        row = int(row)
        col = int(col)
        height = int(height)
        block_width = int(block_width)
        center_row = row + (height - 1) // 2
        center_col = col + (block_width - 1) // 2
        if ifg_amplitude[center_row, center_col] == 0.0:
            continue

        local = pair_amplitude[
            max(center_row - 1, 0) : min(center_row + 2, nlines),
            max(center_col - 1, 0) : min(center_col + 2, width),
        ]
        prior_mean = float(np.mean(local))
        block_amplitude = pair_amplitude[
            row : row + height, col : col + block_width
        ].ravel(order="F")
        row_indices = np.tile(np.arange(row, row + height), block_width)
        col_indices = np.repeat(np.arange(col, col + block_width), height)
        homogeneous = (block_amplitude > lower_factor * prior_mean) & (
            block_amplitude <= upper_factor * prior_mean
        )
        selected = np.flatnonzero(homogeneous)
        minimum_samples = int(np.ceil(height * block_width / 4.0)) + 1

        if selected.size < minimum_samples:
            distance = np.abs(
                block_amplitude - pair_amplitude[center_row, center_col]
            )
            selected = np.argsort(distance, kind="stable")[:minimum_samples]
            selected = selected[block_amplitude[selected] > 0.0]
        if selected.size == 0:
            continue

        selected_rows = row_indices[selected]
        selected_cols = col_indices[selected]
        row_normalized = (selected_rows + 1.0) / nlines
        col_normalized = (selected_cols + 1.0) / width
        center_row_normalized = (center_row + 1.0) / nlines
        center_col_normalized = (center_col + 1.0) / width
        design = np.column_stack(
            [
                row_normalized - center_row_normalized,
                col_normalized - center_col_normalized,
                row_normalized * col_normalized
                - center_row_normalized * center_col_normalized,
                row_normalized**2 - center_row_normalized**2,
                col_normalized**2 - center_col_normalized**2,
            ]
        )
        phase_samples = phase[selected_rows, selected_cols]
        phase_difference = (
            phase_samples - phase[center_row, center_col] + np.pi
        ) % (2.0 * np.pi) - np.pi
        parameters = np.linalg.lstsq(design, phase_difference, rcond=None)[0]
        trend = (
            row_normalized * parameters[0]
            + col_normalized * parameters[1]
            + row_normalized * col_normalized * parameters[2]
            + row_normalized**2 * parameters[3]
            + col_normalized**2 * parameters[4]
        )
        detrended = (phase_samples - trend + np.pi) % (2.0 * np.pi) - np.pi
        output[block_index] = (
            np.abs(np.sum(np.exp(1j * detrended)))
            * amplitude_similarity[center_row, center_col]
            / selected.size
        )
    return output


def coherence_quality_ratio(
    coherence_stack: np.ndarray, threshold: float = 0.05
) -> np.ndarray:
    """计算每幅干涉图中样本相干性超过阈值的块比例。"""
    values = np.asarray(coherence_stack)
    if values.ndim != 2 or values.shape[0] == 0:
        raise ValueError("coherence_stack must be a non-empty 2-D array")
    return np.mean(values >= threshold, axis=0)


def select_interferogram_network(
    baseline_rows: Sequence[BaselineRow],
    quality: Sequence[float],
    coefficient: float,
) -> Tuple[np.ndarray, List[int], np.ndarray]:
    """以最大相干性生成树保持连通，再按评分补足目标干涉对。"""
    if coefficient < 1.0:
        raise ValueError("coefficient must be greater than or equal to 1")
    rows = list(baseline_rows)
    scores = np.asarray(quality, dtype=np.float64)
    if len(rows) != scores.size:
        raise ValueError("quality length must match baseline row count")

    dates = collect_dates(rows)
    date_to_index = {date: index for index, date in enumerate(dates)}
    pairs = np.asarray(
        [[date_to_index[row[0]], date_to_index[row[1]]] for row in rows],
        dtype=np.int32,
    )
    requested_count = int(np.floor(coefficient * len(dates)))
    target_count = min(requested_count, len(rows))

    parent = np.arange(len(dates), dtype=np.int32)

    def find(node: int) -> int:
        """Return and compress the disjoint-set root for one SLC node."""
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = int(parent[node])
        return node

    quality_order = np.argsort(-scores, kind="stable")
    tree_indices: List[int] = []
    for edge_index in quality_order:
        master, slave = pairs[edge_index]
        master_root = find(int(master))
        slave_root = find(int(slave))
        if master_root == slave_root:
            continue
        parent[slave_root] = master_root
        tree_indices.append(int(edge_index))
        if len(tree_indices) == len(dates) - 1:
            break
    if len(tree_indices) != len(dates) - 1:
        raise ValueError("candidate interferogram network is disconnected")

    tree_set = set(tree_indices)
    residual = [int(index) for index in quality_order if index not in tree_set]
    extra_count = target_count - len(tree_indices)
    selected = np.asarray(
        sorted(tree_indices + residual[:extra_count]), dtype=np.int64
    )
    return selected, dates, np.asarray(sorted(tree_indices), dtype=np.int64)
