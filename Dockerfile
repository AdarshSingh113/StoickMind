# One image for everything the outside world talks to: API, webhooks, website widget AND the React dashboard.
# Stage 1 builds the React app with Node; stage 2 is a slim Python image that serves it (Node isn't shipped).

FROM node:22-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json frontend/.npmrc ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 KOTLER_PRODUCTION=1
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY kotler/ kotler/
COPY --from=frontend /app/frontend/dist frontend/dist
# Runs as a normal user, not root.
RUN useradd --create-home kotler && mkdir -p data && chown -R kotler data
USER kotler
EXPOSE 8000
CMD ["sh", "-c", "uvicorn kotler.server:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers"]
