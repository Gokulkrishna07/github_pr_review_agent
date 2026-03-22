FROM python:3.12.9-slim

RUN groupadd -r app && useradd -r -g app -d /app app

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . agent/

RUN mkdir -p /app/data && chown app:app /app/data

USER app

EXPOSE 8000

CMD ["uvicorn", "agent.agent:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
