FROM python:3.12.9-slim

RUN groupadd -r app && useradd -r -g app -d /app app

WORKDIR /app

COPY dashboard/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY dashboard/ dashboard/

USER app

EXPOSE 8504

CMD ["streamlit", "run", "dashboard/app.py", \
     "--server.port", "8504", \
     "--server.address", "0.0.0.0", \
     "--server.headless", "true", \
     "--server.baseUrlPath", "/dashboard", \
     "--browser.gatherUsageStats", "false"]
