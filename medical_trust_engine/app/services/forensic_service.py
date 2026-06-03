import json
from pathlib import Path
from typing import Dict, List

import cv2
import imagehash
import numpy as np
from PIL import Image, ImageChops, ImageEnhance

SUSPICIOUS_CREATORS = [
    "photoshop", "canva", "paint", "gimp", "pixlr", "photopea", "illustrator", "coreldraw",
    "ms word", "libreoffice", "powerpoint"
]


def metadata_risk(pdf_info: Dict) -> Dict:
    metadata = pdf_info.get("metadata", {}) or {}
    joined = " ".join([str(v) for v in metadata.values() if v]).lower()
    suspicious_hits = [tool for tool in SUSPICIOUS_CREATORS if tool in joined]

    creation = metadata.get("creationDate") or metadata.get("created")
    mod = metadata.get("modDate") or metadata.get("modified")
    modified_after_created = bool(creation and mod and creation != mod)

    risk = 0.0
    reasons = []
    if suspicious_hits:
        risk += 0.55
        reasons.append(f"Suspicious editor metadata found: {', '.join(suspicious_hits)}")
    if modified_after_created:
        risk += 0.20
        reasons.append("PDF modification timestamp differs from creation timestamp")
    if pdf_info.get("pdf_type") == "SCANNED":
        reasons.append("Scanned document: metadata may not prove authenticity")

    return {
        "metadata": metadata,
        "suspicious_tools": suspicious_hits,
        "modified_after_created": modified_after_created,
        "risk": min(risk, 1.0),
        "reasons": reasons,
    }


def ela_image(image_path: Path, out_path: Path, quality: int = 85) -> Dict:
    # IMPORTANT: create the forensic output folder before writing the temporary
    # recompressed image. Without this, Windows raises:
    # [Errno 2] No such file or directory: .../forensic/ela_page_1.recompressed.jpg
    out_path.parent.mkdir(parents=True, exist_ok=True)

    image = Image.open(image_path).convert("RGB")
    temp_path = out_path.with_suffix(".recompressed.jpg")
    image.save(temp_path, "JPEG", quality=quality)
    recompressed = Image.open(temp_path).convert("RGB")

    diff = ImageChops.difference(image, recompressed)
    extrema = diff.getextrema()
    max_diff = max([ex[1] for ex in extrema]) or 1
    scale = 255.0 / max_diff
    ela = ImageEnhance.Brightness(diff).enhance(scale)
    ela.save(out_path)
    temp_path.unlink(missing_ok=True)

    gray = np.array(ela.convert("L"))
    mean_error = float(np.mean(gray))
    std_error = float(np.std(gray))
    p95 = float(np.percentile(gray, 95))

    # This is a heuristic signal, not proof. High localized compression inconsistency increases risk.
    risk = 0.0
    if p95 > 75 and std_error > 25:
        risk = 0.65
    elif p95 > 50 and std_error > 18:
        risk = 0.35

    return {
        "image": str(image_path),
        "ela_output": str(out_path),
        "mean_error": round(mean_error, 2),
        "std_error": round(std_error, 2),
        "p95_error": round(p95, 2),
        "risk": risk,
    }


def perceptual_hashes(page_paths: List[Path]) -> Dict:
    hashes = []
    for path in page_paths:
        image = Image.open(path).convert("RGB")
        hashes.append({
            "image": str(path),
            "phash": str(imagehash.phash(image)),
            "dhash": str(imagehash.dhash(image)),
        })
    return {"hashes": hashes}


def amount_date_region_risk(extracted: Dict, raw_text: str) -> Dict:
    risk = 0.0
    reasons = []

    if extracted.get("max_amount", 0) > 10000 and extracted.get("document_type") in {"BILL", "PRESCRIPTION"}:
        risk += 0.25
        reasons.append("High amount detected for bill/prescription; verify manually")

    if len(extracted.get("dates", [])) >= 4:
        risk += 0.15
        reasons.append("Many dates detected; verify bill date, prescription date, and leave date consistency")

    if not raw_text.strip():
        risk += 0.25
        reasons.append("No reliable text extracted; document needs manual review or stronger OCR")

    return {"risk": min(risk, 1.0), "reasons": reasons}


def analyze_forensics(page_paths: List[Path], pdf_info: Dict, extracted: Dict, raw_text: str, out_dir: Path) -> Dict:
    meta = metadata_risk(pdf_info)
    ela_results = []
    ela_errors = []

    # ELA is useful evidence, but it should never crash the whole claim.
    # If one page fails, continue with the remaining forensic checks and show
    # a warning in the final reasons.
    for idx, page in enumerate(page_paths, start=1):
        try:
            ela_results.append(ela_image(page, out_dir / "forensic" / f"ela_page_{idx}.png"))
        except Exception as exc:
            ela_errors.append({
                "page": idx,
                "image": str(page),
                "error": str(exc),
            })

    try:
        hash_info = perceptual_hashes(page_paths)
    except Exception as exc:
        hash_info = {"hashes": [], "error": str(exc)}

    region = amount_date_region_risk(extracted, raw_text)

    risks = [meta["risk"], region["risk"]] + [r["risk"] for r in ela_results]
    overall = max(risks) if risks else 0.0
    reasons = meta["reasons"] + region["reasons"]
    if any(r["risk"] >= 0.35 for r in ela_results):
        reasons.append("ELA/compression inconsistency found in one or more pages")
    if ela_errors:
        reasons.append("ELA could not be completed for one or more pages; other checks continued")

    return {
        "metadata_analysis": meta,
        "ela_analysis": ela_results,
        "ela_errors": ela_errors,
        "perceptual_hashes": hash_info,
        "region_rules": region,
        "overall_forensic_risk": round(overall, 2),
        "reasons": reasons,
    }
