#!/usr/bin/env python3
"""Batch image converter and optimizer."""

import argparse
import shutil
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Optional dependency check with helpful messages
# ---------------------------------------------------------------------------

def _require(pkg: str, import_name: str | None = None):
    import importlib
    try:
        return importlib.import_module(import_name or pkg)
    except ImportError:
        print(f"[ERROR] Missing package: {pkg}  →  pip install {pkg}", file=sys.stderr)
        sys.exit(1)


PIL_Image = None  # loaded lazily in main()

SUPPORTED_EXTENSIONS = {
    "source": {".png", ".jpg", ".jpeg", ".heic", ".heif", ".webp"},
    "png":    {".png"},
    "jpeg":   {".jpg", ".jpeg"},
    "heif":   {".heic", ".heif"},
    "webp":   {".webp"},
}

# ---------------------------------------------------------------------------
# File collection
# ---------------------------------------------------------------------------

def collect_files(inputs: list[str], recursive: bool) -> list[Path]:
    files: list[Path] = []
    for raw in inputs:
        p = Path(raw)
        if p.is_dir():
            pattern = "**/*" if recursive else "*"
            for f in sorted(p.glob(pattern)):
                if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS["source"]:
                    files.append(f)
        elif p.is_file():
            if p.suffix.lower() in SUPPORTED_EXTENSIONS["source"]:
                files.append(p)
            else:
                print(f"[SKIP] Unsupported file type: {p}", file=sys.stderr)
        else:
            print(f"[WARN] Not found: {p}", file=sys.stderr)
    return files


def make_dest(src: Path, out_dir: Path | None, new_suffix: str, in_place: bool) -> Path:
    if in_place:
        return src.with_suffix(new_suffix)
    base = out_dir or src.parent
    base.mkdir(parents=True, exist_ok=True)
    return base / (src.stem + new_suffix)

# ---------------------------------------------------------------------------
# Conversion helpers
# ---------------------------------------------------------------------------

def _open_image(path: Path):
    """Open image, registering HEIF opener if needed."""
    Image = PIL_Image
    suffix = path.suffix.lower()
    if suffix in SUPPORTED_EXTENSIONS["heif"]:
        try:
            import pillow_heif
            pillow_heif.register_heif_opener()
        except ImportError:
            print("[ERROR] HEIF support requires:  pip install pillow-heif", file=sys.stderr)
            raise
    img = Image.open(path)
    img.load()
    return img


def _to_rgb(img) -> object:
    """Ensure image is in RGB (needed for JPEG / WebP lossy)."""
    if img.mode in ("RGBA", "LA", "P"):
        bg = PIL_Image.new("RGB", img.size, (255, 255, 255))
        if img.mode == "P":
            img = img.convert("RGBA")
        if img.mode in ("RGBA", "LA"):
            bg.paste(img, mask=img.split()[-1])
        return bg
    if img.mode != "RGB":
        return img.convert("RGB")
    return img


def convert_to_jpeg(src: Path, dst: Path, quality: int) -> None:
    img = _open_image(src)
    img = _to_rgb(img)
    img.save(
        dst,
        format="JPEG",
        quality=quality,
        optimize=True,
        progressive=True,
        subsampling=0,   # 4:4:4 – best chroma quality
    )


def convert_to_webp(src: Path, dst: Path, quality: int) -> None:
    img = _open_image(src)
    # Preserve alpha channel when converting PNG→WebP
    lossless = False
    if img.mode in ("RGBA", "LA", "P") and src.suffix.lower() == ".png":
        if img.mode == "P":
            img = img.convert("RGBA")
        # Use lossless for transparency to avoid colour fringing
        img.save(dst, format="WEBP", lossless=True, method=6, quality=100)
        return
    img = _to_rgb(img)
    img.save(dst, format="WEBP", quality=quality, method=6)

# ---------------------------------------------------------------------------
# Optimisation helpers
# ---------------------------------------------------------------------------

def optimize_png(src: Path, dst: Path) -> tuple[int, int]:
    """Optimize PNG using oxipng if available, else Pillow."""
    src_size = src.stat().st_size
    try:
        import oxipng
        data = oxipng.optimize_from_memory(src.read_bytes(), level=4)
        dst.write_bytes(data)
    except ImportError:
        img = PIL_Image.open(src)
        img.save(dst, format="PNG", optimize=True, compress_level=9)
    return src_size, dst.stat().st_size


def optimize_jpeg(src: Path, dst: Path, quality: int) -> tuple[int, int]:
    """Re-save JPEG with progressive + optimize flags at the given quality."""
    src_size = src.stat().st_size
    img = PIL_Image.open(src)
    img.load()
    img = _to_rgb(img)
    img.save(
        dst,
        format="JPEG",
        quality=quality,
        optimize=True,
        progressive=True,
        subsampling=0,
    )
    # If optimized is somehow larger, keep original
    if dst.stat().st_size > src_size and src != dst:
        shutil.copy2(src, dst)
    return src_size, dst.stat().st_size


def optimize_webp(src: Path, dst: Path, quality: int) -> tuple[int, int]:
    """Re-save WebP at the given quality / lossless setting."""
    src_size = src.stat().st_size
    img = PIL_Image.open(src)
    img.load()
    has_alpha = img.mode in ("RGBA", "LA")
    if has_alpha:
        if img.mode == "LA":
            img = img.convert("RGBA")
        img.save(dst, format="WEBP", lossless=True, method=6, quality=100)
    else:
        img = _to_rgb(img)
        img.save(dst, format="WEBP", quality=quality, method=6)
    if dst.stat().st_size > src_size and src != dst:
        shutil.copy2(src, dst)
    return src_size, dst.stat().st_size

# ---------------------------------------------------------------------------
# Progress / reporting
# ---------------------------------------------------------------------------

class Reporter:
    def __init__(self, total: int):
        self.total = total
        self.done = 0
        self.errors = 0
        self.saved_bytes = 0
        self._start = time.time()

    def ok(self, src: Path, dst: Path, orig: int = 0, new: int = 0):
        self.done += 1
        delta = orig - new
        self.saved_bytes += delta
        bar = self._bar()
        size_info = (
            f"  {_fmt_size(orig)} → {_fmt_size(new)}  ({_pct(delta, orig):+.1f}%)"
            if orig else ""
        )
        print(f"  [{bar}] {self.done}/{self.total}  {src.name} → {dst.name}{size_info}")

    def fail(self, src: Path, reason: str):
        self.errors += 1
        self.done += 1
        print(f"  [ERROR] {src.name}: {reason}", file=sys.stderr)

    def summary(self):
        elapsed = time.time() - self._start
        success = self.done - self.errors
        print(f"\n  Done: {success}/{self.total} files in {elapsed:.1f}s", end="")
        if self.saved_bytes > 0:
            print(f"  |  saved {_fmt_size(self.saved_bytes)}", end="")
        elif self.saved_bytes < 0:
            print(f"  |  size increased {_fmt_size(-self.saved_bytes)}", end="")
        print()

    def _bar(self) -> str:
        width = 20
        filled = int(width * self.done / self.total)
        return "█" * filled + "░" * (width - filled)


def _fmt_size(b: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if abs(b) < 1024:
            return f"{b:.0f} {unit}"
        b /= 1024
    return f"{b:.1f} GB"


def _pct(delta: int, total: int) -> float:
    return (delta / total * 100) if total else 0.0

# ---------------------------------------------------------------------------
# Sub-commands
# ---------------------------------------------------------------------------

def cmd_convert(args) -> int:
    files = collect_files(args.inputs, args.recursive)
    if not files:
        print("[ERROR] No supported image files found.")
        return 1

    fmt = args.format
    suffix = ".jpg" if fmt == "jpeg" else f".{fmt}"
    rep = Reporter(len(files))
    print(f"\n  Converting {len(files)} file(s) to {fmt.upper()}…\n")

    for src in files:
        src_sfx = src.suffix.lower()

        # Skip: already the target format (unless --force)
        if src_sfx == suffix and not args.force:
            rep.fail(src, f"already {fmt.upper()} – use --force to re-encode")
            continue

        # Guard: heif→jpeg/webp requires pillow-heif
        if src_sfx in SUPPORTED_EXTENSIONS["heif"]:
            try:
                import pillow_heif  # noqa: F401
            except ImportError:
                rep.fail(src, "HEIF support missing – pip install pillow-heif")
                continue

        dst = make_dest(src, Path(args.output_dir) if args.output_dir else None,
                        suffix, args.in_place)
        try:
            if fmt == "jpeg":
                convert_to_jpeg(src, dst, args.quality)
            else:
                convert_to_webp(src, dst, args.quality)
            rep.ok(src, dst)
        except Exception as e:
            rep.fail(src, str(e))

    rep.summary()
    return 0 if rep.errors == 0 else 1


def cmd_optimize(args) -> int:
    files = collect_files(args.inputs, args.recursive)
    # Filter to optimizable formats
    opt_exts = SUPPORTED_EXTENSIONS["png"] | SUPPORTED_EXTENSIONS["jpeg"] | SUPPORTED_EXTENSIONS["webp"]
    files = [f for f in files if f.suffix.lower() in opt_exts]

    if not files:
        print("[ERROR] No PNG / JPEG / WebP files found.")
        return 1

    rep = Reporter(len(files))
    print(f"\n  Optimizing {len(files)} file(s)…\n")

    for src in files:
        suffix = src.suffix.lower()
        dst = make_dest(src, Path(args.output_dir) if args.output_dir else None,
                        suffix, args.in_place)
        try:
            if suffix == ".png":
                orig, new = optimize_png(src, dst)
            elif suffix in (".jpg", ".jpeg"):
                orig, new = optimize_jpeg(src, dst, args.jpeg_quality)
            else:  # .webp
                orig, new = optimize_webp(src, dst, args.webp_quality)
            rep.ok(src, dst, orig, new)
        except Exception as e:
            rep.fail(src, str(e))

    rep.summary()
    return 0 if rep.errors == 0 else 1

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="imgbatch",
        description="Batch image converter and optimizer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Convert all PNG/HEIF in a folder to JPEG (quality 90)
  python app.py convert --format jpeg ./photos/

  # Convert specific files to WebP, write to ./out/
  python app.py convert --format webp -o ./out/ img1.png img2.heic

  # Optimize a folder of mixed PNG/JPEG/WebP (overwrite originals)
  python app.py optimize --in-place ./photos/

  # Optimize recursively, output to ./optimized/
  python app.py optimize -r -o ./optimized/ ./photos/
        """,
    )

    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument("inputs", nargs="+", metavar="FILE_OR_DIR",
                        help="Files or directories to process")
    shared.add_argument("-o", "--output-dir", metavar="DIR",
                        help="Write output files here (default: same dir as source)")
    shared.add_argument("--in-place", action="store_true",
                        help="Overwrite source files (ignored if --output-dir given)")
    shared.add_argument("-r", "--recursive", action="store_true",
                        help="Search directories recursively")

    sub = p.add_subparsers(dest="command", required=True)

    # ---- convert ----
    cv = sub.add_parser("convert", parents=[shared],
                        help="Convert image format",
                        formatter_class=argparse.RawDescriptionHelpFormatter,
                        description="""
Convert images between formats:
  png  → jpeg
  heif → jpeg
  png  → webp
  jpeg → webp
        """)
    cv.add_argument("-f", "--format", choices=["jpeg", "webp"], required=True,
                    help="Target format")
    cv.add_argument("-q", "--quality", type=int, default=90, metavar="1-100",
                    help="Output quality 1-100 (default: 90)")
    cv.add_argument("--force", action="store_true",
                    help="Re-encode even if already the target format")
    cv.set_defaults(func=cmd_convert)

    # ---- optimize ----
    op = sub.add_parser("optimize", parents=[shared],
                        help="Optimize PNG / JPEG / WebP files",
                        formatter_class=argparse.RawDescriptionHelpFormatter,
                        description="""
Optimize images with maximum quality preservation:
  PNG  – lossless recompression via oxipng (if installed) or Pillow
  JPEG – progressive + optimize re-save
  WebP – method-6 re-save (lossless when alpha channel present)
        """)
    op.add_argument("--jpeg-quality", type=int, default=90, metavar="1-100",
                    help="JPEG re-save quality (default: 90)")
    op.add_argument("--webp-quality", type=int, default=90, metavar="1-100",
                    help="WebP re-save quality (default: 90)")
    op.set_defaults(func=cmd_optimize)

    return p


def main():
    global PIL_Image
    _require("Pillow", "PIL")
    from PIL import Image  # noqa: PLC0415
    PIL_Image = Image

    parser = build_parser()
    args = parser.parse_args()

    # Validate quality ranges
    for attr in ("quality", "jpeg_quality", "webp_quality"):
        val = getattr(args, attr, None)
        if val is not None and not (1 <= val <= 100):
            parser.error(f"Quality must be between 1 and 100, got {val}")

    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
