import hashlib
import json
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

import fitz  # PyMuPDF
from PIL import Image

from app.core.config import settings
from app.storage.object_store import object_store

try:
    import magic
except Exception:  # pragma: no cover
    magic = None


@dataclass
class StoredFile:
    claim_id: str
    original_name: str
    file_hash: str
    file_path: Path
    processed_dir: Path
    storage_backend: str = "local"
    storage_key: str | None = None


def generate_claim_id() -> str:
    return "CLM" + uuid.uuid4().hex[:12].upper()


def calculate_sha256(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(8192), b""):
            sha.update(chunk)
    return sha.hexdigest()


def validate_extension(filename: str) -> None:
    suffix = Path(filename).suffix.lower()
    if suffix not in settings.allowed_extensions:
        raise ValueError(f"Unsupported file type '{suffix}'. Upload PDF, JPG, JPEG, or PNG only.")


def validate_size(path: Path) -> None:
    size_mb = path.stat().st_size / (1024 * 1024)
    if size_mb <= 0:
        raise ValueError("Uploaded file is empty.")
    if size_mb > settings.max_upload_mb:
        raise ValueError(f"File too large. Maximum allowed size is {settings.max_upload_mb} MB.")


def validate_mime(path: Path, filename: str) -> None:
    suffix = Path(filename).suffix.lower()
    if magic is None:
        return
    mime = magic.from_file(str(path), mime=True) or ""
    if suffix == ".pdf" and mime not in {"application/pdf", "application/octet-stream"}:
        raise ValueError(f"Invalid PDF file content: {mime}")
    if suffix in {".png", ".jpg", ".jpeg"} and not mime.startswith("image/"):
        raise ValueError(f"Invalid image file content: {mime}")


def store_upload(file_obj, filename: str) -> StoredFile:
    validate_extension(filename)
    claim_id = generate_claim_id()
    claim_dir = settings.processed_dir / claim_id
    claim_dir.mkdir(parents=True, exist_ok=True)

    safe_name = Path(filename).name.replace(" ", "_")
    dest = settings.upload_dir / f"{claim_id}_{safe_name}"
    with dest.open("wb") as buffer:
        shutil.copyfileobj(file_obj, buffer)

    validate_size(dest)
    validate_mime(dest, filename)
    file_hash = calculate_sha256(dest)

    object_key = f"claims/{claim_id}/original/{safe_name}"
    storage = object_store.put_file(dest, object_key, content_type="application/pdf" if dest.suffix.lower() == ".pdf" else "image/png")

    return StoredFile(
        claim_id=claim_id,
        original_name=filename,
        file_hash=file_hash,
        file_path=dest,
        processed_dir=claim_dir,
        storage_backend=storage.get("backend", "local"),
        storage_key=storage.get("key"),
    )


def inspect_pdf(path: Path) -> Dict:
    try:
        doc = fitz.open(path)
    except Exception as exc:
        raise ValueError(f"Cannot open PDF. File may be corrupt: {exc}") from exc

    info = doc.metadata or {}
    page_count = doc.page_count
    text_chars = 0
    image_count = 0
    embedded_files = []
    encrypted = doc.needs_pass

    for page in doc:
        text_chars += len(page.get_text("text") or "")
        image_count += len(page.get_images(full=True))
    try:
        embedded_files = [doc.embfile_info(i) for i in range(doc.embfile_count())]
    except Exception:
        embedded_files = []
    doc.close()

    if encrypted:
        pdf_type = "ENCRYPTED"
    elif text_chars > 50 and image_count > 0:
        pdf_type = "NATIVE_OR_HYBRID"
    elif text_chars > 50:
        pdf_type = "NATIVE"
    else:
        pdf_type = "SCANNED"

    return {
        "page_count": page_count,
        "metadata": info,
        "text_chars": text_chars,
        "image_count": image_count,
        "embedded_files": embedded_files,
        "pdf_type": pdf_type,
        "encrypted": encrypted,
    }


def extract_native_pdf_text(path: Path) -> str:
    text_parts: List[str] = []
    doc = fitz.open(path)
    for page in doc:
        text_parts.append(page.get_text("text") or "")
    doc.close()
    return "\n".join(text_parts).strip()


def render_pdf_pages(path: Path, out_dir: Path, dpi: int = 300) -> List[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(path)
    zoom = dpi / 72
    matrix = fitz.Matrix(zoom, zoom)
    paths = []
    for index, page in enumerate(doc, start=1):
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        out_path = out_dir / f"page_{index}.png"
        pix.save(out_path)
        paths.append(out_path)
    doc.close()
    return paths


def normalize_image_file(path: Path, out_dir: Path) -> List[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    image = Image.open(path).convert("RGB")
    out_path = out_dir / "page_1.png"
    image.save(out_path)
    return [out_path]


def prepare_document_pages(path: Path, claim_dir: Path) -> Tuple[List[Path], Dict, str]:
    suffix = path.suffix.lower()
    pages_dir = claim_dir / "pages"
    if suffix == ".pdf":
        pdf_info = inspect_pdf(path)
        if pdf_info["encrypted"]:
            raise ValueError("Password-protected PDFs are not supported.")
        pages = render_pdf_pages(path, pages_dir)
        native_text = extract_native_pdf_text(path)
        return pages, pdf_info, native_text

    pages = normalize_image_file(path, pages_dir)
    return pages, {"pdf_type": "IMAGE", "page_count": 1, "metadata": {}}, ""


def save_json(path: Path, payload: Dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
