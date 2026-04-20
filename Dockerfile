FROM python:3.12-slim AS base

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf2.0-0 \
    libffi-dev \
    libcairo2 \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd -r crm && useradd -r -g crm -d /app -s /sbin/nologin crm

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN chown -R crm:crm /app
USER crm

EXPOSE 5000

CMD ["gunicorn", \
     "--workers", "3", \
     "--bind", "0.0.0.0:5000", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "--timeout", "120", \
     "bridge_crm.wsgi:app"]
