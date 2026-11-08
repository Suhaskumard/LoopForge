# syntax=docker/dockerfile:1
# LoopForge Node sandbox image (Phase 8, ADR-0015). Build from backend/sandbox:
#   docker build -t loopforge-sandbox-node -f node/Dockerfile .
# Same isolation as the Python image: no network, read-only root FS, non-root user. Packages are
# fixed at build time from approved_packages_js.txt; npm is removed so the container cannot install.
FROM node:20-slim
ENV HOME=/tmp NODE_ENV=test NODE_PATH=/usr/local/lib/node_modules \
    NPM_CONFIG_UPDATE_NOTIFIER=false
COPY node/approved_packages_js.txt /tmp/approved_packages_js.txt
RUN grep -v '^#' /tmp/approved_packages_js.txt | grep . | sed 's/==/@/' | xargs npm install -g --no-fund --no-audit \
    && rm -rf /tmp/approved_packages_js.txt /root/.npm \
    && rm -rf /usr/local/lib/node_modules/npm /usr/local/bin/npm /usr/local/bin/npx /usr/local/bin/corepack \
    && useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin sandbox
USER 10001:10001
WORKDIR /workspace
