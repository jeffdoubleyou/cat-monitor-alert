FROM python:3.12-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ffmpeg \
        libglib2.0-0 \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    YOLO_CONFIG_DIR=/app/.ultralytics

COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir . \
    && pip install --no-cache-dir --force-reinstall --no-deps opencv-python-headless==4.10.0.84 \
    && python -c "from ultralytics import YOLO; YOLO('yolo11n.pt')"

RUN pip uninstall -y opencv-python \
    && pip install --no-cache-dir --force-reinstall --no-deps opencv-python-headless==4.10.0.84

ENV YOLO_CONFIG_DIR=/tmp

CMD ["python", "-m", "cat_monitor"]
