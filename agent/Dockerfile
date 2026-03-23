FROM python:3.12.9-slim

RUN groupadd -r app && useradd -r -g app -d /app app

WORKDIR /app

COPY agent/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY agent/ agent/
COPY dashboard/ dashboard/

RUN mkdir -p /app/data && chown app:app /app/data

COPY agent/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

USER app

EXPOSE 8000 8504

ENTRYPOINT ["/app/entrypoint.sh"]
