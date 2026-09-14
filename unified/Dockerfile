FROM ghcr.io/firefrei/snapcast/server:latest

USER root

RUN apk add --no-cache \
        --repository=https://dl-cdn.alpinelinux.org/alpine/edge/main \
        --repository=https://dl-cdn.alpinelinux.org/alpine/edge/community \
        mpd \
        py3-mutagen \
        upmpdcli

COPY unified /app/unified
COPY control/app.py /app/control/app.py
COPY control/static /app/control/static

RUN chmod 0755 /app/unified/entrypoint.sh /app/unified/healthcheck.sh \
        /app/unified/shairport-entrypoint.sh /app/unified/snapserver-entrypoint.sh \
        /app/unified/upmpdcli-entrypoint.sh /app/unified/verify_upnp_next.py \
    && chmod -R a+rX /app/control /app/unified

USER root

HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=12 \
    CMD ["/bin/sh", "/app/unified/healthcheck.sh"]

ENTRYPOINT ["/bin/sh", "/app/unified/entrypoint.sh"]
