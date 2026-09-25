FROM python:3.11-slim

WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# The model file is mounted from the repo's single authoritative model/
# directory (see docker-compose.yml) rather than copied into the image, so
# there is exactly one copy of the artifact on disk.
ENV MODEL_PATH=/model/hybrid_ensemble_model.pkl

EXPOSE 8001
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
