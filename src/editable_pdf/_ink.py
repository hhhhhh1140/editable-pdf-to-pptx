"""Local background and glyph masks for separated raster assets."""

import numpy as np
from PIL import Image, ImageFilter

def luma(rgb):
    return rgb[..., 0] * .299 + rgb[..., 1] * .587 + rgb[..., 2] * .114


def vertical_estimate(crop, top, bottom, light_ink):
    """Interpolate the nearby paper color, preferring the edge without ink."""
    upper = np.median(crop[:top + 1], axis=0).astype(np.float32)
    lower = np.median(crop[bottom - 1:], axis=0).astype(np.float32)
    delta = luma(upper) - luma(lower)
    # For dark ink, the cleaner of two samples is usually the brighter one.
    upper_wins = delta < -20 if light_ink else delta > 20
    lower_wins = delta > 20 if light_ink else delta < -20
    original_upper = upper.copy()
    upper[lower_wins] = lower[lower_wins]
    lower[upper_wins] = original_upper[upper_wins]
    # Nearby columns fill in where a glyph touches an edge sample.
    radius = max(2, min(12, (bottom - top) // 5))
    for edge in (upper, lower):
        padded = np.pad(edge, ((radius, radius), (0, 0)), mode="edge")
        windows = np.lib.stride_tricks.sliding_window_view(padded, 2 * radius + 1, axis=0)
        windows = np.moveaxis(windows, -1, 1)
        brightness = luma(windows)
        order = np.argsort(brightness, axis=1)
        quantile = round((2 * radius) * (.24 if light_ink else .76))
        neighbor = windows[np.arange(len(edge)), order[:, quantile]]
        change = np.abs(luma(neighbor) - luma(edge))
        edge[change < 75] = neighbor[change < 75]
    mix = np.linspace(0, 1, len(crop), dtype=np.float32)[:, None, None]
    return upper[None] * (1 - mix) + lower[None] * mix


def detect_ink(image, box):
    """Find contrasting strokes inside a line, including their antialiasing."""
    left, top, right, bottom = box
    h = bottom - top
    margin_x = max(3, round(h * .13))
    margin_y = max(3, round(h * .16))
    x0, y0 = max(0, left - margin_x), max(0, top - margin_y)
    x1, y1 = min(image.width, right + margin_x), min(image.height, bottom + margin_y)
    crop = np.asarray(image.crop((x0, y0, x1, y1)))
    gray = luma(crop)
    core = gray[top-y0:bottom-y0, left-x0:right-x0]
    if not core.size:
        return None
    above = gray[:max(1, top-y0)]
    below = gray[min(bottom-y0, len(gray)-1):]
    reference = np.median(np.concatenate([above.ravel(), below.ravel()]))
    inside_reference = np.median(core)
    if abs(reference - inside_reference) > 36:
        reference = inside_reference
    low, high = np.percentile(core, [9, 91])
    light_ink = high - reference > (reference - low) * 1.12
    bg = vertical_estimate(crop, top-y0, bottom-y0, light_ink)
    contrast = luma(bg) - gray
    if light_ink:
        contrast = -contrast
    central = contrast[top-y0:bottom-y0, left-x0:right-x0]
    peak = np.percentile(central, 93)
    strokes = contrast > max(22, peak * .30)
    if peak < 19:
        return None
    # Constrain the mask to the OCR bounds plus a small allowance for glyph edges.
    slack_x = max(2, round(h * .10))
    slack_y = max(2, round(h * .08))
    bounds = np.zeros_like(strokes)
    bounds[max(0, top-y0-slack_y):bottom-y0+slack_y,
           max(0, left-x0-slack_x):right-x0+slack_x] = True
    strokes &= bounds
    rows, cols = np.where(strokes)
    if len(rows) < 5:
        return None
    # Keep faint edge pixels next to strong strokes, including colored fringe.
    radius = 2 if h < 36 else 3
    dilated = np.asarray(Image.fromarray(strokes).filter(ImageFilter.MaxFilter(2 * radius + 1)))
    alpha = dilated & bounds & (contrast > 3)
    foreground = crop[strokes & (contrast >= np.percentile(contrast[strokes], 65))]
    color = "".join(f"{int(c):02X}" for c in np.median(foreground, axis=0))
    return (x0, y0, x1, y1), bg, alpha, rows, cols, color
