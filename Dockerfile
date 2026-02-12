FROM python:3.12-slim

# Make sure bash, curl, and git exist (Deepnote requirement + your request)
RUN apt-get update && apt-get install -y --no-install-recommends \
    bash \
    curl \
    git && \
    rm -rf /var/lib/apt/lists/*

# Disable Deepnote constraints so we can use numpy>=2, protobuf>=6, etc.
ENV PIP_CONSTRAINT=""

# Upgrade pip
RUN pip install --no-cache-dir --upgrade pip

# Install protobuf 6, streamlit, and all your dependencies
RUN pip install --no-cache-dir \
    "protobuf>=6,<7" \
    "streamlit" \
    "typing-extensions>=4.12.2,<5" \
    "numpy>=2.3.1,<3" \
    "pandas>=2.3.1,<3" \
    "pyarrow>=20.0.0,<23.0.0" \
    "matplotlib>=3.9.2,<3.11.0" \
    "pvlib>=0.13.0,<0.14.0" \
    "python-dotenv>=0.21.0,<1.3.0" \
    "toml>=0.10.2,<0.11.0" \
    "marshmallow-dataclass>=8.7.1,<9" \
    "plotly>=6.0.0,<6.4.0" \
    "kaleido>=0.2.1,<1.2.0" \
    "marshmallow>=4.1.0,<5"
