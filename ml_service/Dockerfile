FROM python:3.11-slim

WORKDIR /srv

COPY requirements.txt .
# PyPI's default "torch" build bundles ~1.5GB of nvidia-* CUDA packages this
# service never uses (it runs on CPU only, inside this plain python:3.11-slim
# container with no GPU). Installing the official CPU-only build first
# satisfies the same torch>=2.4.1 requirement from requirements.txt (left
# untouched) without pulling in CUDA.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY data ./data

# The model file is mounted from the repo's single authoritative model/
# directory (see docker-compose.yml) rather than copied into the image, so
# there is exactly one copy of the artifact on disk.
ENV MODEL_PATH=/model/hybrid_ensemble_model.pkl

EXPOSE 8001
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
