# syntax=docker/dockerfile:1
# LoopForge sandbox image (spec 3.1). Build: docker build -t loopforge-sandbox backend/sandbox
# Generated code runs here with no network, a read-only root FS and a non-root user.
# Dependencies are fixed at build time from approved_packages.txt (Addendum 19.2); the running
# container cannot install anything.
FROM python:3.12-slim
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOME=/tmp
COPY approved_packages.txt /tmp/approved_packages.txt
RUN pip install -r /tmp/approved_packages.txt pytest-json-report==1.5.0 \
       ruff==0.8.4 bandit==1.9.4 coverage==7.17.2 \
    && rm /tmp/approved_packages.txt \
    && pip uninstall -y pip setuptools wheel \
    && rm -f /usr/bin/apt /usr/bin/apt-get /usr/bin/dpkg \
    && useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin sandbox
USER 10001:10001
WORKDIR /workspace
