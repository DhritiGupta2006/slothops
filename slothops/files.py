"""Constrained filesystem access, content fingerprints, and bounded text extraction."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import io
import os
from pathlib import Path
import stat
import zipfile
import xml.etree.ElementTree as ET


class SafetyError(ValueError):
    pass


EXCLUDED = {".slothops", ".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache"}
TEXT_EXTENSIONS = {".txt", ".md", ".csv", ".json", ".log", ".rst", ".yaml", ".yml", ".html", ".xml"}
READABLE = TEXT_EXTENSIONS | {".pdf", ".docx"}
DOCUMENT_CATEGORIES = ("Work", "Finance", "Personal", "Study", "Reference", "Other")
MAX_FILE_BYTES = 100 * 1024 * 1024
MAX_DOCUMENT_BYTES = 20 * 1024 * 1024


def is_link(path: Path) -> bool:
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def root_path(value: str | Path) -> Path:
    raw = Path(value).expanduser().absolute()
    if not raw.is_dir():
        raise SafetyError("Choose an existing folder.")
    if is_link(raw):
        raise SafetyError("Choose a real folder, not a symbolic link or Windows junction.")
    result = raw.resolve(strict=True)
    if result == Path(result.anchor):
        raise SafetyError("Choose a specific folder instead of an entire drive.")
    return result


def identity(path: Path) -> dict:
    info = path.stat()
    return {"device": info.st_dev, "inode": info.st_ino}


def safe_path(root: Path, value: str | Path, *, internal: bool = False) -> Path:
    root = root_path(root)
    path = Path(value)
    if not path.is_absolute():
        path = root / path
    if ".." in path.parts:
        raise SafetyError("Parent path traversal is not allowed.")
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise SafetyError("The file must stay inside its approved folder.") from exc
    if not relative.parts:
        raise SafetyError("An action must address a file, not the root folder.")
    if not internal and any(part.casefold() in EXCLUDED for part in relative.parts):
        raise SafetyError("SlothOps internal and development folders are excluded.")
    current = root
    for part in relative.parts:
        current /= part
        if current.exists() or current.is_symlink():
            if is_link(current):
                raise SafetyError("Symbolic links and Windows reparse points are excluded.")
    if not path.resolve(strict=False).is_relative_to(root):
        raise SafetyError("The path resolves outside the approved folder.")
    return path


def fingerprint(path: Path) -> dict:
    if is_link(path) or not path.is_file():
        raise SafetyError("Only regular files can be processed.")
    before = path.stat()
    if before.st_nlink > 1:
        raise SafetyError("Hard-linked files are excluded from file changes.")
    if before.st_size > MAX_FILE_BYTES:
        raise SafetyError("File exceeds the 100 MB scan limit.")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    after = path.stat()
    fields = ("st_size", "st_mtime_ns", "st_ino", "st_dev")
    if any(getattr(before, name) != getattr(after, name) for name in fields):
        raise SafetyError("The file changed while being read. Scan it again.")
    return {"sha256": digest.hexdigest(), "size": after.st_size, "mtime_ns": after.st_mtime_ns,
            "inode": after.st_ino, "device": after.st_dev}


def verify(path: Path, expected: dict, *, content_only: bool = False):
    actual = fingerprint(path)
    keys = ("sha256", "size") if content_only else tuple(expected)
    if any(actual.get(key) != expected[key] for key in keys):
        raise SafetyError("The file changed since preview. Create a fresh plan.")


@dataclass
class Scan:
    files: list[Path] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    limited: bool = False


def scan_folder(root: Path, *, limit: int = 500, skip_organized: bool = False, exclude: Path | None = None) -> Scan:
    root = root_path(root)
    report = Scan()
    def walk_error(error):
        report.skipped.append(str(error))
    for folder, directories, names in os.walk(root, followlinks=False, onerror=walk_error):
        kept = []
        for name in sorted(directories):
            candidate = Path(folder) / name
            try:
                if name.casefold() in EXCLUDED or (skip_organized and name.casefold() == "organized"):
                    continue
                if exclude and exclude.is_relative_to(root) and (candidate == exclude or candidate.is_relative_to(exclude)):
                    continue
                safe_path(root, candidate)
                if is_link(candidate):
                    continue
                kept.append(name)
            except (OSError, SafetyError) as exc:
                report.skipped.append(f"{candidate.name}: {exc}")
        directories[:] = kept
        for name in sorted(names):
            candidate = Path(folder) / name
            try:
                safe_path(root, candidate)
                info = candidate.stat()
                if not candidate.is_file() or info.st_nlink > 1:
                    raise SafetyError("Not a regular, independent file")
                if info.st_size > MAX_FILE_BYTES:
                    raise SafetyError("Over 100 MB")
                if len(report.files) >= limit:
                    report.limited = True
                    return report
                report.files.append(candidate)
            except (OSError, SafetyError) as exc:
                report.skipped.append(f"{candidate.name}: {exc}")
    return report


def extract_bytes(data: bytes, suffix: str, *, max_chars: int = 240_000) -> str:
    if len(data) > MAX_DOCUMENT_BYTES:
        raise ValueError("Documents must be 20 MB or smaller.")
    suffix = suffix.lower()
    if suffix in TEXT_EXTENSIONS:
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = data.decode("cp1252")
    elif suffix == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise ValueError("Unlock the PDF before importing it.")
        if len(reader.pages) > 200:
            raise ValueError("Split PDFs larger than 200 pages before importing.")
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
    elif suffix == ".docx":
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            info = archive.getinfo("word/document.xml")
            if info.file_size > 10 * 1024 * 1024:
                raise ValueError("The document's expanded text is too large.")
            document = ET.fromstring(archive.read(info))
            ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
            text = "\n".join("".join(t.itertext()) for t in document.findall(".//w:p", ns))
    else:
        raise ValueError("Use TXT, Markdown, CSV, JSON, LOG, PDF, or DOCX.")
    text = text.replace("\x00", "").strip()
    if not text:
        raise ValueError("No text found. Scanned images need OCR before import.")
    if len(text) > max_chars:
        raise ValueError(f"Text exceeds {max_chars:,} characters. Split the document first; nothing was silently truncated.")
    return text


def extract_file(path: Path, *, max_chars: int = 240_000) -> str:
    if path.stat().st_size > MAX_DOCUMENT_BYTES:
        raise ValueError("Document exceeds 20 MB.")
    return extract_bytes(path.read_bytes(), path.suffix, max_chars=max_chars)


def type_category(path: Path) -> str:
    suffix = path.suffix.lower()
    groups = {
        "Images": {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".heic"},
        "Audio": {".mp3", ".wav", ".flac", ".m4a", ".ogg"},
        "Video": {".mp4", ".mov", ".avi", ".mkv", ".webm"},
        "Archives": {".zip", ".7z", ".rar", ".tar", ".gz"},
        "Code": {".py", ".js", ".ts", ".tsx", ".jsx", ".css", ".sh", ".ps1"},
        "Documents": READABLE | {".xlsx", ".pptx", ".doc", ".xls", ".ppt"},
    }
    return next((group for group, extensions in groups.items() if suffix in extensions), "Other")
