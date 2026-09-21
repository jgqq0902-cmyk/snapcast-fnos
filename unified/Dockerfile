FROM ghcr.io/firefrei/snapcast/server@sha256:75fac528c0a6a6bc49b3ffde338bfaf34f8066827a62ab543eca437a36ad02be

USER root

RUN apk add --no-cache \
        --repository=https://mirrors.tuna.tsinghua.edu.cn/alpine/edge/main \
        --repository=https://mirrors.tuna.tsinghua.edu.cn/alpine/edge/community \
        mpd=0.24.15-r0 \
        mympd=25.3.0-r0 \
        nginx=1.30.4-r3 \
        upmpdcli=1.9.17-r1 \
    && apk info -v mpd mympd nginx upmpdcli

COPY unified /app/unified
COPY control/app.py /app/control/app.py
COPY control/static /app/control/static

RUN chmod 0755 /app/unified/entrypoint.sh /app/unified/healthcheck.sh \
        /app/unified/drop-airplay-session.sh \
        /app/unified/mympd-init.sh \
        /app/unified/shairport-entrypoint.sh /app/unified/snapserver-entrypoint.sh \
        /app/unified/upmpdcli-entrypoint.sh /app/unified/smoke-test.sh \
        /app/unified/verify_discovery.py /app/unified/gateway-integration-test.py \
    && chmod -R a+rX /app/control /app/unified

USER root

HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=12 \
    CMD ["/bin/sh", "/app/unified/healthcheck.sh"]

ENTRYPOINT ["/bin/sh", "/app/unified/entrypoint.sh"]
