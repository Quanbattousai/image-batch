"""Flask web interface for the image batch converter/optimizer."""

import io
import zipfile
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_file

import app as core  # reuse all conversion/optimization logic

# Pillow must be loaded before using core helpers
from PIL import Image
core.PIL_Image = Image

UPLOAD_LIMIT_MB = 100
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = UPLOAD_LIMIT_MB * 1024 * 1024


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _process_file(file_bytes: bytes, filename: str, action: str,
                  fmt: str, quality: int) -> tuple[bytes, str]:
    """Process a single in-memory file. Returns (result_bytes, out_filename)."""
    suffix = Path(filename).suffix.lower()

    # Write upload to a temp buffer via BytesIO for Pillow
    src_buf = io.BytesIO(file_bytes)

    if action == "convert":
        out_suffix = ".jpg" if fmt == "jpeg" else ".webp"
        out_buf = io.BytesIO()
        img = _open_from_bytes(src_buf, suffix)
        if fmt == "jpeg":
            img = core._to_rgb(img)
            img.save(out_buf, format="JPEG", quality=quality,
                     optimize=True, progressive=True, subsampling=0)
        else:
            has_alpha = img.mode in ("RGBA", "LA", "P")
            if has_alpha:
                if img.mode == "P":
                    img = img.convert("RGBA")
                elif img.mode == "LA":
                    img = img.convert("RGBA")
                img.save(out_buf, format="WEBP", lossless=True, method=6, quality=100)
            else:
                img = core._to_rgb(img)
                img.save(out_buf, format="WEBP", quality=quality, method=6)
        out_name = Path(filename).stem + out_suffix
        return out_buf.getvalue(), out_name

    else:  # optimize
        out_buf = io.BytesIO()
        if suffix == ".png":
            try:
                import oxipng
                data = oxipng.optimize_from_memory(file_bytes, level=4)
                return data, filename
            except ImportError:
                img = Image.open(src_buf)
                img.save(out_buf, format="PNG", optimize=True, compress_level=9)
        elif suffix in (".jpg", ".jpeg"):
            img = Image.open(src_buf)
            img.load()
            img = core._to_rgb(img)
            img.save(out_buf, format="JPEG", quality=quality,
                     optimize=True, progressive=True, subsampling=0)
            # If larger, return original
            if len(out_buf.getvalue()) > len(file_bytes):
                return file_bytes, filename
        else:  # webp
            img = Image.open(src_buf)
            img.load()
            if img.mode in ("RGBA", "LA"):
                if img.mode == "LA":
                    img = img.convert("RGBA")
                img.save(out_buf, format="WEBP", lossless=True, method=6, quality=100)
            else:
                img = core._to_rgb(img)
                img.save(out_buf, format="WEBP", quality=quality, method=6)
            if len(out_buf.getvalue()) > len(file_bytes):
                return file_bytes, filename
        return out_buf.getvalue(), filename


def _open_from_bytes(buf: io.BytesIO, suffix: str):
    if suffix in core.SUPPORTED_EXTENSIONS["heif"]:
        try:
            import pillow_heif
            pillow_heif.register_heif_opener()
        except ImportError:
            raise ValueError("HEIF support requires: pip install pillow-heif")
    img = Image.open(buf)
    img.load()
    return img


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/process", methods=["POST"])
def process():
    files = request.files.getlist("files")
    action  = request.form.get("action", "convert")       # convert | optimize
    fmt     = request.form.get("format", "jpeg")           # jpeg | webp
    quality = int(request.form.get("quality", 90))

    if not files or all(f.filename == "" for f in files):
        return jsonify(error="No files uploaded."), 400

    results: list[tuple[str, bytes]] = []
    errors:  list[str] = []

    for f in files:
        if not f.filename:
            continue
        suffix = Path(f.filename).suffix.lower()
        allowed = core.SUPPORTED_EXTENSIONS["source"]
        if suffix not in allowed:
            errors.append(f"{f.filename}: unsupported format")
            continue
        try:
            data, out_name = _process_file(f.read(), f.filename, action, fmt, quality)
            results.append((out_name, data))
        except Exception as e:
            errors.append(f"{f.filename}: {e}")

    if not results:
        return jsonify(error="No files could be processed.", details=errors), 422

    # Single file → return directly
    if len(results) == 1:
        name, data = results[0]
        mime = _mime(name)
        return send_file(io.BytesIO(data), mimetype=mime,
                         as_attachment=True, download_name=name)

    # Multiple files → zip
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in results:
            zf.writestr(name, data)
    zip_buf.seek(0)
    return send_file(zip_buf, mimetype="application/zip",
                     as_attachment=True, download_name="processed_images.zip")


def _mime(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    return {"jpg": "image/jpeg", ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg", ".png": "image/png",
            ".webp": "image/webp"}.get(ext, "application/octet-stream")


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(debug=True, port=5000)
