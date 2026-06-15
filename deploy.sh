#!/bin/bash
set -e

# ── Load PAT from .env ──────────────────────────────────────────
if [ -f .env ]; then
  export $(grep -E '^GITHUB_PAT=' .env | xargs)
fi

if [ -z "$GITHUB_PAT" ]; then
  echo "❌ GITHUB_PAT not found in .env"
  exit 1
fi

# ── Derive version ──────────────────────────────────────────────
# Prefer explicit version from .version file; fall back to git describe.
if [ -f .version ]; then
  VERSION=$(cat .version | tr -d ' \n')
else
  # When tags exist, git describe produces valid PEP 440 versions (e.g. v1.0.0-2-gabc123).
  # Without tags it falls back to a raw commit hash (e.g. abc123-dirty), which
  # setuptools_scm rejects.  Fall back to a default in that case.
  RAW_VERSION=$(git describe --tags --always --dirty 2>/dev/null || true)
  if echo "$RAW_VERSION" | grep -qE '^[0-9a-f]{7,}(-dirty)?$'; then
    VERSION="0.1.0"
  else
    VERSION="$RAW_VERSION"
  fi
fi

# ── Login ───────────────────────────────────────────────────────
echo "$GITHUB_PAT" | docker login ghcr.io -u x-access-token --password-stdin

# ── Build & push ────────────────────────────────────────────────
docker buildx build \
  --platform linux/amd64 \
  -t ghcr.io/neurwerk/apikey-manager:latest \
  -t ghcr.io/neurwerk/apikey-manager:"$VERSION" \
  --build-arg SETUPTOOLS_SCM_PRETEND_VERSION="$VERSION" \
  --push .

echo "✅ Pushed ghcr.io/neurwerk/apikey-manager:$VERSION"
