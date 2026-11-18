FROM python:3.12-slim

# Deepnote requires bash and curl in custom images
RUN apt-get update && apt-get install -y --no-install-recommends \
    bash \
    curl && \
    rm -rf /var/lib/apt/lists/*

# Disable Deepnote constraints so we can use numpy>=2, protobuf>=6, etc.
ENV PIP_CONSTRAINT=""

# Precompile bytecode so the app doesn't pay for it on every cold start.
ENV UV_COMPILE_BYTECODE=1 UV_NO_CACHE=1

# numpy, pandas, plotly, pyarrow, ... come in through frequenz-cs-reporting
# (via frequenz-lib-notebooks), so only the overrides are pinned here.
RUN --mount=from=ghcr.io/astral-sh/uv:0.9.0,source=/uv,target=/usr/local/bin/uv \
    uv pip install --system \
    "protobuf>=6,<7" \
    "streamlit>=1.60.0, < 1.68.0" \
    "grpcio>=1.81.1,<2" \
    "frequenz-cs-reporting>=0.5.0,<0.6.0" && \
    find /usr/local/lib/python3.12/site-packages -type d \( -name tests -o -name test \) -prune -exec rm -rf {} +

# Prefer packages installed in Deepnote's venv over Deepnote's toolkit server libs.
ENV PYTHONPATH="/root/venv/lib/python3.12/site-packages:${PYTHONPATH}"
