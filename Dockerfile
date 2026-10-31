FROM python:3.12-slim-trixie

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core libvulkan1 mesa-vulkan-drivers \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 1000 frameforge \
    && useradd --uid 1000 --gid 1000 --create-home frameforge \
    && mkdir -p /data \
    && chown 1000:1000 /data

WORKDIR /app
COPY app.py audio.py storage.py hdr.py subtitles.py auth.py scan.py naming.py VERSION ./
COPY static ./static
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 XDG_CACHE_HOME=/tmp/.cache
USER 1000:1000
EXPOSE 8765
CMD ["python", "app.py", "--host", "0.0.0.0", "--no-browser"]
