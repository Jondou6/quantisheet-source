# QuantiSheet Back Office self-service server: its OWN service and volume.
# Build from the QuantiSheet folder (the image needs only the package):
#   docker build -f quantisheet_backoffice/server/deploy/Dockerfile -t qsbo-server .
FROM python:3.12-slim
RUN pip install --no-cache-dir "cryptography>=42" "waitress>=3"
WORKDIR /srv
COPY quantisheet_backoffice/__init__.py quantisheet_backoffice/security.py quantisheet_backoffice/clock.py ./quantisheet_backoffice/
COPY quantisheet_backoffice/server ./quantisheet_backoffice/server
ENV QSBO_SERVER_DATA=/data
VOLUME /data
EXPOSE 8080
# QSBO_OFFICE_TOKEN (24+ random characters) and QSBO_SERVER_KEY (a Fernet
# key) come from the host's secret store, never from this file.
CMD ["waitress-serve", "--listen=0.0.0.0:8080", "--call", "quantisheet_backoffice.server.app:create_app"]
