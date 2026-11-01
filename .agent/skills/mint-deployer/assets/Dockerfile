FROM python:3.11-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
ARG GIT_SHA=dev
ENV GIT_SHA=${GIT_SHA}
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .
RUN useradd -m app && chown -R app /app
USER app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
# The Playwright worker (S10) gets its own Dockerfile based on mcr.microsoft.com/playwright/python.
