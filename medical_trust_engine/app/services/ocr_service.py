from pathlib import Path
from typing import Dict, List, Tuple

import cv2
import numpy as np
from PIL import Image, ImageEnhance, ImageFilter

from app.core.config import settings

try:
    import pytesseract
except Exception:  # pragma: no cover
    pytesseract = None

_PADDLE_OCR = None


def _get_paddle_ocr():
    global _PADDLE_OCR
    if _PADDLE_OCR is not None:
        return _PADDLE_OCR
    if settings.ocr_engine not in {"auto", "paddle"}:
        return None
    try:
        from paddleocr import PaddleOCR
        _PADDLE_OCR = PaddleOCR(use_angle_cls=True, lang=settings.paddle_lang, use_gpu=settings.paddle_use_gpu, show_log=False)
        return _PADDLE_OCR
    except Exception:
        return None


def _opencv_image(path: Path):
    image = cv2.imread(str(path))
    if image is None:
        raise ValueError(f"Could not read image: {path}")
    return image


def assess_quality(image_path: Path) -> Dict:
    image = _opencv_image(image_path)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blur_score = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    brightness = float(np.mean(gray))
    contrast = float(np.std(gray))

    blur_risk = 0.9 if blur_score < 50 else 0.5 if blur_score < 120 else 0.0
    low_contrast_risk = 0.6 if contrast < 35 else 0.0
    dark_risk = 0.5 if brightness < 80 else 0.0
    overexposed_risk = 0.4 if brightness > 220 else 0.0
    quality_score = max(0, min(100, 100 - (blur_risk + low_contrast_risk + dark_risk + overexposed_risk) * 25))

    return {
        "image": str(image_path),
        "blur_score": round(blur_score, 2),
        "brightness": round(brightness, 2),
        "contrast": round(contrast, 2),
        "quality_score": round(quality_score, 2),
        "risks": {
            "blur": blur_risk,
            "low_contrast": low_contrast_risk,
            "dark_scan": dark_risk,
            "overexposed": overexposed_risk,
        },
    }


def deskew_image(gray: np.ndarray) -> np.ndarray:
    coords = np.column_stack(np.where(gray < 245))
    if coords.size == 0:
        return gray
    angle = cv2.minAreaRect(coords)[-1]
    if angle < -45:
        angle = -(90 + angle)
    else:
        angle = -angle
    if abs(angle) < 0.5 or abs(angle) > 20:
        return gray
    (h, w) = gray.shape[:2]
    center = (w // 2, h // 2)
    matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
    return cv2.warpAffine(gray, matrix, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


def preprocess_for_ocr(image_path: Path, out_dir: Path) -> List[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    original = Image.open(image_path).convert("RGB")
    gray = original.convert("L")

    # Variant 1: contrast/sharpness for printed bills.
    enhanced = ImageEnhance.Contrast(gray).enhance(1.8).filter(ImageFilter.SHARPEN)
    enhanced_path = out_dir / f"{image_path.stem}_enhanced.png"
    enhanced.save(enhanced_path)

    # Variant 2: deskew + threshold for receipts/bills.
    gray_arr = np.array(gray)
    deskewed = deskew_image(gray_arr)
    binary = cv2.adaptiveThreshold(deskewed, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 11)
    binary_path = out_dir / f"{image_path.stem}_binary.png"
    Image.fromarray(binary).save(binary_path)

    # Variant 3: denoised grayscale for handwriting/stamps.
    denoised = cv2.fastNlMeansDenoising(deskewed, None, 10, 7, 21)
    denoised_path = out_dir / f"{image_path.stem}_denoised.png"
    Image.fromarray(denoised).save(denoised_path)

    return [image_path, enhanced_path, binary_path, denoised_path]


def run_tesseract(image_path: Path) -> Tuple[str, list]:
    if pytesseract is None or settings.ocr_engine == "none":
        return "", []
    try:
        image = Image.open(image_path)
        text = pytesseract.image_to_string(image)
        data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
        boxes = []
        for i, word in enumerate(data.get("text", [])):
            if not word or not str(word).strip():
                continue
            conf = float(data.get("conf", [0])[i]) if str(data.get("conf", [0])[i]).replace('.', '', 1).lstrip('-').isdigit() else 0
            boxes.append({
                "text": word,
                "confidence": conf / 100 if conf > 0 else 0,
                "bbox": [data["left"][i], data["top"][i], data["left"][i] + data["width"][i], data["top"][i] + data["height"][i]],
                "engine": "tesseract",
            })
        return text, boxes
    except Exception:
        return "", []


def run_paddleocr(image_path: Path) -> Tuple[str, list]:
    ocr = _get_paddle_ocr()
    if ocr is None:
        return "", []
    try:
        result = ocr.ocr(str(image_path), cls=True)
        lines, boxes = [], []
        for page in result or []:
            for item in page or []:
                bbox, pair = item[0], item[1]
                text, conf = pair[0], float(pair[1])
                lines.append(text)
                xs = [int(p[0]) for p in bbox]
                ys = [int(p[1]) for p in bbox]
                boxes.append({"text": text, "confidence": conf, "bbox": [min(xs), min(ys), max(xs), max(ys)], "engine": "paddleocr"})
        return "\n".join(lines), boxes
    except Exception:
        return "", []


def ocr_pages(page_paths: List[Path], native_text: str, out_dir: Path) -> Dict:
    all_quality = []
    text_candidates = []
    all_boxes = []
    processed_paths = []
    engines_used = []

    if native_text:
        text_candidates.append({"text": native_text, "engine": "native_pdf", "length": len(native_text)})
        engines_used.append("native_pdf")

    for page in page_paths:
        all_quality.append(assess_quality(page))
        variants = preprocess_for_ocr(page, out_dir / "ocr_variants")
        processed_paths.extend([str(v) for v in variants])
        # Production speed rule: run PaddleOCR once per page when available;
        # run Tesseract on the enhanced variant only. This avoids 20+ OCR calls
        # for a multi-page hospital bill while still giving strong extraction.
        paddle_text, paddle_boxes = run_paddleocr(page)
        if paddle_text.strip():
            text_candidates.append({"text": paddle_text, "engine": "paddleocr", "length": len(paddle_text)})
            all_boxes.extend(paddle_boxes)
            engines_used.append("paddleocr")

        tesseract_target = variants[1] if len(variants) > 1 else page
        tess_text, tess_boxes = run_tesseract(tesseract_target)
        if tess_text.strip():
            text_candidates.append({"text": tess_text, "engine": "tesseract", "length": len(tess_text)})
            all_boxes.extend(tess_boxes)
            engines_used.append("tesseract")

    best = max(text_candidates, key=lambda item: item["length"]) if text_candidates else {"text": "", "engine": "none", "length": 0}
    return {
        "raw_text": best["text"].strip(),
        "quality": all_quality,
        "processed_images": processed_paths,
        "ocr_boxes": all_boxes,
        "ocr_available": bool(best["text"].strip()),
        "selected_engine": best["engine"],
        "engines_used": sorted(set(engines_used)),
        "note": "Production OCR supports PaddleOCR when installed; Tesseract remains fallback. TrOCR can be added for handwritten-only region crops.",
    }
