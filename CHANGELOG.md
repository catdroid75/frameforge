# Changelog

## 0.9.0-beta.7 — 2026-10-31

- Make the _converted suffix optional for filenames that are not cleaned.
- Add SRT text subtitle sidecar exports with individual/all/forced selection, staged publication and collision-safe matching video basenames.
- Add sampled interlace/repeated-field detection, BWDIF/YADIF frame or bob deinterlacing, and manual field matching / 3:2 inverse telecine.
- Detect movie-like names and TV episode markers before cleanup; add TV styles, episode-title/year toggles, series/season folders and an authenticated naming preview.
- Save all new settings with presets, preserve _FFtmp staging, and report detection/export results in the queue.


## 0.9.0-beta.6 — 2026-10-28

- Keep encoded media and subtitle preparation files inside an _FFtmp directory in the destination root, then publish completed files into final directories.
- Monitor staging disk space and exclude this _FFtmp directory from folder scans.


## 0.9.0-beta.5 — 2026-10-28

- Stage encoded media and subtitle preparation files in the selected destination root, even with per-movie output folders; publish completed files into their final directories.
- Add optional source-relative directory mirroring for recursive batches, combinable with per-movie folders and saved presets.
- Redesign the desktop workspace with a wider editor, integrated batch presets, persistent queue sidebar and sticky queue action bar.
- Restore the Smaller MP4 quick-preset option lost to malformed HTML in the earlier interface.


## 0.9.0-beta.4 — 2026-10-27

- Lower the minimum login token length from 24 to 12 characters; update startup validation and deployment instructions.


## 0.9.0-beta.3 — 2026-10-27

- Replace the username/password login with a single secret login token, configured using FRAMEFORGE_AUTH_TOKEN.
- Remove the username/password environment variables from deployment files and migrate stored credentials after token setup.
- Retain hashed secret storage, session expiry, sign-out, login throttling and authenticated page/API protection.
- Preserve the current logo, SMTP configuration and user-confirmed NVENC status.


## 0.9.0-beta.2 — 2026-10-27

- Add mandatory single-user login covering the app, filesystem browser, settings and conversion APIs, with logout, expiring sessions, login throttling and persistent salted password hashes.
- Add login environment variables and authenticated deployment instructions; keep the full SMTP environment setup and current FrameForge logo.
- Advance the 0.9.0-beta release series for this security addition; tag Compose builds with the application version.
- Record NVENC encoding as confirmed working by the user on their target system. This confirmation does not assert testing of every GPU, codec, simultaneous-session limit or Dolby Vision path.


## 0.9.0-beta.1 — 2026-10-27

First explicitly versioned release. Earlier downloadable builds were unversioned.

- Restore the FrameForge name throughout the interface, startup messages, and email notifications.
- Introduce a modern geometric video-frame/play logo using the existing orange, amber, and charcoal palette; shared transparent artwork supports both themes.
- Add a single VERSION source, browser version badge/title, API version, and `python app.py --version`.
- Include the version in Docker builds and document versioned image/archive names.
- Carry forward batch conversion, NVENC controls, HDR conversion, post-crop subtitle burn-in, per-track audio outputs, queue safeguards, saved presets, CPU/GPU concurrency controls, and complete SMTP environment configuration.

Historical beta.1 status: NVIDIA encoding was pending target validation at that release. NVENC has since been confirmed by the user for beta.2. Docker startup in this environment, Vulkan and Dolby Vision rendering remain unverified. This release does not claim full Dolby Vision enhancement-layer reconstruction.
