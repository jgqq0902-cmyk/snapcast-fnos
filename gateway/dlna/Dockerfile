FROM debian:trixie-slim

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        mpd \
        procps \
        supervisor \
    && install -d -m 0755 /usr/share/keyrings \
    && curl -fsSL https://www.lesbonscomptes.com/pages/lesbonscomptes.gpg \
        -o /usr/share/keyrings/lesbonscomptes.gpg \
    && curl -fsSL https://www.lesbonscomptes.com/upmpdcli/pages/upmpdcli-trixie.sources \
        -o /etc/apt/sources.list.d/upmpdcli.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends upmpdcli \
    && rm -rf /var/lib/apt/lists/*

COPY mpd.conf /etc/mpd.conf
COPY upmpdcli.conf /etc/upmpdcli.conf
COPY supervisord.conf /etc/supervisor/supervisord.conf
COPY entrypoint.sh /usr/local/bin/snapcast-dlna-entrypoint
COPY upmpdcli-entrypoint.sh /usr/local/bin/snapcast-upmpdcli-entrypoint

RUN chmod 0755 /usr/local/bin/snapcast-dlna-entrypoint /usr/local/bin/snapcast-upmpdcli-entrypoint

ENTRYPOINT ["/usr/local/bin/snapcast-dlna-entrypoint"]
