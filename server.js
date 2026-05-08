"use strict";

const express = require("express");
const multer  = require("multer");
const sharp   = require("sharp");
const path    = require("path");

const app    = express();
// 50 MB per file — no Vercel body-size restriction on Railway
const upload = multer({ storage: multer.memoryStorage(), limits: { fileSize: 50 * 1024 * 1024 } });

app.use(express.static(path.join(__dirname, "public")));

// ---------------------------------------------------------------------------
// POST /process  — one file per call, returns the processed file directly
// Body (multipart/form-data): file, action, format, quality, resizeMode, …
// ---------------------------------------------------------------------------
app.post("/process", upload.single("file"), async (req, res) => {
  const file    = req.file;
  const action  = req.body.action  || "convert";
  const fmt     = req.body.format  || "jpeg";
  const quality = clamp(parseInt(req.body.quality, 10) || 90, 1, 100);

  if (!file) return res.status(400).json({ error: "No file provided." });

  const ext = path.extname(file.originalname).toLowerCase();
  let pipeline = sharp(file.buffer, { failOn: "none" });
  let outName;

  try {
    if (action === "convert") {
      if (fmt === "jpeg") {
        pipeline = pipeline.flatten({ background: { r: 255, g: 255, b: 255 } })
                           .jpeg({ quality, mozjpeg: true, progressive: true });
        outName  = replaceExt(file.originalname, ".jpg");
      } else if (fmt === "png") {
        pipeline = pipeline.png({ compressionLevel: 9, adaptiveFiltering: true });
        outName  = replaceExt(file.originalname, ".png");
      } else {
        const meta = await sharp(file.buffer).metadata();
        pipeline   = meta.hasAlpha
          ? pipeline.webp({ lossless: true, effort: 6 })
          : pipeline.webp({ quality, effort: 6 });
        outName = replaceExt(file.originalname, ".webp");
      }

    } else if (action === "resize") {
      const resizeMode = req.body.resizeMode || "percent";
      const resizeFmt  = req.body.resizeFmt  || "original";
      const meta       = await sharp(file.buffer).metadata();

      if (resizeMode === "percent") {
        const pct = clamp(parseFloat(req.body.percent) || 100, 1, 2000) / 100;
        pipeline  = pipeline.resize({
          width:  Math.round((meta.width  || 100) * pct),
          height: Math.round((meta.height || 100) * pct),
          fit: "fill",
        });
      } else {
        const w    = parseInt(req.body.rWidth,  10) || null;
        const h    = parseInt(req.body.rHeight, 10) || null;
        const keep = req.body.keepAspect !== "false";
        if      (w && !h) pipeline = pipeline.resize({ width:  w, withoutEnlargement: false });
        else if (!w && h) pipeline = pipeline.resize({ height: h, withoutEnlargement: false });
        else if (w  && h) pipeline = pipeline.resize({ width: w, height: h, withoutEnlargement: false,
                                                        fit: keep ? "inside" : "fill" });
      }

      const srcFmt    = meta.format;
      const targetFmt = resizeFmt === "original"
        ? (["jpeg","png","webp"].includes(srcFmt) ? srcFmt : "jpeg")   // tiff → jpeg on resize
        : resizeFmt;

      if (targetFmt === "jpeg") {
        pipeline = pipeline.flatten({ background: { r: 255, g: 255, b: 255 } })
                           .jpeg({ quality, mozjpeg: true, progressive: true });
        outName  = replaceExt(file.originalname, ".jpg");
      } else if (targetFmt === "png") {
        pipeline = pipeline.png({ compressionLevel: 9, adaptiveFiltering: true });
        outName  = replaceExt(file.originalname, ".png");
      } else {
        pipeline = meta.hasAlpha
          ? pipeline.webp({ lossless: true, effort: 6 })
          : pipeline.webp({ quality, effort: 6 });
        outName  = replaceExt(file.originalname, ".webp");
      }

    } else {
      // optimize — keep format (tiff → converted to jpeg)
      if (ext === ".png") {
        outName  = file.originalname;
        pipeline = pipeline.png({ compressionLevel: 9, adaptiveFiltering: true, palette: false });
      } else if (ext === ".jpg" || ext === ".jpeg") {
        outName  = file.originalname;
        pipeline = pipeline.flatten({ background: { r: 255, g: 255, b: 255 } })
                           .jpeg({ quality, mozjpeg: true, progressive: true });
      } else if (ext === ".webp") {
        outName = file.originalname;
        const meta = await sharp(file.buffer).metadata();
        pipeline   = meta.hasAlpha
          ? pipeline.webp({ lossless: true, effort: 6 })
          : pipeline.webp({ quality, effort: 6 });
      } else if (ext === ".tif" || ext === ".tiff") {
        // TIFF can't stay as-is in browsers — optimize by converting to JPEG
        outName  = replaceExt(file.originalname, ".jpg");
        pipeline = pipeline.flatten({ background: { r: 255, g: 255, b: 255 } })
                           .jpeg({ quality, mozjpeg: true, progressive: true });
      } else {
        return res.status(422).json({ error: `Unsupported format for optimization: ${ext}` });
      }
    }

    let outBuf = await pipeline.toBuffer();

    // Never let optimize make the file larger
    if (action === "optimize" && outBuf.length > file.buffer.length) outBuf = file.buffer;

    res.setHeader("Content-Disposition", `attachment; filename="${outName}"`);
    res.setHeader("Content-Type", mime(outName));
    res.send(outBuf);

  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// ---------------------------------------------------------------------------

function replaceExt(filename, newExt) { return filename.replace(/\.[^.]+$/, "") + newExt; }
function clamp(v, lo, hi)             { return Math.min(hi, Math.max(lo, v)); }
function mime(filename) {
  const ext = path.extname(filename).toLowerCase();
  return { ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
           ".png": "image/png",  ".webp": "image/webp",
           ".tif": "image/tiff", ".tiff": "image/tiff" }[ext] || "application/octet-stream";
}

module.exports = app;

if (require.main === module) {
  const PORT = process.env.PORT || 3001;
  app.listen(PORT, () => console.log(`Image Batch running at http://localhost:${PORT}`));
}
