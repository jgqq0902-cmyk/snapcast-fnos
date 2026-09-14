FROM python:3.13-alpine

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CONTROL_PORT=8080 \
    SNAPSERVER_RPC_URL=http://snapserver:1780/jsonrpc \
    MPD_SOCKET=/data/dlna/mpd.sock

WORKDIR /app

COPY app.py /app/app.py
COPY static /app/static
RUN chmod -R a+rX /app

EXPOSE 8080

CMD ["python3", "/app/app.py"]
