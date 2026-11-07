# One headless Nidhogg instance per container.
#
# Base image choice: Debian slim, NOT Alpine. Proton (and every Proton-GE build) is linked
# against glibc; Alpine is musl. Running Proton there needs gcompat/Steam-runtime shims, and
# the failure modes we already debugged (DXVK init, prefix creation) become much harder to
# read. Debian gives us the same stack that is validated on the dev machine, so a container
# failure is a real failure and not a libc artefact.
FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      xvfb xdotool ffmpeg \
      python3 python3-numpy \
      ca-certificates curl xz-utils bzip2 tar \
      gcc libc6-dev make \
      libvulkan1 mesa-vulkan-drivers vulkan-tools \
      libgl1 libglx-mesa0 libegl1 libgles2 \
      libx11-6 libxext6 libxrandr2 libxi6 libxcursor1 libxinerama1 libxcomposite1 \
      libxkbcommon0 libfreetype6 fonts-dejavu-core \
      libasound2 libpulse0 \
   && rm -rf /var/lib/apt/lists/*

# Proton-GE is fetched at build time (pin GE_VERSION for reproducibility).
ARG GE_VERSION=GE-Proton9-20
RUN mkdir -p /opt/proton /opt/cache \
 && curl -fsSL -o /opt/cache/ge.tar.gz \
      "https://github.com/GloriousEggroll/proton-ge-custom/releases/download/${GE_VERSION}/${GE_VERSION}.tar.gz" \
 && tar -xzf /opt/cache/ge.tar.gz -C /opt/proton --strip-components=1 \
 && rm -f /opt/cache/ge.tar.gz \
 && test -x /opt/proton/proton

# The game is NOT baked in: it is mounted at /game (licence + 169 MB + we want a writable copy
# per instance). Entry script copies it to a writable dir before launching.
COPY docker/entry.sh /usr/local/bin/entry.sh
RUN chmod +x /usr/local/bin/entry.sh

ENV NID_PROTON=/opt/proton/proton \
    NID_GAME_DIR=/game \
    STEAM_COMPAT_CLIENT_INSTALL_PATH=/opt/steamroot \
    DISPLAY=:0 \
    PROTON_NO_ESYNC=0

WORKDIR /repo
ENTRYPOINT ["/usr/local/bin/entry.sh"]
