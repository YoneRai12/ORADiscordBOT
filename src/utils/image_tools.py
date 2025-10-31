"""Utility helpers for image classification and OCR."""

from __future__ import annotations

import io
import logging
from typing import Tuple

from PIL import Image

try:
    import pytesseract
except ImportError:  # pragma: no cover - optional dependency
    pytesseract = None  # type: ignore

import numpy as np

logger = logging.getLogger(__name__)


def classify_image(data: bytes) -> str:
    """Return a simple colour-based classification label for the image."""

    with Image.open(io.BytesIO(data)) as img:
        image = img.convert("RGB")
        array = np.array(image)

    avg_color = array.mean(axis=(0, 1))
    red, green, blue = avg_color
    dominant = max((red, "赤系"), (green, "緑系"), (blue, "青系"), key=lambda item: item[0])[1]
    brightness = float(array.mean())
    mood = "明るい" if brightness > 180 else "落ち着いた" if brightness > 100 else "暗め"
    width, height = image.size
    aspect: float = width / height if height else 1
    orientation = "横長" if aspect > 1.2 else "縦長" if aspect < 0.8 else "ほぼ正方形"
    return f"推定カテゴリ: {dominant} / 雰囲気: {mood} / 形状: {orientation}"


def ocr_image(data: bytes) -> str:
    """Extract text using pytesseract if available."""

    if pytesseract is None:
        raise RuntimeError("pytesseract がインストールされていません。")

    with Image.open(io.BytesIO(data)) as img:
        image = img.convert("RGB")

    try:
        text = pytesseract.image_to_string(image, lang="jpn+eng")
    except pytesseract.TesseractNotFoundError as exc:  # type: ignore[attr-defined]
        raise RuntimeError("Tesseract 実行ファイルが見つかりません。サーバーにインストールしてください。") from exc
    except Exception as exc:  # pragma: no cover - passthrough message
        raise RuntimeError(f"OCR に失敗しました: {exc}") from exc

    cleaned = text.strip()
    if not cleaned:
        return "テキストは検出されませんでした。"
    return cleaned
