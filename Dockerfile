FROM node:20-bookworm-slim

# Install system libvips with full HEIF/HEVC support (libde265 = HEVC decoder)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    python3 \
    pkg-config \
    libvips-dev \
    libheif-dev \
    libde265-dev \
    libx265-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY package*.json ./

# Build Sharp from source so it links against the system libvips above
# (the prebuilt binary bundles its own libvips without HEVC support)
RUN npm_config_build_from_source=true npm ci --omit=dev

COPY . .

EXPOSE 3001
ENV PORT=3001

CMD ["node", "server.js"]
