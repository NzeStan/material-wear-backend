ARG PYTHON_VERSION=3.12-slim

FROM python:${PYTHON_VERSION}

ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# libpq-dev/gcc: psycopg. libpango/libharfbuzz/libcairo2: weasyprint (PDF
# generation) — needed at runtime too, not just build time, since Django's
# admin autodiscover imports orderitem_generation.api_views (which imports
# weasyprint) on every app startup, not only during collectstatic.
RUN apt-get update && apt-get install -y \
    libpq-dev \
    gcc \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libpangocairo-1.0-0 \
    libharfbuzz-subset0 \
    libcairo2 \
    libgdk-pixbuf-2.0-0 \
    libffi-dev \
    shared-mime-info \
    libmagic1 \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /code

WORKDIR /code

COPY requirements.txt /tmp/requirements.txt
RUN set -ex && \
    pip install --upgrade pip && \
    pip install -r /tmp/requirements.txt && \
    rm -rf /root/.cache/
COPY . /code

# Build-time placeholders only — collectstatic just needs settings.py to
# import without EnvError, it never actually calls Cloudinary/Paystack/
# YouTube. Real values come from `fly secrets set ...` at runtime, which
# override these for the actual running container.
ENV DJANGO_SECRET_KEY "PjPvTf0BBMQLSmNNXR3Xl6WoKNASx7hndOkPYCwaHiojqQx1LE"
ENV CLOUDINARY_CLOUD_NAME "build-placeholder"
ENV CLOUDINARY_API_KEY "build-placeholder"
ENV CLOUDINARY_API_SECRET "build-placeholder"
ENV PAYSTACK_PUBLIC_KEY "build-placeholder"
ENV PAYSTACK_SECRET_KEY "build-placeholder"
ENV YOUTUBE_API_KEY "build-placeholder"
ENV YOUTUBE_CHANNEL_ID "build-placeholder"
RUN python manage.py collectstatic --noinput

EXPOSE 8000

# Shell form (not exec/JSON array) so $PORT actually expands — Railway
# assigns its own dynamic port at runtime; Fly sets PORT=8000 itself via
# fly.toml's [env] block, so ${PORT:-8000} keeps working there unchanged.
CMD gunicorn --bind 0.0.0.0:${PORT:-8000} --workers 2 material.wsgi
