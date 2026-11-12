# Production requirements: dedicated HTTPS-ingress service, >=2 GiB RAM, current AV signatures.
# Pin this base image to an approved digest during the audited release process.
FROM python:3.13-slim-bookworm
ENV DEBIAN_FRONTEND=noninteractive PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends \
    clamav clamav-freshclam ca-certificates && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /opt/deilaw-av /var/lib/clamav \
    && chown -R clamav:clamav /opt/deilaw-av /var/lib/clamav
COPY --chown=clamav:clamav clamav_gateway.py start.sh /opt/deilaw-av/
RUN chmod 0555 /opt/deilaw-av/start.sh
USER clamav
ENV DEILAW_AV_HOST=0.0.0.0 \
    DEILAW_AV_TRUSTED_INGRESS=1 \
    DEILAW_AV_PORT=10000 \
    DEILAW_AV_DB_DIR=/var/lib/clamav \
    DEILAW_AV_MAX_SIGNATURE_HOURS=48
EXPOSE 10000
WORKDIR /opt/deilaw-av
ENTRYPOINT ["/opt/deilaw-av/start.sh"]
