"""Test helper: synthetic 'old typewritten regulation' scans with known ground truth, for measuring OCR accuracy."""
import io
import random

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

import os

FONT = "/usr/share/fonts/truetype/freefont/FreeMono.ttf"  # Courier-like typewriter face; Pillow's font otherwise

TEXT = """PERATURAN MENTERI TENAGA KERJA DAN TRANSMIGRASI
NOMOR PER.02/MEN/1980
TENTANG
PEMERIKSAAN KESEHATAN TENAGA KERJA DALAM PENYELENGGARAAN KESELAMATAN KERJA
MENTERI TENAGA KERJA DAN TRANSMIGRASI,
Menimbang : bahwa untuk melaksanakan ketentuan undang-undang dipandang perlu menetapkan peraturan.
BAB I
KETENTUAN UMUM
Pasal 1
Yang dimaksud dalam Peraturan Menteri ini dengan pemeriksaan kesehatan sebelum bekerja ialah pemeriksaan kesehatan yang dilakukan oleh dokter sebelum seorang tenaga kerja diterima untuk melakukan pekerjaan.
Pasal 2
(1) Pemeriksaan Kesehatan sebelum bekerja ditujukan agar tenaga kerja yang diterima berada dalam kondisi kesehatan yang setinggi-tingginya.
(2) Pengurus wajib melakukan pemeriksaan kesehatan sebelum bekerja terhadap setiap tenaga kerja yang akan diterimanya.
Pasal 3
(1) Pemeriksaan kesehatan berkala wajib dilakukan sekurang-kurangnya 1 (satu) tahun sekali.
(2) Hasil pemeriksaan kesehatan wajib dilaporkan kepada Direktur paling lambat 2 (dua) bulan setelah pemeriksaan.
Pasal 4
Pengurus dilarang mempekerjakan tenaga kerja yang tidak memenuhi syarat kesehatan sebagaimana dimaksud dalam Pasal 2 ayat (2).
Pasal 5
Pengurus yang tidak memenuhi ketentuan Pasal 2 dan Pasal 3 diancam dengan hukuman kurungan selama-lamanya 3 (tiga) bulan atau denda setinggi-tingginya Rp 100.000,- (seratus ribu rupiah)."""


def wrap(lines, font, draw, width):
    out = []
    for ln in lines:
        cur = ""
        for w in ln.split():
            trial = (cur + " " + w).strip()
            if draw.textlength(trial, font=font) > width and cur:
                out.append(cur)
                cur = w
            else:
                cur = trial
        out.append(cur)
    return out


def render_pages(text=TEXT, size=46, lines_per_page=40):
    """Clean rendering at 300 dpi A4; returns (images, ground-truth lines)."""
    font = ImageFont.truetype(FONT, size) if os.path.isfile(FONT) else ImageFont.load_default(size=size)
    probe = ImageDraw.Draw(Image.new("L", (10, 10)))
    lines = wrap(text.splitlines(), font, probe, 2000)
    pages, gt = [], []
    for start in range(0, len(lines), lines_per_page):
        chunk = lines[start:start + lines_per_page]
        img = Image.new("L", (2480, 3508), 255)
        d = ImageDraw.Draw(img)
        for i, ln in enumerate(chunk):
            d.text((240, 260 + i * 78), ln, fill=0, font=font)
        pages.append(img)
        gt.extend(chunk)
    return pages, "\n".join(gt)


def degrade(img, level, seed=7):
    """Typewriter/photocopy damage: uneven ink, yellowed paper, noise, skew, blur, JPEG."""
    rnd = random.Random(seed)
    rng = np.random.default_rng(seed)
    p = {"ringan": dict(ink=0.15, noise=0.004, skew=0.4, blur=0.6, contrast=0.85, jpeg=70),
         "sedang": dict(ink=0.35, noise=0.012, skew=1.2, blur=1.0, contrast=0.65, jpeg=45),
         "berat": dict(ink=0.55, noise=0.03, skew=2.0, blur=1.4, contrast=0.5, jpeg=30)}[level]
    a = np.asarray(img, dtype=np.float32) / 255.0
    ink = 1 - a
    # uneven ribbon ink: faded and heavy strokes in patches
    patch = rng.random((a.shape[0] // 60 + 1, a.shape[1] // 60 + 1))
    patch = np.kron(patch, np.ones((60, 60)))[: a.shape[0], : a.shape[1]]
    ink = ink * (1 - p["ink"] * patch)
    im = Image.fromarray(((1 - ink) * 255).astype(np.uint8))
    if p["ink"] > 0.3:  # bleeding / filled counters in places
        im = Image.blend(im, im.filter(ImageFilter.MinFilter(3)), 0.5)
    a = np.asarray(im, dtype=np.float32) / 255.0
    # yellowed, unevenly lit paper and reduced contrast
    yy, xx = np.mgrid[0:a.shape[0], 0:a.shape[1]]
    light = 0.82 + 0.18 * (xx / a.shape[1]) * (1 - 0.5 * yy / a.shape[0])
    a = (a * p["contrast"] + (1 - p["contrast"])) * light
    # speckle noise
    mask = rng.random(a.shape) < p["noise"]
    a[mask] = rng.random(mask.sum()) * 0.6
    im = Image.fromarray(np.clip(a * 255, 0, 255).astype(np.uint8))
    im = im.rotate(p["skew"] * (1 if rnd.random() > 0.5 else -1), fillcolor=200, resample=Image.BICUBIC)
    im = im.filter(ImageFilter.GaussianBlur(p["blur"]))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=p["jpeg"])
    return Image.open(io.BytesIO(buf.getvalue())).convert("L")


def scanned_pdf(level, seed=7):
    pages, gt = render_pages()
    imgs = [degrade(pg, level, seed + i) for i, pg in enumerate(pages)]
    buf = io.BytesIO()
    imgs[0].save(buf, "PDF", resolution=300, save_all=True, append_images=imgs[1:])
    return buf.getvalue(), gt


def cer(reference, hypothesis):
    """Character error rate after whitespace normalisation (Levenshtein / len(reference))."""
    r = " ".join(reference.split())
    h = " ".join(hypothesis.split())
    prev = list(range(len(h) + 1))
    for i, rc in enumerate(r, 1):
        cur = [i]
        for j, hc in enumerate(h, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (rc != hc)))
        prev = cur
    return prev[-1] / max(1, len(r))
