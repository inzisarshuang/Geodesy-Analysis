#!/usr/bin/env python3
"""
geodesy_analysis.insar.masking
==============================

功能概述:
    提供二值掩膜的图像读写、阈值构建、布尔组合、
    振幅统计和地形约束函数；不负责 cfg、GAMMA 工程发现、参考点流程编排或
    来源产品导出。

函数说明:
    ``read_mask``:
        读取 BMP/TIFF 并将非零像元归一化为二值掩膜。
    ``_write_bmp_u8``:
        写出无压缩的 8-bit 灰度调色板 BMP。
    ``write_gray_u8``:
        将 uint8 二维数组写为 BMP/TIFF 灰度图。
    ``write_mask``:
        将二值掩膜写为值域 0/255 的 BMP/TIFF。
    ``coherence_mask``:
        根据相干性阈值和保留方向生成二值掩膜。
    ``amplitude_statistics``:
        逐景读取 MLI 栅格，计算振幅均值、标准差、有效数和 ADI。
    ``amplitude_mean_mask``:
        根据振幅均值阈值和有效观测数生成掩膜。
    ``amplitude_dispersion_mask``:
        根据 ADI 阈值生成稳定散射区掩膜。
    ``combine_masks``:
        对一个或多个掩膜执行 and、or、xor 或 not 运算。
    ``mask_valid_ratio``:
        计算掩膜中有效像元占全部像元的比例。
    ``topographic_flat_mask``:
        根据 DEM 梯度估算坡度并生成平坦区掩膜。
    ``relax_amplitude_mask``:
        在非平坦地形中放宽振幅掩膜，保留山区像元。
"""

import sys
from typing import Iterable, Sequence, Tuple

import numpy as np

from insar_data_adapter import read_binary_raster

from geodesy_analysis.io import atomic_output_path


def _require_pillow():
    """Import Pillow only for image-mask I/O."""
    try:
        from PIL import Image
    except ImportError as exc:
        raise ImportError(
            "Pillow is required only for BMP/TIFF mask image I/O"
        ) from exc
    Image.MAX_IMAGE_PIXELS = None
    return Image


def read_mask(path: str, nlines: int, width: int) -> np.ndarray:
    """Read a BMP/TIFF image and normalize nonzero pixels to a uint8 mask."""
    if not path.lower().endswith((".bmp", ".tif", ".tiff")):
        raise ValueError(f"Unsupported mask format: {path} (use .bmp/.tif/.tiff)")
    image = _require_pillow()
    with image.open(path) as source:
        arr = np.array(source.convert("L"), dtype=np.uint8)
    if arr.shape != (nlines, width):
        raise ValueError(
            f"Size mismatch for {path}: got {arr.shape}, expect {(nlines, width)}"
        )
    return (arr > 0).astype(np.uint8)


def _write_bmp_u8(array: np.ndarray, out_path: str) -> None:
    """Write one uint8 array as an uncompressed, palette-based grayscale BMP."""
    arr = np.asarray(array, dtype=np.uint8)
    if arr.ndim != 2:
        raise ValueError(f"BMP output requires a 2-D array, got shape {arr.shape}")
    h, w = arr.shape
    row_stride = ((w + 3) // 4) * 4
    pixel_bytes = row_stride * h
    palette_bytes = 256 * 4
    file_header_size = 14
    dib_header_size = 40
    pixel_offset = file_header_size + dib_header_size + palette_bytes
    file_size = pixel_offset + pixel_bytes

    with open(out_path, "wb") as f:
        f.write(b"BM")
        f.write(file_size.to_bytes(4, "little"))
        f.write((0).to_bytes(2, "little"))
        f.write((0).to_bytes(2, "little"))
        f.write(pixel_offset.to_bytes(4, "little"))

        f.write(dib_header_size.to_bytes(4, "little"))
        f.write(w.to_bytes(4, "little", signed=True))
        f.write(h.to_bytes(4, "little", signed=True))
        f.write((1).to_bytes(2, "little"))
        f.write((8).to_bytes(2, "little"))
        f.write((0).to_bytes(4, "little"))
        f.write(pixel_bytes.to_bytes(4, "little"))
        f.write((2835).to_bytes(4, "little", signed=True))
        f.write((2835).to_bytes(4, "little", signed=True))
        f.write((256).to_bytes(4, "little"))
        f.write((0).to_bytes(4, "little"))

        for i in range(256):
            f.write(bytes((i, i, i, 0)))

        pad = bytes(row_stride - w)
        for y in range(h - 1, -1, -1):
            f.write(arr[y].tobytes())
            if pad:
                f.write(pad)


def write_gray_u8(array: np.ndarray, out_path: str) -> None:
    """Write a 2-D uint8 array as BMP or TIFF while preserving gray levels."""
    arr = np.asarray(array, dtype=np.uint8)
    if arr.ndim != 2:
        raise ValueError(f"grayscale output requires a 2-D array, got shape {arr.shape}")
    lower = out_path.lower()
    if not lower.endswith((".bmp", ".tif", ".tiff")):
        raise ValueError(f"Unsupported output format: {out_path} (use .bmp/.tif/.tiff)")
    with atomic_output_path(out_path) as temporary:
        if lower.endswith(".bmp"):
            _write_bmp_u8(arr, str(temporary))
        else:
            image = _require_pillow()
            image.fromarray(arr, mode="L").save(temporary, format="TIFF")


def write_mask(mask: np.ndarray, out_path: str) -> None:
    """Write a binary mask as an 8-bit BMP/TIFF with values 0 and 255."""
    binary = np.where(np.asarray(mask).astype(bool), 255, 0).astype(np.uint8)
    write_gray_u8(binary, out_path)


def coherence_mask(
    coh: np.ndarray, threshold: float, keep_if_ge: bool = True
) -> np.ndarray:
    """由相干性阈值得到掩膜。keep_if_ge=True 表示 coh>=threshold 为有效(1)。"""
    finite = np.isfinite(coh)
    if keep_if_ge:
        return (finite & (coh >= threshold)).astype(np.uint8)
    return (finite & (coh <= threshold)).astype(np.uint8)


def amplitude_statistics(
    files: Iterable[str], nlines: int, width: int, block_rows: int = 256
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    流式累加各景 MLI（x>0 计入）：返回 mean, std, cnt, adi。
    adi = std/mean 仅在 cnt>0 且 mean>0 且 std>0 处有定义，否则为 nan（避免 std=0 得 ADI=0 误判为低离差）。
    """
    files = list(files)
    if not files:
        raise ValueError("No input files for amplitude statistics.")
    if block_rows <= 0:
        raise ValueError("block_rows must be positive")

    sum_x = np.zeros((nlines, width), dtype=np.float64)
    sum_x2 = np.zeros((nlines, width), dtype=np.float64)
    cnt = np.zeros((nlines, width), dtype=np.int32)

    total = len(files)
    for i, fp in enumerate(files, start=1):
        print(f"[amp-stats] {i}/{total}: {fp}", file=sys.stderr, flush=True)
        source = read_binary_raster(
            fp, (nlines, width), dtype="float32", endian="big", memmap=True
        )
        for row_start in range(0, nlines, block_rows):
            rows = slice(row_start, min(row_start + block_rows, nlines))
            values = np.asarray(source[rows], dtype=np.float64)
            valid = values > 0
            np.add(sum_x[rows], values, out=sum_x[rows], where=valid)
            np.square(values, out=values)
            np.add(sum_x2[rows], values, out=sum_x2[rows], where=valid)
            cnt[rows] += valid
        del source

    observed = cnt > 0
    np.divide(sum_x, cnt, out=sum_x, where=observed)
    sum_x[~observed] = 0.0
    np.divide(sum_x2, cnt, out=sum_x2, where=observed)
    adi = np.full((nlines, width), np.nan, dtype=np.float64)
    for row_start in range(0, nlines, block_rows):
        rows = slice(row_start, min(row_start + block_rows, nlines))
        mean_block = sum_x[rows]
        std_block = sum_x2[rows]
        std_block -= mean_block * mean_block
        np.maximum(std_block, 0.0, out=std_block)
        np.sqrt(std_block, out=std_block)
        usable = (cnt[rows] > 0) & (mean_block > 0) & (std_block > 0)
        np.divide(std_block, mean_block, out=adi[rows], where=usable)
    return sum_x, sum_x2, cnt, adi


def amplitude_mean_mask(
    mean: np.ndarray, mean_threshold: float, cnt: np.ndarray
) -> np.ndarray:
    """
    振幅均值掩膜：与 amplitude_statistics 配套使用。
    仅 cnt>0 且 mean 有限且 >= 阈值 -> 1；无观测处不凭 mean 数值误通过。
    """
    return (
        (cnt > 0) & np.isfinite(mean) & (mean >= mean_threshold)
    ).astype(np.uint8)


def amplitude_dispersion_mask(adi: np.ndarray, adi_threshold: float) -> np.ndarray:
    """
    振幅离差掩膜：仅当 ADI 为有限值且 <= 阈值时为 1。
    NaN/inf（无观测、std=0 等）为 0，BMP/TIF 中为黑；ADI 应由 amplitude_statistics 一并算出。
    """
    return (np.isfinite(adi) & (adi <= adi_threshold)).astype(np.uint8)


def combine_masks(masks: Sequence[np.ndarray], operation: str) -> np.ndarray:
    """Combine one or more masks with ``and``, ``or``, ``xor``, or ``not``."""
    if not masks:
        raise ValueError("combine_masks needs at least one mask")

    op = operation.lower()
    arrays = [np.asarray(mask).astype(bool) for mask in masks]
    if op == "not":
        if len(arrays) != 1:
            raise ValueError("operation=not needs exactly one mask")
        return (~arrays[0]).astype(np.uint8)
    if op not in {"and", "or", "xor"}:
        raise ValueError(f"Unsupported mask operation: {operation}")

    out = arrays[0]
    for array in arrays[1:]:
        if array.shape != out.shape:
            raise ValueError(f"mask shape mismatch: {array.shape} != {out.shape}")
        if op == "and":
            out = out & array
        elif op == "or":
            out = out | array
        else:
            out = out ^ array
    return out.astype(np.uint8)


def mask_valid_ratio(mask: np.ndarray) -> float:
    """返回掩膜有效像元占比。"""
    return float(np.mean(mask.astype(bool)))


def topographic_flat_mask(
    hgt: np.ndarray, dx: float, dy: float, slope_max_deg: float
) -> np.ndarray:
    """
    用高程梯度估计坡度，生成平坦区掩膜：
      flat=1 when slope_deg <= slope_max_deg
    """
    gy, gx = np.gradient(hgt.astype(np.float64), dy, dx)
    slope_rad = np.arctan(np.sqrt(gx * gx + gy * gy))
    slope_deg = np.rad2deg(slope_rad)
    return (slope_deg <= slope_max_deg).astype(np.uint8)


def relax_amplitude_mask(amp_valid: np.ndarray, topo_flat: np.ndarray) -> np.ndarray:
    """
    地形约束下放宽振幅掩膜：
      - 平坦区：使用 amp_valid（严格去水）
      - 非平坦区：直接保留（避免山区低反射误杀）
    等价：amp_valid OR (NOT topo_flat)
    """
    return (amp_valid.astype(bool) | (~topo_flat.astype(bool))).astype(np.uint8)
