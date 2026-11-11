"""Voice packs for the chat reader: model files you upload from the dashboard, kept on the server and served back to your browser.

Files go in a folder (VOICE_DIR, default data/voices). On Railway that folder is wiped on every deploy unless you attach a Volume to it, and the
status says so. Names are checked so nothing can be written outside the folder, zips are unpacked with the same checks and a size limit.
"""
from __future__ import annotations

import io
import os
import re
import shutil
import zipfile
from pathlib import Path
from typing import Any, AsyncIterator

PACK_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,47}$")
ALLOWED_EXT = {".onnx", ".json", ".bin", ".wav", ".txt", ".wasm", ".js", ".mjs", ".data", ".model", ".vocab", ".yaml", ".yml", ".npy", ".npz"}
MAX_FILES = 200


class VoiceError(ValueError):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.message, self.status = message, status


def clean_rel(rel: str) -> str:
    """One safe relative path: no drive letters, no .., no empty parts, no hidden files, a known file type."""
    rel = rel.replace("\\", "/").strip("/")
    parts = rel.split("/")
    if not rel or len(rel) > 200 or any(p in ("", ".", "..") or p.startswith(".") or ":" in p or "\x00" in p for p in parts):
        raise VoiceError("That file name is not allowed.")
    if Path(rel).suffix.lower() not in ALLOWED_EXT:
        raise VoiceError(f"Files of type {Path(rel).suffix or 'none'} are not accepted here. Voice packs hold models, configs and word lists.")
    return "/".join(parts)


class VoiceStore:
    def __init__(self, root: str, max_mb: int) -> None:
        self.root, self.max_bytes = Path(root), max_mb * 1024 * 1024

    def status(self) -> dict[str, Any]:
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            probe = self.root / ".probe"
            probe.write_text("x"); probe.unlink()
            writable = True
        except OSError:
            writable = False
        return {"dir": str(self.root), "writable": writable, "max_mb": self.max_bytes // (1024 * 1024), "used_bytes": self.used(),
                "volume_hint": "On Railway, attach a Volume mounted at this folder or the files disappear on the next deploy."}

    def used(self) -> int:
        return sum(f.stat().st_size for f in self.root.rglob("*") if f.is_file()) if self.root.exists() else 0

    def packs(self) -> list[dict[str, Any]]:
        out = []
        if self.root.exists():
            for d in sorted(p for p in self.root.iterdir() if p.is_dir()):
                files = [f for f in d.rglob("*") if f.is_file()]
                out.append({"name": d.name, "files": len(files), "bytes": sum(f.stat().st_size for f in files), "list": sorted(str(f.relative_to(d)).replace(os.sep, "/") for f in files)[:60]})
        return out

    def _pack_dir(self, pack: str) -> Path:
        if not PACK_RE.match(pack):
            raise VoiceError("A pack name is letters, digits, . _ - (up to 48 characters).")
        return self.root / pack

    def path_for(self, pack: str, rel: str) -> Path | None:
        try:
            d = self._pack_dir(pack)
            p = (d / clean_rel(rel)).resolve()
        except VoiceError:
            return None
        return p if d.resolve() in p.parents and p.is_file() else None

    async def save_stream(self, pack: str, rel: str, chunks: AsyncIterator[bytes]) -> int:
        d, rel = self._pack_dir(pack), clean_rel(rel)
        target = (d / rel).resolve()
        if d.resolve() not in target.parents and d.resolve() != target.parent:
            raise VoiceError("That file name is not allowed.")
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp, size, existing = target.with_name(target.name + ".part"), 0, target.stat().st_size if target.exists() else 0
        try:
            with open(tmp, "wb") as fh:
                async for chunk in chunks:
                    size += len(chunk)
                    if self.used() - existing + size > self.max_bytes:
                        raise VoiceError(f"That would pass the {self.max_bytes // 1048576} MB limit for voice files.", 413)
                    fh.write(chunk)
            tmp.replace(target)
        finally:
            tmp.unlink(missing_ok=True)
        return size

    def save_zip(self, pack: str, data: bytes) -> int:
        d = self._pack_dir(pack)
        try:
            zf = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile:
            raise VoiceError("That is not a valid zip file.") from None
        infos = [i for i in zf.infolist() if not i.is_dir()]
        if not infos or len(infos) > MAX_FILES:
            raise VoiceError(f"A zip must hold between 1 and {MAX_FILES} files.")
        if sum(i.file_size for i in infos) + self.used() > self.max_bytes:
            raise VoiceError(f"Unpacked, that would pass the {self.max_bytes // 1048576} MB limit for voice files.", 413)
        names = [clean_rel(i.filename) for i in infos]        # checks every name before anything is written
        for info, name in zip(infos, names):
            target = (d / name).resolve()
            if d.resolve() not in target.parents:
                raise VoiceError("That file name is not allowed.")
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)
        return len(infos)

    def delete(self, pack: str) -> bool:
        d = self._pack_dir(pack)
        if d.is_dir():
            shutil.rmtree(d)
            return True
        return False
