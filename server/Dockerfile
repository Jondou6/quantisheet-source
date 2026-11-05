FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir "websockets>=13,<16"
COPY relay_server.py hub.py relaycore.py ./
COPY web ./web
ENV PORT=8765 DATA_DIR=/data
VOLUME /data
EXPOSE 8765
HEALTHCHECK CMD python -c "import urllib.request,os;urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8765')+'/healthz')"
CMD ["python", "relay_server.py"]
