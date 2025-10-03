FROM ghcr.io/astral-sh/uv:python3.12-trixie-slim

WORKDIR /app

ENV PYTHONPATH=/app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    --no-install-recommends \
    gcc \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*


ENV PYTHONPATH=/app \
    CHAINLIT_APP_ROOT=/app/breba_app

# Leverage Docker layer cache: copy lockfiles first, then sync env
#    (uv will create .venv in /app)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev


# Copy the entire app into the image
COPY breba_app ./breba_app
# Public direcotry is used by chainlit to get files. Needs to be on the level of working directory
COPY breba_app/public ./public
COPY breba_app/.chainlit ./.chainlit
COPY breba_app/chainlit.md ./chainlit.md


# Non-root user
RUN groupadd -r appuser && useradd -r -g appuser appuser \
 && chown -R appuser:appuser /app
USER appuser


# Command to run the app with uvicorn
CMD ["/app/.venv/bin/python", "breba_app/main.py"]

EXPOSE 8080
