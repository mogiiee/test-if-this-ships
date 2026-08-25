FROM python:3.14-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8787

COPY pyproject.toml ./
COPY groundskeeper ./groundskeeper
COPY context ./context

RUN pip install --no-cache-dir -e .

EXPOSE 8787

CMD ["python", "-m", "groundskeeper"]
