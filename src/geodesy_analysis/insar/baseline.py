"""Scientific baseline-network quality estimation and pair selection."""

from typing import List, Sequence, Tuple

import numpy as np

BaselineRow = Tuple[int, int, float, float]


def collect_dates(rows: Sequence[BaselineRow]) -> List[int]:
    """
    汇总基线记录中所有 master/slave SLC 日期。

    参数:
        rows:
            主影像、从影像、垂直基线和时间基线记录。

    返回:
        去重并按时间升序排列的 ``yyyymmdd`` 日期列表。
    """
    dates = set()
    for master, slave, _, _ in rows:
        dates.add(master)
        dates.add(slave)
    return sorted(dates)


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
