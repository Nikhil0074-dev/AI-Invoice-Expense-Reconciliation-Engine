from PIL import Image, ImageOps


def preprocess(img: Image.Image) -> Image.Image:
    """Orientation fix (EXIF), grayscale, upscale small receipts, autocontrast."""
    img = ImageOps.exif_transpose(img)
    img = img.convert("L")
    w, h = img.size
    if max(w, h) < 1400:
        factor = 2 if max(w, h) >= 700 else 3
        img = img.resize((w * factor, h * factor), Image.LANCZOS)
    return ImageOps.autocontrast(img, cutoff=1)
