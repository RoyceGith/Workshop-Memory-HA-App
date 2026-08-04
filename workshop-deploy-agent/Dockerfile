FROM ghcr.io/home-assistant/base:latest

ARG BUILD_VERSION
ARG BUILD_ARCH

LABEL \
    io.hass.version="${BUILD_VERSION}" \
    io.hass.type="addon" \
    io.hass.arch="${BUILD_ARCH}"

RUN apk add --no-cache \
    git \
    openssh-client \
    python3

COPY run.sh /run.sh

RUN chmod a+x /run.sh

CMD ["/run.sh"]
