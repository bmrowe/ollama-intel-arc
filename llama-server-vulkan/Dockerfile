# llama.cpp's official Vulkan server image with Mesa from the kisak PPA.
# On an Arc A380, Mesa 26.2 generated text ~22% faster than Ubuntu 26.04's Mesa 26.0.
ARG BASE_IMAGE=ghcr.io/ggml-org/llama.cpp:server-vulkan
FROM ${BASE_IMAGE}

ARG BASE_DIGEST=unknown
LABEL org.opencontainers.image.source="https://github.com/bmrowe/ollama-intel-arc" \
      org.opencontainers.image.description="llama.cpp server-vulkan with kisak Mesa" \
      io.github.bmrowe.base-digest="${BASE_DIGEST}"

RUN apt-get update \
 && apt-get install -y --no-install-recommends software-properties-common gpg-agent \
 && add-apt-repository -y ppa:kisak/kisak-mesa \
 && apt-get update \
 && apt-get install -y --no-install-recommends mesa-vulkan-drivers libvulkan1 \
 && apt-get purge -y software-properties-common gpg-agent \
 && apt-get autoremove -y \
 && rm -rf /var/lib/apt/lists/* \
 && dpkg -l mesa-vulkan-drivers | grep -q kisak
