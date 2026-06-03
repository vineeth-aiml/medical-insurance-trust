from pathlib import Path
from typing import Dict, List

import cv2
import imagehash
import numpy as np
from PIL import Image

from app.core.config import settings


def _hash_image(path: Path) -> dict:
    image = Image.open(path).convert("L")
    return {"phash": str(imagehash.phash(image)), "dhash": str(imagehash.dhash(image))}


def _hamming_hex(a: str, b: str) -> int:
    try:
        return bin(int(a, 16) ^ int(b, 16)).count("1")
    except Exception:
        return 64


def _crop_candidate_regions(image_path: Path, out_dir: Path) -> List[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    img = cv2.imread(str(image_path))
    if img is None:
        return []
    h, w = img.shape[:2]
    regions = {
        "bottom_right": img[int(h * 0.55):h, int(w * 0.45):w],
        "bottom_left": img[int(h * 0.55):h, 0:int(w * 0.55)],
        "header": img[0:int(h * 0.30), 0:w],
        "full_lowres": cv2.resize(img, (min(w, 900), int(h * min(w, 900) / w))) if w > 900 else img,
    }
    paths = []
    for name, crop in regions.items():
        if crop.size == 0:
            continue
        out = out_dir / f"{image_path.stem}_{name}.png"
        cv2.imwrite(str(out), crop)
        paths.append(out)
    return paths


def _reference_paths(kind: str) -> List[Path]:
    base = settings.signature_reference_dir if kind == "signature" else settings.stamp_reference_dir
    if not Path(base).exists():
        return []
    return [p for p in Path(base).glob("**/*") if p.suffix.lower() in {".png", ".jpg", ".jpeg"}]


def _best_hash_match(candidate: Path, refs: List[Path]) -> dict:
    if not refs:
        return {"matched": False, "distance": None, "label": None, "risk": 0.2, "reason": "No verified reference images available"}
    cand_hash = _hash_image(candidate)
    best = {"distance": 999, "label": None, "reference_path": None}
    for ref in refs:
        ref_hash = _hash_image(ref)
        dist = min(_hamming_hex(cand_hash["phash"], ref_hash["phash"]), _hamming_hex(cand_hash["dhash"], ref_hash["dhash"]))
        if dist < best["distance"]:
            best = {"distance": dist, "label": ref.stem, "reference_path": str(ref)}
    matched = best["distance"] <= 10
    return {
        "matched": matched,
        "distance": best["distance"],
        "label": best["label"],
        "reference_path": best["reference_path"],
        "risk": 0.0 if matched else 0.45,
        "reason": "Visual reference matched" if matched else "Visual reference did not match known signature/stamp profiles",
    }


def analyze_signature_and_stamp(page_paths: List[Path], claim_dir: Path) -> Dict:
    out_dir = claim_dir / "visual_profiles"
    candidates: List[Path] = []
    for page in page_paths:
        candidates.extend(_crop_candidate_regions(page, out_dir))

    sig_refs = _reference_paths("signature")
    stamp_refs = _reference_paths("stamp")

    sig_matches = [_best_hash_match(c, sig_refs) | {"candidate": str(c)} for c in candidates]
    stamp_matches = [_best_hash_match(c, stamp_refs) | {"candidate": str(c)} for c in candidates]

    best_sig = min(sig_matches, key=lambda x: x.get("risk", 1)) if sig_matches else {"risk": 0.2, "reason": "No signature candidate detected"}
    best_stamp = min(stamp_matches, key=lambda x: x.get("risk", 1)) if stamp_matches else {"risk": 0.2, "reason": "No stamp candidate detected"}

    risk = max(float(best_sig.get("risk", 0)), float(best_stamp.get("risk", 0)))
    reasons = [best_sig.get("reason", ""), best_stamp.get("reason", "")]
    return {
        "signature_stamp_risk": round(risk, 2),
        "best_signature_match": best_sig,
        "best_stamp_match": best_stamp,
        "candidate_regions": [str(c) for c in candidates],
        "reference_counts": {"signature": len(sig_refs), "stamp": len(stamp_refs)},
        "reasons": [r for r in reasons if r],
        "note": "For stronger production accuracy, add verified doctor signature/stamp samples per clinic and train a Siamese/embedding model.",
    }
