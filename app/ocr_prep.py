"""Image clean-up before OCR, aimed at old typewritten / photocopied regulations.

All steps use Pillow + NumPy only (no OpenCV), so they bundle easily in the portable package:
  normalise background  — divide by a smooth estimate of the paper (yellowing, uneven light)
  stretch contrast      — faded ribbon ink becomes dark again
  denoise               — median filter removes speckle
  deskew                — rotate so text lines are horizontal (projection-profile search)
  binarise (Sauvola)    — local threshold that survives uneven ink and paper
"""
import numpy as np
from PIL import Image, ImageFilter, ImageOps


def normalise(img):
    """Grayscale image with a flat white background and stretched contrast."""
    g = ImageOps.grayscale(img)
    small = g.resize((max(1, g.width // 8), max(1, g.height // 8)), Image.BILINEAR)
    # text is thin, so a max filter followed by a blur leaves only the paper
    bg = small.filter(ImageFilter.MaxFilter(7)).filter(ImageFilter.GaussianBlur(6)).resize(g.size, Image.BILINEAR)
    a = np.asarray(g, dtype=np.float32)
    b = np.maximum(np.asarray(bg, dtype=np.float32), 1.0)
    flat = np.clip(a / b, 0, 1)
    lo, hi = np.percentile(flat, (0.5, 99.5))
    if hi - lo < 1e-3:
        return g
    out = np.clip((flat - lo) / (hi - lo), 0, 1)
    return Image.fromarray((out * 255).astype(np.uint8)).filter(ImageFilter.MedianFilter(3))


def skew_angle(img, max_angle=3.0, step=0.2):
    """Angle (degrees) that makes text lines horizontal, found by maximising row-profile variance."""
    small = img.resize((max(1, img.width // 4), max(1, img.height // 4)), Image.BILINEAR)
    ink = Image.fromarray((np.asarray(small) < 160).astype(np.uint8) * 255)
    best, best_score = 0.0, -1.0
    for angle in np.arange(-max_angle, max_angle + 1e-6, step):
        rows = np.asarray(ink.rotate(float(angle), resample=Image.NEAREST, fillcolor=0)).sum(axis=1, dtype=np.float64)
        score = float(np.var(rows))
        if score > best_score:
            best, best_score = float(angle), score
    return best


def deskew(img):
    angle = skew_angle(img)
    if abs(angle) < 0.15:
        return img, 0.0
    return img.rotate(angle, resample=Image.BICUBIC, fillcolor=255, expand=False), angle


def sauvola(img, window=41, k=0.2, r=128.0):
    """Binary image (0 ink / 255 paper) with Sauvola's local threshold, via integral images."""
    a = np.asarray(img, dtype=np.float64)
    h, w = a.shape
    pad = window // 2
    p = np.pad(a, pad + 1, mode="edge")
    s1 = p.cumsum(0).cumsum(1)
    s2 = (p * p).cumsum(0).cumsum(1)

    def box(s):
        return (s[window:window + h, window:window + w] - s[0:h, window:window + w]
                - s[window:window + h, 0:w] + s[0:h, 0:w])
    n = window * window
    mean = box(s1) / n
    std = np.sqrt(np.maximum(box(s2) / n - mean * mean, 0))
    thresh = mean * (1 + k * (std / r - 1))
    return Image.fromarray(np.where(a > thresh, 255, 0).astype(np.uint8))


def prepare(img, binarise=True):
    """Full clean-up; returns (image, info)."""
    g = normalise(img)
    g, angle = deskew(g)
    out = sauvola(g) if binarise else g
    return out, {"skew": round(angle, 2), "binarised": binarise}
