FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends git \
  && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Copy tree including .git when present (CI build context); pin script falls back to docs JSON.
COPY . .
ENV DRIFT_AUDIT=0 STUDY_ALLOW_BASELINE=1
CMD ["bash", "-lc", "pytest -q && python scripts/validate_claims.py && python scripts/eval_vignettes.py && python scripts/baseline_git_pin.py"]
