# syntax=docker/dockerfile:1
# LoopForge Go sandbox image (Phase 16, ADR-0023). Build from backend/sandbox:
#   docker build -t loopforge-sandbox-go -f go/Dockerfile .
# Same isolation as the other images: no network, read-only root FS, non-root user. Standard library
# only (approved_modules.txt is empty). UNTESTED in this repository's CI: needs a Docker daemon with
# network at BUILD time only; see the ADR's known limits (notably: /tmp is mounted noexec, so Go's
# temp and cache directories point at /out, the writable scratch mount).
FROM golang:1.22-bookworm
ENV GOTOOLCHAIN=local GOPROXY=off GOFLAGS=-buildvcs=false CGO_ENABLED=0 \
    GOCACHE=/out/.gocache GOTMPDIR=/out HOME=/tmp
COPY go/approved_modules.txt /opt/approved_modules.txt
RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin sandbox
USER 10001:10001
WORKDIR /workspace
