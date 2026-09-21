# Production image for the AI Receptionist (Flask + Gunicorn).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_ENV=production \
    PORT=5000

WORKDIR /app

# Install dependencies first for better layer caching.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application. Local databases, .env, and secrets are excluded via
# .dockerignore so they never enter the image.
COPY . .

# Run as a non-root user.
RUN useradd --create-home --uid 10001 appuser \
    && chmod +x /app/docker-entrypoint.sh \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 5000

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["gunicorn", "-c", "gunicorn.conf.py", "wsgi:app"]
