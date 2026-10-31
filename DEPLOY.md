# Deploy FrameForge 0.9.0-beta.8

1. Extract this complete build on your Docker host. Keep your existing `data` folder and private `.env`.
2. Copy `.env.example` to `.env` only for a new installation. In an existing `.env`, add a random `FRAMEFORGE_AUTH_TOKEN` of at least 12 characters, and `FRAMEFORGE_COOKIE_SECURE=false` for local HTTP. Retain all `FRAMEFORGE_SMTP_*` values. Remove the old `FRAMEFORGE_AUTH_USERNAME` and `FRAMEFORGE_AUTH_PASSWORD` variables. Keep the login token separate from your email app password.
3. Run `docker compose up -d --build`; for NVIDIA use `docker compose -f compose.yaml -f compose.nvidia.yaml up -d --build`.
4. Open `http://localhost:8765` and enter your login token. For another port, set `FRAMEFORGE_PORT` before rebuilding/recreating.

## Portainer

Build on the Docker endpoint host first:

```sh
docker build -t frameforge:0.9.0-beta.8 .
```

Create/update a Portainer Stack using the supplied `compose.yaml`. When deploying through the web editor, remove `build: .` because the image is already built; retain `image: frameforge:0.9.0-beta.8`. Use absolute host paths for `INPUT_DIR`, `OUTPUT_DIR`, and `DATA_DIR`. Set the login and SMTP variables in the stack environment editor, never in a shared Compose file. Include the NVIDIA overlay's device reservation and environment fields for GPU mode. Portainer Stack environment values must be set explicitly; a `.env` on the endpoint host is not automatically imported by the web editor. Use a standalone Docker endpoint for this Compose workflow, not Docker Swarm.

The default published port is bound to the endpoint's loopback address. Access it using an SSH tunnel (`ssh -L 8765:127.0.0.1:8765 user@docker-host`), or use an HTTPS reverse proxy with a deliberate private network connection to the container. For HTTPS, set `FRAMEFORGE_COOKIE_SECURE=true` and `FRAMEFORGE_ORIGINS=https://your-frameforge-host` and preserve the Host header. Change the network/port mapping only as required for that proxy. Redeploy the stack after changes.

After first login setup, a salted token hash persists in `DATA_DIR`. You may remove the plaintext environment login token and redeploy. To reset it later, set a new `FRAMEFORGE_AUTH_TOKEN` and restart. Preserve `DATA_DIR` on each upgrade. All conversion settings remain available, including the movie folders, metadata titles, themes, Admin tab and per-track settings.

NVENC encoding is confirmed working by the user. Docker startup and GPU session limits must be verified on the deployment host; no image binary or registry push is included in this source build.
