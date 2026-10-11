FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
RUN groupadd --gid 10001 voc \
    && useradd --uid 10001 --gid voc --create-home voc \
    && mkdir -p /data/research-runs \
    && chown -R voc:voc /data

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py build.py cloud_app.py ./
COPY research-core/ ./research-core/
COPY examples/ ./examples/
COPY tests/ ./tests/
COPY web/ ./web/

USER voc
EXPOSE 8780
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import os; from urllib.request import urlopen; urlopen('http://127.0.0.1:'+os.environ.get('PORT','8780')+('/healthz' if os.environ.get('VOC_APP_MODE')=='cloud' else '/api/health'), timeout=2).close()"
ENTRYPOINT ["python", "app.py"]
CMD ["--host", "0.0.0.0", "--port", "8780", "--runs", "/data/research-runs"]
