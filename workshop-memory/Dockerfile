FROM ghcr.io/home-assistant/base:latest

ARG BUILD_VERSION
ARG BUILD_ARCH

LABEL \
    io.hass.version="${BUILD_VERSION}" \
    io.hass.type="app" \
    io.hass.arch="${BUILD_ARCH}"

RUN apk add --no-cache \
    python3 \
    py3-pip

WORKDIR /app

COPY requirements.txt /app/requirements.txt

RUN python3 -m pip install \
    --no-cache-dir \
    --break-system-packages \
    -r /app/requirements.txt

COPY src /app/src
COPY config /app/config
COPY run.sh /run.sh

RUN chmod a+x /run.sh

CMD ["/run.sh"]