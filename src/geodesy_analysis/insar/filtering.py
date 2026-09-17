"""
geodesy_analysis.insar.filtering
================================

功能概述:
    提供 GAMMA 干涉图的标准相干估计和单次 NL-InSAR 非局部滤波。
    算法按带重叠的小块运行，联合估计反射率和缠绕相位；不负责 GAMMA 文件
    发现、缓存、并行任务编排或产品写出。

函数说明:
    ``estimate_likelihood_bandwidth``:
        用固定随机种子估计指定 patch 的似然带宽。
    ``resolve_filter_parameters``:
        检查并补全单次非局部滤波参数。
    ``estimate_boxcar_coherence``:
        从两景振幅和干涉相位计算标准局部相干性。
    ``_pixel_log_likelihood``:
        计算两组 InSAR 像元的对数似然相似度。
    ``_enforce_minimum_looks``:
        当等效视数不足时重新分配最相似样本的权重。
    ``_filter_tile``:
        对一块带重叠数据执行一次 NL-InSAR 加权估计。
    ``nonlocal_insar_filter``:
        对指定有效区域分块执行一次 NL-InSAR，返回反射率、相位和后验相干性。
    ``compose_filtered_interferogram``:
        将滤波反射率和相位组合为 GAMMA 复数干涉图。
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple

import numpy as np


def estimate_likelihood_bandwidth(
    patch_size: int,
    alpha: float = 0.92,
    samples: int = 20000,
    seed: int = 20260717,
) -> float:
    """用固定随机种子估计单视 InSAR patch 的中心化似然分位数。"""
    if patch_size <= 0 or patch_size % 2 == 0:
        raise ValueError("patch_size must be a positive odd integer")
    if not 0.0 < alpha < 1.0:
        raise ValueError("alpha must be between 0 and 1")
    if samples <= 0:
        raise ValueError("samples must be positive")

    if patch_size == 3:
        return 0.58
    if patch_size == 7:
        return 0.244

    rng = np.random.default_rng(seed)
    patch_area = patch_size * patch_size
    batch_size = min(samples, 1000)
    values = np.empty(samples, dtype=np.float64)
    eps = np.finfo(np.float64).eps
    offset = 0
    while offset < samples:
        count = min(batch_size, samples - offset)
        shape = (count, patch_area)
        slc = (
            rng.standard_normal((4,) + shape)
            + 1j * rng.standard_normal((4,) + shape)
        ) / np.sqrt(2.0)
        am1, as1, am2, as2 = (np.abs(slc[index]) for index in range(4))
        dp1 = np.angle(slc[0] * np.conj(slc[1]))
        dp2 = np.angle(slc[2] * np.conj(slc[3]))
        log_similarity = _pixel_log_likelihood(
            am1, as1, dp1, am2, as2, dp2, eps
        )
        values[offset : offset + count] = -np.mean(log_similarity, axis=1)
        offset += count
    return float(np.quantile(values, alpha) - np.mean(values))


def resolve_filter_parameters(
    search_window: int = 13,
    patch_size: int = 3,
    minimum_looks: int = 80,
    likelihood_h: Optional[float] = None,
    seed: int = 20260717,
) -> Dict[str, float | int | str]:
    """检查单次非局部滤波参数，并确定性计算似然带宽。"""
    for label, value in (
        ("search_window", search_window),
        ("patch_size", patch_size),
    ):
        if value <= 0 or value % 2 == 0:
            raise ValueError(f"{label} must be a positive odd integer")
    if minimum_looks <= 0:
        raise ValueError("minimum_looks must be positive")
    if minimum_looks > search_window * search_window:
        raise ValueError("minimum_looks exceeds the search-window sample count")

    if likelihood_h is None:
        h_theoretical = estimate_likelihood_bandwidth(patch_size, seed=seed)
        likelihood_h = h_theoretical * patch_size * patch_size
    if likelihood_h <= 0.0:
        raise ValueError("likelihood_h must be positive")
    return {
        "search_window": int(search_window),
        "patch_size": int(patch_size),
        "minimum_looks": int(minimum_looks),
        "likelihood_h": float(likelihood_h),
        "seed": int(seed),
    }


def estimate_boxcar_coherence(
    master_amplitude: np.ndarray,
    slave_amplitude: np.ndarray,
    phase: np.ndarray,
    window_size: int,
    valid_mask: Optional[np.ndarray] = None,
) -> np.ndarray:
    """用局部复互相关计算标准归一化相干性。"""
    from scipy.ndimage import uniform_filter

    if window_size <= 0 or window_size % 2 == 0:
        raise ValueError("window_size must be a positive odd integer")
    master = np.asarray(master_amplitude, dtype=np.float32)
    slave = np.asarray(slave_amplitude, dtype=np.float32)
    phase_values = np.asarray(phase, dtype=np.float32)
    if master.shape != slave.shape or master.shape != phase_values.shape:
        raise ValueError("amplitude and phase arrays must have the same shape")
    cross = master * slave * np.exp(1j * phase_values)
    real = uniform_filter(cross.real, window_size, mode="reflect")
    imag = uniform_filter(cross.imag, window_size, mode="reflect")
    master_power = uniform_filter(master * master, window_size, mode="reflect")
    slave_power = uniform_filter(slave * slave, window_size, mode="reflect")
    denominator = np.sqrt(master_power * slave_power)
    coherence = np.divide(
        np.hypot(real, imag),
        denominator,
        out=np.zeros_like(master, dtype=np.float32),
        where=denominator > np.finfo(np.float32).eps,
    )
    np.clip(coherence, 0.0, 1.0, out=coherence)
    if valid_mask is not None:
        coherence[~np.asarray(valid_mask, dtype=bool)] = 0.0
    return coherence


def _pixel_log_likelihood(
    am1: np.ndarray,
    as1: np.ndarray,
    phase1: np.ndarray,
    am2: np.ndarray,
    as2: np.ndarray,
    phase2: np.ndarray,
    epsilon: float,
) -> np.ndarray:
    """计算论文式两像元观测的对数似然相似度。"""
    a_value = (am1 * am1 + as1 * as1 + am2 * am2 + as2 * as2) ** 2
    product = am1 * as1 * am2 * as2
    b_value = 4.0 * (
        (am1 * as1) ** 2
        + (am2 * as2) ** 2
        + 2.0 * product * np.cos(phase1 - phase2)
    )
    safe_a = np.maximum(a_value, epsilon)
    safe_b = np.clip(b_value, epsilon, safe_a * (1.0 - 1.0e-7))
    factor = np.power(np.maximum(product / safe_b, epsilon), 1.5)
    bracket = (
        (safe_a + safe_b)
        / safe_a
        * np.sqrt(safe_b / np.maximum(safe_a - safe_b, epsilon))
        - np.arcsin(np.sqrt(np.clip(safe_b / safe_a, 0.0, 1.0)))
    )
    result = np.log(np.maximum(factor * bracket, epsilon))
    result[~np.isfinite(result)] = np.log(epsilon)
    return np.minimum(result, 0.0)


def _enforce_minimum_looks(
    weights: np.ndarray,
    eligible: np.ndarray,
    minimum_looks: int,
) -> None:
    """原位修正等效视数不足像元的最高权重。"""
    sum_weights = np.sum(weights, axis=0, dtype=np.float64)
    sum_squares = np.sum(weights * weights, axis=0, dtype=np.float64)
    equivalent = np.divide(
        sum_weights * sum_weights,
        sum_squares,
        out=np.zeros_like(sum_weights),
        where=sum_squares > 0.0,
    )
    low = equivalent < minimum_looks
    if not np.any(low):
        return

    candidate_count = np.sum(eligible, axis=0)
    enough = low & (candidate_count >= minimum_looks)
    if np.any(enough):
        scores = np.where(eligible, weights, -np.inf)
        selected = np.argpartition(
            scores, -minimum_looks, axis=0
        )[-minimum_looks:]
        selected_weights = np.take_along_axis(weights, selected, axis=0)
        replacement = np.broadcast_to(
            np.mean(selected_weights, axis=0, keepdims=True),
            selected_weights.shape,
        )
        selected_weights = np.where(
            enough[None, :, :], replacement, selected_weights
        )
        np.put_along_axis(weights, selected, selected_weights, axis=0)

    short = low & (candidate_count > 0) & (candidate_count < minimum_looks)
    if np.any(short):
        candidate_mean = np.divide(
            np.sum(np.where(eligible, weights, 0.0), axis=0),
            candidate_count,
            out=np.zeros_like(sum_weights),
            where=candidate_count > 0,
        )
        weights[:] = np.where(
            short[None, :, :] & eligible,
            candidate_mean[None, :, :],
            weights,
        )


def _filter_tile(
    master: np.ndarray,
    slave: np.ndarray,
    phase: np.ndarray,
    core_shape: Tuple[int, int],
    search_window: int,
    patch_size: int,
    minimum_looks: int,
    likelihood_h: float,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """对一块带足够重叠的数据执行单次非局部估计。"""
    from scipy.ndimage import uniform_filter

    core_height, core_width = core_shape
    search_half = search_window // 2
    patch_half = patch_size // 2
    overlap = search_half + patch_half
    center_rows = slice(overlap, overlap + core_height)
    center_cols = slice(overlap, overlap + core_width)
    patch_rows = slice(
        overlap - patch_half, overlap + core_height + patch_half
    )
    patch_cols = slice(
        overlap - patch_half, overlap + core_width + patch_half
    )
    epsilon = float(np.finfo(np.float32).eps)
    offsets = [
        (row_offset, col_offset)
        for row_offset in range(-search_half, search_half + 1)
        for col_offset in range(-search_half, search_half + 1)
    ]
    weights = np.empty(
        (len(offsets), core_height, core_width), dtype=np.float32
    )
    eligible = np.empty_like(weights, dtype=bool)

    reference_master = master[patch_rows, patch_cols]
    reference_slave = slave[patch_rows, patch_cols]
    reference_phase = phase[patch_rows, patch_cols]
    center_master = master[center_rows, center_cols]

    for index, (row_offset, col_offset) in enumerate(offsets):
        if row_offset == 0 and col_offset == 0:
            # A patch is maximally similar to itself.  Evaluating the
            # closed-form likelihood at identical samples is singular, so
            # use its analytical log-weight limit directly.
            weights[index] = 0.0
            eligible[index] = True
            continue
        shifted_rows = slice(
            overlap - patch_half + row_offset,
            overlap + core_height + patch_half + row_offset,
        )
        shifted_cols = slice(
            overlap - patch_half + col_offset,
            overlap + core_width + patch_half + col_offset,
        )
        log_likelihood = _pixel_log_likelihood(
            reference_master,
            reference_slave,
            reference_phase,
            master[shifted_rows, shifted_cols],
            slave[shifted_rows, shifted_cols],
            phase[shifted_rows, shifted_cols],
            epsilon,
        )
        likelihood_sum = uniform_filter(
            log_likelihood, patch_size, mode="nearest"
        ) * (patch_size * patch_size)
        log_weight = likelihood_sum[
            patch_half : patch_half + core_height,
            patch_half : patch_half + core_width,
        ] / likelihood_h
        weights[index] = log_weight.astype(np.float32)
        shifted_center_rows = slice(
            overlap + row_offset, overlap + core_height + row_offset
        )
        shifted_center_cols = slice(
            overlap + col_offset, overlap + core_width + col_offset
        )
        eligible[index] = (
            master[shifted_center_rows, shifted_center_cols]
            < 2.0 * center_master
        )

    maximum = np.max(weights, axis=0)
    weights -= maximum[None, :, :]
    np.exp(weights, out=weights)
    weights[~np.isfinite(weights)] = 0.0
    _enforce_minimum_looks(weights, eligible, minimum_looks)

    normalization = np.sum(weights, axis=0, dtype=np.float64)
    reflectivity_sum = np.zeros(core_shape, dtype=np.float64)
    cross_sum = np.zeros(core_shape, dtype=np.complex128)
    for index, (row_offset, col_offset) in enumerate(offsets):
        shifted_rows = slice(
            overlap + row_offset, overlap + core_height + row_offset
        )
        shifted_cols = slice(
            overlap + col_offset, overlap + core_width + col_offset
        )
        master_values = master[shifted_rows, shifted_cols]
        slave_values = slave[shifted_rows, shifted_cols]
        phase_values = phase[shifted_rows, shifted_cols]
        current_weights = weights[index]
        reflectivity_sum += current_weights * (
            master_values * master_values + slave_values * slave_values
        ) / 2.0
        cross_sum += (
            current_weights
            * master_values
            * slave_values
            * np.exp(-1j * phase_values)
        )
    reflectivity = np.divide(
        reflectivity_sum,
        normalization,
        out=np.zeros_like(reflectivity_sum),
        where=normalization > 0.0,
    )
    phase_output = -np.angle(cross_sum)
    # Use the same nonlocal samples and weights for phase and coherence.
    coherence = np.divide(
        np.abs(cross_sum),
        reflectivity_sum,
        out=np.zeros_like(reflectivity_sum),
        where=reflectivity_sum > 0.0,
    )
    np.clip(coherence, 0.0, 1.0, out=coherence)
    return (
        reflectivity.astype(np.float32),
        phase_output.astype(np.float32),
        coherence.astype(np.float32),
    )


def nonlocal_insar_filter(
    master_amplitude: np.ndarray,
    slave_amplitude: np.ndarray,
    phase: np.ndarray,
    valid_mask: np.ndarray,
    parameters: Dict[str, float | int | str],
    process_mask: Optional[np.ndarray] = None,
    tile_size: int = 96,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """按重叠分块估计反射率、缠绕相位和非局部加权相干性。"""
    master = np.asarray(master_amplitude, dtype=np.float32)
    slave = np.asarray(slave_amplitude, dtype=np.float32)
    phase_values = np.asarray(phase, dtype=np.float32)
    valid = np.asarray(valid_mask, dtype=bool)
    if not (master.shape == slave.shape == phase_values.shape == valid.shape):
        raise ValueError("all NL-InSAR input arrays must share one shape")
    if tile_size <= 0:
        raise ValueError("tile_size must be positive")
    active = (
        valid.copy()
        if process_mask is None
        else np.asarray(process_mask, dtype=bool).copy()
    )
    if active.shape != valid.shape:
        raise ValueError("process_mask must have the same shape as the inputs")
    active &= valid

    search_window = int(parameters["search_window"])
    patch_size = int(parameters["patch_size"])
    overlap = search_window // 2 + patch_size // 2
    pad = ((overlap, overlap), (overlap, overlap))
    master_padded = np.pad(master, pad, mode="symmetric")
    slave_padded = np.pad(slave, pad, mode="symmetric")
    phase_padded = np.pad(phase_values, pad, mode="symmetric")
    height, width = master.shape
    reflectivity = np.zeros(master.shape, dtype=np.float32)
    filtered_phase = np.zeros(master.shape, dtype=np.float32)
    filtered_coherence = np.zeros(master.shape, dtype=np.float32)
    for row in range(0, height, tile_size):
        core_height = min(tile_size, height - row)
        for col in range(0, width, tile_size):
            core_width = min(tile_size, width - col)
            output_rows = slice(row, row + core_height)
            output_cols = slice(col, col + core_width)
            if not np.any(active[output_rows, output_cols]):
                continue
            tile_rows = slice(row, row + core_height + 2 * overlap)
            tile_cols = slice(col, col + core_width + 2 * overlap)
            tile_output = _filter_tile(
                master_padded[tile_rows, tile_cols],
                slave_padded[tile_rows, tile_cols],
                phase_padded[tile_rows, tile_cols],
                (core_height, core_width),
                search_window,
                patch_size,
                int(parameters["minimum_looks"]),
                float(parameters["likelihood_h"]),
            )
            reflectivity[output_rows, output_cols] = tile_output[0]
            filtered_phase[output_rows, output_cols] = tile_output[1]
            filtered_coherence[output_rows, output_cols] = tile_output[2]
    reflectivity[~valid] = 0.0
    filtered_phase[~valid] = 0.0
    filtered_coherence[~valid] = 0.0
    return reflectivity, filtered_phase, filtered_coherence


def compose_filtered_interferogram(
    reflectivity: np.ndarray, phase: np.ndarray, valid_mask: np.ndarray
) -> np.ndarray:
    """将反射率与缠绕相位组合成复数滤波干涉图。"""
    output = np.asarray(reflectivity, dtype=np.float32) * np.exp(
        1j * np.asarray(phase, dtype=np.float32)
    )
    output[~np.asarray(valid_mask, dtype=bool)] = 0.0
    return output.astype(np.complex64, copy=False)
