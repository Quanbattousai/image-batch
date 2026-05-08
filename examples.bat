@echo off
:: Quick example usage — edit paths as needed

:: --- Convert all PNG + HEIC in a folder to JPEG (quality 90) ---
:: python app.py convert --format jpeg -o .\output\ .\my-photos\

:: --- Convert specific files to WebP ---
:: python app.py convert --format webp -o .\output\ photo1.png photo2.jpg

:: --- Optimize a folder of mixed images (overwrite originals) ---
:: python app.py optimize --in-place .\my-photos\

:: --- Optimize recursively, output to a new folder ---
:: python app.py optimize -r -o .\optimized\ .\my-photos\

:: --- JPEG optimize at quality 85 ---
:: python app.py optimize --jpeg-quality 85 .\my-photos\

echo Uncomment the example you want to run and adjust paths.
pause
