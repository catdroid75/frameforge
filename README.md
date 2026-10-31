# FrameForge

Current release: **0.9.0.10**. See [CHANGELOG.md](CHANGELOG.md).

A local batch video converter with a browser interface. **No pip packages, npm packages, build tools, CDN scripts, external accounts, or uploads.** Runtime dependencies: Python 3.10+ and FFmpeg with ffprobe on PATH. Conversion works offline. Optional email notifications use your configured SMTP server. Named presets and mail configuration use SQLite, included with Python.

## Token login setup

The login page has one field: **Login token**. There is no username or login password. Set this before the first launch:

```dotenv
FRAMEFORGE_AUTH_TOKEN=your-random-token-at-least-12-characters
FRAMEFORGE_COOKIE_SECURE=false
```

Generate a random token on your own computer with `python -c "import secrets; print(secrets.token_urlsafe(32))"` and keep it in your password manager. Use the generated value in your private Docker `.env`, Portainer stack environment, or standalone process environment. The standalone launcher does not automatically load `.env`. On PowerShell, set `$env:FRAMEFORGE_AUTH_TOKEN = "your-token"` before running `python app.py`. An interactive first launch can also prompt for a token with confirmation; unattended startup without a token or saved token hash exits without starting the server.

For upgrades from beta.2, remove `FRAMEFORGE_AUTH_USERNAME` and `FRAMEFORGE_AUTH_PASSWORD` and set the new `FRAMEFORGE_AUTH_TOKEN`. The old username/password settings are ignored and their stored account record is removed after successful token setup. Existing conversion presets and SMTP settings stay intact. This login token is separate from the SMTP email password, which is still used for sending email.

Only a salted PBKDF2-SHA256 hash (600,000 iterations) is stored in the existing data database. No plaintext login token is stored there or returned by the API. After setup, you may remove `FRAMEFORGE_AUTH_TOKEN` from the environment and reuse the saved hash. To change/reset the token, set a new environment token and restart, then remove the environment value if desired. Keep the data volume private and preserve it during updates.

Entering the token creates an HttpOnly, SameSite=Strict session cookie. The token is not put in URLs, browser local storage, or session storage. Sessions expire after eight hours and on server restart. **Sign out** revokes the current session without stopping the queue. Login attempts are limited to five per client address per minute. Host/Origin and write-token checks remain enabled; the browser write token is separate from your secret login token.

For access beyond loopback, use an HTTPS reverse proxy, set `FRAMEFORGE_COOKIE_SECURE=true`, and set `FRAMEFORGE_ORIGINS` to the exact HTTPS browser origin(s), without trailing slashes. Forward the original Host header. Reverse-proxy clients share the proxy's login rate limit. Default Compose port binding remains local-only; token login does not encrypt HTTP. `/healthz` is intentionally public and returns only a basic health result.

## Start with Docker Compose

Docker installs Python, FFmpeg, a basic DejaVu font, and a Vulkan loader/software driver inside the image; you do not need them installed on the host. Install Docker Engine with the Compose plugin, or Docker Desktop configured for Linux containers.

1. Extract the entire archive. Open a terminal in the `frameforge` folder (the one containing `compose.yaml` and `Dockerfile`).
2. Put videos in the included `input` folder. Converted files go to the included `output` folder. To use other folders, copy `.env.example` to `.env` and set `INPUT_DIR` and `OUTPUT_DIR` to existing absolute paths. On Windows use forward slashes, e.g. `D:/Videos` and `D:/Converted`.
3. On Linux, set `FRAMEFORGE_UID` and `FRAMEFORGE_GID` in `.env` to your user/group IDs (`id -u` and `id -g`). That user must be able to read the input files and write the output and data folders. Create input, output and data host folders before startup; otherwise Docker may create root-owned folders. Docker Desktop users can normally keep the default IDs.
4. Run:

   ```sh
   docker compose up -d --build
   ```

5. Open **http://localhost:8765** (or **http://127.0.0.1:8765**). The file picker starts in `/input`; save destination defaults to `/output`. The browser shows paths **inside the container**, so select `/input` and `/output`, not a host path such as `D:/Videos`.

Input is mounted read-only. Output is saved directly in your chosen host output folder and survives container recreation. SQLite settings and email history are stored in the host `data` folder (override with `DATA_DIR` in `.env`) and survive container recreation. Keep this folder when updating the app. Only mounted folders are available as host media; add another bind mount to Compose to access another host directory. No media is copied into the image. Keep the terminal build output if the build fails so its error can be diagnosed.

```sh
docker compose logs -f        # View startup/errors; Ctrl+C exits log viewing only
docker compose down           # Stop and remove the container; host video files remain
docker compose up -d --build  # Rebuild after updating the app files
```

To change the local port, set `FRAMEFORGE_PORT` in `.env`, then run `docker compose up -d` again. Both port publication and allowed browser origins follow that value. The default port binding is loopback-only; this app requires a token login and is intended for your local installation. It does not publish itself to your LAN or the Internet. Container queues are in memory and disappear when stopped/recreated. Graceful stop terminates active FFmpeg processes; a partial hidden file may remain, so remove `.frameforge-*` files from the output folder only after the app is stopped.

### Docker with NVIDIA NVENC

Enable GPU access using the included overlay:

```sh
docker compose -f compose.yaml -f compose.nvidia.yaml up -d --build
```

The host needs a supported NVIDIA GPU/driver and a Docker installation configured for GPU access. On Linux, install and configure the [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html). Docker Desktop GPU support on Windows requires its supported [WSL2 GPU configuration](https://docs.docker.com/desktop/features/gpu/). NVENC is not available through this configuration on macOS Docker Desktop. The overlay requests NVIDIA devices using [Compose GPU reservations](https://docs.docker.com/compose/how-tos/gpu-support/) and enables the `video`, `compute`, `utility` and `graphics` driver capabilities (graphics is used for Vulkan/libplacebo HDR processing).

Use the same `-f compose.yaml -f compose.nvidia.yaml` arguments for subsequent `up`, `logs`, `exec`, and `down` commands for GPU mode. For example:

```sh
docker compose -f compose.yaml -f compose.nvidia.yaml exec frameforge nvidia-smi
docker compose -f compose.yaml -f compose.nvidia.yaml exec frameforge ffmpeg -hide_banner -encoders
```

Check that the desired `h264_nvenc`, `hevc_nvenc`, or `av1_nvenc` encoder is listed, then run a small conversion. The Debian-packaged FFmpeg controls which encoders are compiled in; unavailable encoders are disabled by the UI. A listed encoder still requires compatible hardware and driver versions at runtime. AV1 requires newer supported hardware. GPU access is optional; software encoding continues to work in the base Compose setup.

The container runs as a non-root user with a read-only root filesystem and writable temporary space. Do not use privileged mode or mount the Docker socket. Output must be on a filesystem supporting hard links, as described below.

### Docker verification limits

The application integration tests and YAML structure were checked in the development environment. Docker is not installed there, so image build, Compose startup, and NVIDIA container operation could not be run. On your host, `docker compose config` checks the resolved configuration; `docker compose up -d --build` builds and starts it. An initial image build needs network access to fetch the Python image and Debian packages. After build, the app does not need Internet access to convert files.

## Start without Docker

1. Install Python 3.10+ and an FFmpeg distribution that includes ffprobe. Make sure `python --version`, `ffmpeg -version`, and `ffprobe -version` work in your terminal. On some systems use `python3` instead of `python`.
2. Extract this whole folder, preserving the `static` subfolder.
3. Open a terminal in this folder and run:

   ```sh
   python app.py
   ```

   On Windows you may also double-click **Start-Windows.bat**. On macOS or Linux run `python3 app.py`.
4. The app opens at **http://127.0.0.1:8765**. Keep the terminal open during conversions. Press Ctrl+C in the terminal to stop the server.

Use `python app.py --port 8766` if the port is occupied, or `--no-browser` to skip automatically opening the browser. Use the printed 127.0.0.1 URL or localhost with the same port.

## Workflow

- Use **Browse files** beside the input file field to select one or more videos. Selections persist while navigating across folders. Or paste a video path into the field and click **Add** (or press Enter).
- Use **Browse folder** beside the input folder field to choose a directory, or paste its path and click **Add**. Enable **Include subdirectories** to scan recursively. Folder expansion happens when you start the batch. In Docker, paths are container paths such as `/input`, not host drive paths.
- Choose an existing output folder with **Browse**, or paste its absolute path. In the browser, use **Go** to jump to any path, including another drive on Windows (`D:\\Videos`). Navigate inside the desired folder and click **Use this folder**.
- Choose a preset or customize container, codec, quality, speed, maximum height, frame rate, per-track audio, subtitle selection/burn-in, HDR output and auto crop. Unavailable encoders are disabled according to your installed FFmpeg.
- Click **Start conversion**. CPU and GPU jobs run up to their selected parallel limits (one of each by default). Add another batch while one runs. Settings are captured independently for each batch.
- View progress, errors, and completed output paths in the queue. Cancel individual jobs or stop the batch. **Clear finished** removes completed, failed, and cancelled records from the interface.

## Encoding choices

- MP4 / H.264 / AAC is the default for everyday compatibility.
- H.265 usually trades encoding time for smaller output. Playback support varies.
- WebM uses VP9 and Opus. ProRes MOV uses fixed ProRes 422 HQ for editing and creates large files.
- For CRF, lower numbers mean better quality and larger files. H.264 defaults to 23. MPEG-4 uses a mapped quality scale from 1 (best) to 31. ProRes HQ has fixed quality. The encoding speed control applies to software H.264/H.265. NVENC has its own preset control.
- Resolution caps height without increasing source height; width preserves aspect ratio. Stream copy disables resizing and frame rate changes. Audio bitrate applies to AAC, AC-3, E-AC-3, Opus and MP3.
- Remux / stream copy avoids re-encoding. The source codecs must be valid for the selected container, otherwise FFmpeg reports the error. No silent fallback is applied.

## NVIDIA NVENC

- Choose **H.264 · NVIDIA NVENC**, **HEVC · NVIDIA NVENC**, or **AV1 · NVIDIA NVENC** under Video codec. A quick preset combines HEVC NVENC with AC-3 in MKV. NVENC is offered for MP4/MKV; H.264/HEVC NVENC are also offered for MOV.
- Requires a supported NVIDIA GPU, compatible driver, and FFmpeg built with the desired NVENC encoder. AV1 encoding requires newer supported hardware. The encoder list only proves FFmpeg was built with it; a conversion can still fail if the GPU or driver cannot initialize. Such failures are reported without silently switching encoders.
- Selecting an NVENC codec reveals dedicated controls; the generic software encoding-speed control is disabled. Choose an explicit **P1–P7 preset** (fastest to slowest / higher quality), or Encoder default. Existing batches without explicit NVENC settings retain the earlier software-speed mapping.
- **Rate control** offers VBR-CQ (quality targeting), VBR (target bitrate), CBR (constant bitrate target), and constant QP. CQ/QP uses the quality slider (0–51); VBR/CBR disables it and uses the target bitrate. CQ 0 means automatic quality, not lossless. QP 0 is codec-specific; it is not a universal lossless guarantee.
- **Target / maximum bitrate** is in Mbps; **VBV buffer** is in Mbits. Maximum 0 means uncapped/automatic; buffer 0 is automatic. CBR sets minimum/maximum equal to target and defaults the buffer to twice the target. Capped CQ/VBR defaults the buffer to twice the maximum. VBR maximum cannot be below target. Constant QP does not use maximum bitrate, buffer, or multipass.
- **Tuning** offers encoder default, high quality, low latency, or ultra low latency. Low latency tuning alone is not a guarantee of zero latency; explicit B-frame and lookahead settings also affect buffering.
- **Multipass** offers encoder default, single pass, quarter-resolution first pass, or full-resolution first pass. These are NVENC per-frame rate-control passes, not a file-level analysis/encode pair.
- **Lookahead** can be left to the encoder or set to 0/8/16/32 frames. **B-frames** can be default or 0–4. **Keyframe interval** can be default or 24/48/60/120/240 frames. Availability and supported combinations still depend on the GPU/driver.
- **Adaptive quantization** is default, off, spatial, or temporal. Spatial AQ strength is 1–15. Spatial and temporal AQ are mutually exclusive in the interface.
- **Bit depth** offers 8-bit or 10-bit for HEVC/AV1; H.264 stays 8-bit. Profiles include the encoder default, H.264 Baseline/Main/High, HEVC Main/Main10, and AV1 Main where advertised by FFmpeg. HEVC Main10 requires 10-bit and Main requires 8-bit. H.264 Baseline forces B-frames off. Selecting 10-bit does not perform HDR tone mapping or invent additional source detail.
- **GPU index** is automatic or device 0–7 as numbered inside the running environment/container. For a single GPU the index is usually 0. Docker visibility/remapping can change indices.
- The app reads `ffmpeg -h encoder=...` and disables unadvertised options or enum values. Auto/default leaves an option unspecified. Advertised options do not prove hardware compatibility; errors are reported without silent encoder fallback. Expand **FFmpeg arguments** on a queued/running/completed job to inspect the command used (its output path is the temporary file before final publication).
- Video decoding normally runs on the CPU; NVENC accelerates encoding. CPU HDR conversion and libass run on the CPU, while the optional libplacebo HDR stage uses Vulkan. No extra Python packages or NVIDIA SDK installation are needed by this app.

## Dolby Digital and multiple audio tracks

- **Dolby Digital · AC-3** and **Dolby Digital Plus · E-AC-3** are available for MP4, MKV, and MOV; AVI also supports AC-3. Playback support depends on the player. Choose MKV for broad stream preservation.
- All audio tracks are included by default. Choose **First audio track** to keep only the first. In the default shared-settings mode, the selected audio codec, bitrate, and channel setting apply to every included audio stream. Switch to per-track mode for independent settings and multiple outputs. Source language/title metadata follows mapped streams where supported by the container.
- **Copy original stream** preserves each selected audio track without re-encoding. It requires compatible codecs and original channel layouts.
- Preserve source channels, downmix to stereo, or convert to six-channel 5.1. Converting stereo to six channels does not create genuine surround sound. AC-3/E-AC-3 support up to 5.1 in this app; sources above six channels must be explicitly downmixed. Dolby output is resampled to 48 kHz. AC-3 has a maximum selectable bitrate of 640 kbps; E-AC-3 offers up to 1024 kbps. Use 448 or 640 kbps for 5.1 AC-3.
- This encodes AC-3/E-AC-3; it does not create Dolby Atmos metadata. Copying an existing compatible stream avoids re-encoding it.

## HDR10+, Dolby Vision, HDR10 and SDR

Use **HDR / Dolby Vision conversion** to select **HDR10** or **SDR**. **No HDR color conversion** keeps the existing conversion behavior; it does not promise to preserve Dolby Vision/HDR10+ dynamic metadata when re-encoding. HDR controls are saved in named presets.

- **Inspect selected source** or **Browse sample video** shows detected color transfer, pixel format, Dolby Vision profile/compatibility, and mastering metadata. The app inspects stream headers and the opening 32 video packets for frame metadata. Dynamic metadata that appears later may not be labeled in this sample; HDR10+ metadata is still removed by the output conversion filter. A Dolby Vision stream without decoded RPU metadata in the sample is rejected by the RPU-processing path.
- **HDR10 output** requires HEVC software x265 or HEVC NVENC, an MP4/MKV/MOV container, 10-bit 4:2:0 output, BT.2020 primaries, PQ transfer and limited range. The UI selects a compatible HEVC codec and Main10/depth when this target is chosen. The backend enforces these requirements.
- **SDR output** tone-maps PQ/BT.2020 footage to BT.709 with a 100-nit SDR reference, Hable/Mobius/Reinhard mapping, gamut conversion, and HDR side-data removal. Common video encoders output 8-bit SDR; ProRes retains its normal 10-bit 4:2:2 pixel format. NVENC SDR is forced to 8-bit. Review results on a calibrated display; automatic conversion is not a manual creative color grade.
- **CPU** uses FFmpeg `zscale`/`tonemap` for HDR10/PQ base-layer conversion. HDR10+ → HDR10 removes dynamic scene metadata while retaining the compatible PQ image. HDR10+ → SDR uses the static HDR10/PQ base; it does not apply HDR10+ scene-specific trims. For CPU SDR, source peak comes from your override, MaxCLL, mastering peak, or a 1000-nit fallback. The override is not used by libplacebo.
- **Dolby Vision profiles 5 and 8** use libplacebo's `apply_dolbyvision` with decoded RPU metadata and a working Vulkan runtime. Profile 5 is not an HDR10-compatible base image; CPU-only or simple color retagging is rejected. Unsupported/unknown profiles and missing RPU metadata stop the file/queue with a specific error.
- **Profile 7 / enhancement-layer sources** require explicit **HDR10-compatible base layer only** selection. The first video stream must contain a profile 7 HDR10 base, or a profile 8 base with compatibility ID 1. This discards Dolby Vision trims and enhancement-layer information. **Full EL/FEL reconstruction is not implemented.** This option is rejected for profile 5. On older FFmpeg builds without named Dolby Vision side-data deletion, base-layer HDR10 requires software x265; SDR can still remove all HDR side data after processing.
- Software x265 explicitly carries available mastering-display and MaxCLL/MaxFALL metadata into HDR10. If source mastering metadata is missing, conversion stops unless you check **Allow BT.2020/D65 mastering defaults** and use software x265. That option declares BT.2020/D65, a 0.005-nit minimum and your selected/detected source peak; these are assumed values, not recovered studio mastering data. NVENC needs actual retained source mastering metadata.
- After encoding, HDR outputs are probed before publication. HDR10 must have 10-bit BT.2020/PQ and mastering-display metadata; SDR must be tagged BT.709 without HDR static metadata. Both must be free of detected Dolby Vision/HDR10+ metadata in the inspected opening frames. Failed verification stops the queue and removes the temporary output. This is a bounded metadata check, not a certified whole-file bitstream or visual validation.

HDR conversion requires an FFmpeg build with `zscale`, `tonemap`, `sidedata`, `format` and `setparams`. Dolby Vision RPU processing additionally needs `libplacebo` and Vulkan (GPU or a software Vulkan driver). Docker includes Mesa's software driver; software Vulkan can be slow. With NVIDIA, the overlay enables graphics-driver libraries as well as video/compute. Standalone users must supply compatible FFmpeg filters and a working Vulkan installation. A filter listed in FFmpeg does not guarantee a working Vulkan device. No `dovi_tool`, `hdr10plus_tool`, Python package or extra account is required.

The development host has no working Vulkan device and no Dolby Vision source fixture. Real CPU HDR10/SDR conversions and output metadata were tested using generated PQ/Main10 media; Dolby Vision profile/metadata guards and the libplacebo command plan were tested, but actual Dolby Vision rendering and NVIDIA HDR output still require validation on your hardware and content.

## Subtitle selection and burn-in

The subtitle dropdown supports **Do not include**, **Forced streams only**, **All subtitle streams**, and **Choose tracks / burn subtitles**. Forced-only uses source stream forced flags. Custom selection exposes every embedded subtitle stream found in a sample file. External sidecar subtitle import is not included.

1. Choose custom selection, then **Inspect first selected file** or **Browse sample video**. This does not add the sample to your batch.
2. **Keep as soft track** adds a selectable subtitle stream to the output. **Burn into video** renders that track into the picture. Both toggles may be enabled for a track. Multiple tracks may be burned; their layers are applied in track-rule order, so overlapping captions may overlap visibly.
3. Set optional language/title overrides, default and forced flags, and a soft-subtitle codec. Only one kept track may be explicitly default. **Auto** copies subtitles into MKV, converts text to `mov_text` for MP4/MOV, or WebVTT for WebM. Some text styling is lost when converting to a simpler subtitle format.
4. Bitmap PGS/DVD/DVB subtitles can be kept in MKV or burned; bitmap-to-text conversion would require OCR and is not implemented. AVI only supports burn-only output in this interface. Unsupported decoder/encoder/container combinations stop the file rather than silently dropping tracks.

**Burn-in order is HDR conversion → crop → resize → subtitle rendering → video encoding.** Text subtitles are extracted into a safe temporary ASS file, then rendered with libass at the final video size. Source paths containing spaces, quotes or filter punctuation are not embedded into the filter expression. Embedded TTF/OTF fonts are extracted to fixed safe temporary names and used by libass. Other fonts must be installed on the host/container; Docker includes DejaVu, and additional language coverage may require extra fonts. Rendering and font substitution can differ from a standalone media player.

Bitmap subtitles default to **Fit inside cropped frame**: the whole source subtitle canvas is scaled proportionally to fit the final cropped/resized picture and centered, so subtitles in removed black bars remain visible (glyphs may become smaller). **Original positions · clip removed borders** instead applies the video's crop/resize to the bitmap canvas before overlaying at the original relative position; subtitles outside the retained picture are intentionally clipped. Both overlays are composited after the main picture's crop/resize. Bitmap burn-in requires FFmpeg `overlay` and `scale2ref`; text burn-in requires the `subtitles` filter/libass.

For HDR10 output, subtitle colors are treated as BT.709 SDR graphics, converted to BT.2020/PQ with a 203-nit white reference, and composited in the 10-bit output. This avoids treating SDR-white captions as maximum PQ brightness. Select HDR10 or SDR color conversion before burning into a detected HDR source; stream-copy video cannot be burned. Burned captions cannot be disabled during playback.

Subtitle rules use **subtitle track positions** (track 1, 2, …), independently of audio positions or absolute stream indices. They apply across the batch; use separate batches for different layouts. A selected missing track stops the queue. Inspection does not overwrite an existing plan. The subtitle plan, burn choices and HDR controls are included in saved settings.

## Automatic black-border crop

- Enable **Auto detect and crop black borders** to analyze each queued file separately before encoding. For files longer than 15 seconds, it samples up to ten seconds at 10%, 50%, and 80% of the duration. Short files are sampled from the start for up to ten seconds.
- It uses FFmpeg `cropdetect` with threshold 24 and even dimensions, retaining a conservative rectangle encompassing the detected visible areas across samples. The detected `width:height:x:y` appears in the queue. If no usable rectangle is detected, the original framing is retained.
- Crop is applied before the selected resolution cap. It requires video re-encoding and works with software codecs or NVENC. Stream copy disables it.
- Detection is a heuristic: very dark scenes, logos, subtitles in the borders, or unsampled aspect-ratio changes can affect the result. Inspect finished footage. It applies one fixed crop per file, not a dynamic crop for each scene. Cancel stops the detection process as well as encoding.

## Queue stops and free disk space

- **Any conversion failure stops the whole queue.** The failed file stays marked Failed; other files remain queued. Inspect the error, then click **Resume queue** to skip that failed file and continue, or **Retry failed files** / the individual **Retry** button and then Resume to try it again. Retry uses the original saved job settings; cancel the record and add a new batch if you need to change its settings.
- Before a file starts, while it is probing/crop-detecting/encoding (every 0.5 seconds), and before final publication, the app checks free space on that file's **output filesystem**. Less than **4,000,000,000 bytes (4 GB)** stops processing. An unreadable output filesystem also stops the queue. This is a polling guard, not a reserved disk quota; other applications can consume space between checks.
- If space drops during encoding, FFmpeg is terminated and the partial file is removed when possible. That record is marked Blocked. The remaining files stay queued. Free space or cancel blocked/pending jobs, then click Resume; blocked files restart from the beginning. The queue does not resume automatically when space recovers. If partial-file deletion fails, the queue shows a cleanup warning and path.
- **Pause after current** lets an active file finish before any new one starts. **Stop batch** cancels active and waiting work. **Clear finished** removes terminal records; it keeps blocked and active records.
- The queue itself remains in memory. Restarting the server/container loses queued work; saved presets and email settings are persistent.

## Independent audio settings and extra encodes

1. Select **Different settings / multiple outputs per track** under Audio configuration.
2. Use **Inspect first selected file**, or **Browse sample video** for a file inside a selected folder. This displays language, codec, channel count and available title for each source audio track. Inspection does not add the sample to the conversion batch or change an existing plan.
3. Each rule identifies a **source audio track position**, starting at track 1. Its output rows have separate codec, bitrate, channel conversion, and optional title. Rules apply by audio position in every file of the batch, not by language or absolute stream index. Group files with matching track layouts into separate batches.
4. For original audio plus AAC, keep the original **Copy original stream** row, click **Add another output**, and select AAC, a bitrate such as 192 kbps, and stereo. This maps the same source into two output audio streams; it does not encode the video twice. Other source tracks can have different codecs/bitrates/channel settings.
5. Remove all output rows from a rule to omit that source track. **Tracks without a rule** can be copied unchanged or dropped. At most 64 explicit track rules, eight outputs per rule and 128 explicit outputs per file are allowed.

Language/title metadata follows each mapped source; an optional output title overrides the source title. The first mapped output of the source default track retains default playback status; duplicate encodes are not also marked default. A rule referring to a missing source track fails that file and stops the queue rather than silently dropping it. Stream-copy outputs still need container-compatible source codecs. Changing format does not silently rewrite existing per-track rules; choose compatible codecs if the UI marks a rule incompatible.

## Cut and edition labels

With **Clean up file names** enabled:

```text
Movie.Title.2020.Directors.Cut.1080p.BluRay.mkv
→ Movie Title (2020) {Edition- Director's Cut}.mkv
```

Recognized labels include Director's Cut, Extended Director's Cut, Extended Cut/Edition/Version, Special Edition, Collector's Edition, Ultimate Collector's Edition, Ultimate Edition, Limited Edition, Anniversary Edition, Theatrical Cut, Final Cut, Assembly Cut, Rogue Cut, International Cut, Unrated, Uncut, Remastered Edition, Despecialized Edition, Criterion Collection, IMAX, Fan Edit and Redux. Explicit existing `{Edition- ...}` tags are retained. Labels found before the year move after it, and duplicate recognized labels are not repeated. Multiple labels are joined with commas within one edition tag. No online movie lookup or ambiguous abbreviation inference is performed. Without a year, the recognized edition label is appended to the remaining cleaned name. Existing output files still receive numeric collision suffixes.

## Saved settings

Enter a name under **Saved settings** and click **Save settings**. Load a preset with the dropdown and Load; saving an existing name replaces that preset. The last saved preset is restored when the page opens. Presets include video/NVENC/audio settings, the per-track plan, subtitles, crop, naming, output directory and subfolder choice. They also include HDR processing choices and subtitle selection/burn rules. They do not include source selections or SMTP passwords.

SQLite stores presets and SMTP configuration/history in `~/.frameforge/settings.sqlite3` for standalone use, or `/data/settings.sqlite3` inside Docker (the host `data` folder by default). Set `FRAMEFORGE_DATA` to override the standalone directory. Python supplies SQLite; no database server or external account is required. A local login is required. The app stays restricted to local access. Stop the app before backing up the database. Retain `data` and `.env` when unpacking an update. If a saved codec is unavailable on the new host, select an available codec before queueing work.

## Email notifications

No emails are sent until you configure your own SMTP service. Under **Email notifications**:

1. Enter SMTP host, port, STARTTLS/TLS setting, sender address and recipient address(es), plus username if your service requires authentication. Multiple recipients use comma-separated plain addresses. Use STARTTLS (commonly 587), implicit TLS (commonly 465), or no TLS only for a trusted unauthenticated local relay. Certificate validation is enabled.
2. Enter the SMTP password to use it for the current server session. It is not stored in SQLite, saved presets, or API responses. For persistence, set `FRAMEFORGE_SMTP_PASSWORD` in the process environment; Docker Compose passes it from your private `.env` file. The standalone launcher does not read `.env` automatically; set an environment variable before launching it. A non-empty environment password takes precedence over a session-entered password.
3. Click **Save and send test email**, then check delivery history. The test is sent even if automatic notification toggles are disabled. This supports password/app-password SMTP authentication or an unauthenticated relay, not an interactive OAuth login flow.
4. Enable automatic emails and leave **File failure / low disk stop** and/or **Queue finished** checked, then save.

A file failure or low-disk interruption sends a stop alert containing its filename and error. Queue completion sends completed, failed-attempt, and cancelled counts once when the active queue drains. Adding files while work is active extends that same run. An automatically stopped queue does not send completion until you resume/resolve its pending work; failed files may be skipped by resuming. Retries can generate a new failure alert if they fail again. Queues that end through cancellation are reported with their cancelled counts.

Mail delivery happens in a background thread. A mail error appears in history and does not pause conversion or recursively trigger another email. “Sent” means the SMTP server accepted the message, not guaranteed inbox delivery. Delivery interrupted by server shutdown is marked unconfirmed after restart and is not automatically resent. SMTP delivery and Internet access depend on your service/network; sending to an internal relay can work without public Internet access. Email settings and history survive restart, but session-only passwords do not. No real SMTP credentials or recipient have been configured in the downloadable app.

## File handling and limits

- Inputs remain untouched. With filename cleanup off, outputs are named `name_converted.ext`, followed by `_1`, `_2`, etc. when needed.
- Enable **Clean up file names** to replace dots in the source basename with spaces, keep the title and last standalone year from 1800–2099, remove technical suffixes after that year, put the year in parentheses, and retain recognized cut/edition labels as described below. Example: `Movie.Title.2020.1080p.BluRay.mkv` becomes `Movie Title (2020).mp4` when converting to MP4. Existing `(2020)` or `[2020]` wrappers normalize to a single `(2020)`. The output extension always follows the selected format.
- The last standalone year supports titles such as `2001.A.Space.Odyssey.1968`, which becomes `2001 A Space Odyssey (1968)`. A year embedded in an alphanumeric token such as `2020abc` or `1920x1080` is not used. If no year is found, dots become spaces and repeated spaces collapse; the rest of the title is kept. There is no online lookup, so inspect names when a title contains several year-like numbers.
- Cleanup omits the `_converted` suffix. Collisions still receive `_1`, `_2`, etc., for example `Movie Title (2020)_1.mkv`. Original files and existing outputs are never overwritten, even when input and output folders match.
- Conversion writes to a hidden temporary file in the output folder. Successful files are published atomically using a hard link; the output filesystem must support hard links (normal NTFS, APFS, ext4 do). FAT/exFAT and some network shares do not; those jobs fail without replacing files. Select a supported local output folder.
- Cancellation cleans the current partial file. Abrupt termination or a power outage may leave `.frameforge-*` temporary files; remove those after stopping the app. The queue lives in memory and does not survive restart.
- The first video track is selected. Audio defaults to all tracks, with an optional first-track-only setting. Attachments, arbitrary command arguments, and chapter controls are not offered.
- Recognized input extensions: MP4, MKV, MOV, AVI, WebM, M4V, MPG, MPEG, MTS, M2TS, WMV, FLV, TS, OGV. At most 5,000 files per batch. A corrupt file stops the queue; remaining files wait until you explicitly resume.
- FrameForge runs on the same computer as the videos. Its file browser shows that computer's filesystem. It is a local utility, not a remotely hosted conversion service.
- Manual startup binds the HTTP server to 127.0.0.1. Docker binds it to 0.0.0.0 inside the container and publishes only to host loopback. Explicit host/origin checks and a per-session write token protect local actions. `FRAMEFORGE_ORIGINS` can specify allowed origins for port mappings; the Compose file sets it automatically. Login is required. Use HTTPS and the secure-cookie configuration for any network access. Anyone signed into this shared token session can browse and convert files accessible to the app.

## Verification

`python test_app.py` runs an integration suite with generated media, real FFmpeg conversions, progress completion, output probing, collisions, API validation, cancellation, invalid-file recovery, AC-3/E-AC-3 encoding, multiple audio tracks and language metadata, full/forced subtitle mapping/transcoding, text and synthetic PGS burn-in, post-crop subtitle placement, HDR10/PQ-to-SDR and Main10 output metadata, crop dimensions, NVENC argument modes and capability validation, explicit source path validation, filename normalization and collision handling, NVENC argument handling or clear unavailable-hardware errors, per-track duplicate mapping and original packet preservation, failure/low-disk queue stops and recovery, edition names, SQLite persistence, and SMTP routing/TLS/history with mocked mail transports (no real email is sent by tests). NVENC encoding is confirmed working by the user on their target system. Vulkan rendering and real Dolby Vision media still need content validation; the tests use generated PQ and subtitle fixtures and do not certify a Dolby Vision grade. Requires FFmpeg and ffprobe. No third-party testing packages.

## Logo and branding

The transparent logo is included at `static/frameforge-logo.png` and used in the browser header. The visible application name is FrameForge. Existing `FRAMEFORGE_*` environment variables, data paths and Compose service names are retained so saved settings and installations remain compatible.

### Settings guidance

Open **Recommended starting points** below Quick preset for practical playback, HEVC, NVENC, audio and HDR suggestions. Hover a **?** beside a setting for its meaning and recommended starting point; keyboard focus and tap also reveal help. Per-track audio and subtitle editors include the same help. Quick presets change only their core fields, so review HDR and track rules before saving a complete preset.

### CPU threads and parallel encoding

Both standalone and Docker versions expose **CPU threads per encode** (0 = automatic, or 1–256), **Concurrent CPU jobs** (1–8), and **Concurrent GPU jobs** (1–8). NVENC has encoding sessions rather than a CPU-style GPU thread setting. GPU job limits apply across all selected NVIDIA devices. Non-NVENC jobs, including remuxes, use CPU slots. A GPU encode still needs CPU resources for decoding, audio and filters.

Start with one job per type. For simultaneous CPU jobs, divide your available logical CPUs among the jobs as a starting point and check memory and disk load. The CPU number requests FFmpeg decoder, encoder and filter thread counts; it is not a hard limit on total process threads or CPU usage. x265 receives an explicit pool size plus one frame thread, merged with any HDR metadata parameters. Some codecs use fewer threads, and libraries/drivers can create extra threads. CPU-only and GPU jobs can run together, up to the sum of the two job limits. Increasing sessions beyond a GPU/driver limit can fail and stop the queue.

**Apply queue limits** updates and persists global CPU/GPU job limits immediately. Starting a batch also applies its selected limits to the entire queue. A lower limit lets already-active jobs finish before new jobs are admitted. Thread counts are captured per newly queued batch. All three fields are included in saved presets; loading a preset changes the form, then Apply or Start applies its limits. Existing presets default to automatic threads and one job of each type.

On conversion failure, no more jobs start; already-active jobs finish. Low disk space on any active output drive interrupts all active jobs, removes partial outputs, and requires manual Resume. Interrupted files restart from the beginning. Completion email waits for all jobs and cleanup; failure and notification behavior otherwise remain unchanged. Output naming remains collision-safe when concurrent sources share a name.

Docker uses the CPUs made available by the host/container. No new packages are required. NVIDIA multi-session encoding needs sufficient GPU memory and driver session capacity; actual NVIDIA throughput must be checked on your hardware.

References: [FFmpeg thread and filter controls](https://ffmpeg.org/ffmpeg-all.html), [x265 threading](https://x265.readthedocs.io/en/master/threading.html).

### Appearance and settings tabs

The interface uses the logo's orange/amber and charcoal palette. Choose **Appearance → Light, Dark, or System** in the header. System follows your operating system, including changes while the app is open. Your appearance choice is saved in this browser; the matching light/dark logo switches automatically. Appearance is separate from conversion presets.

Use **Sources & destination** for sources, destination, container format and filename cleanup; **Video** for encoding, CPU/GPU job limits, HDR and cropping; and **Audio & subtitles** for shared/per-track audio, subtitle mapping, burn-in and export. Quick presets remain above the tabs because they can affect both video and audio. Settings stay in place when switching tabs. Left/Right arrow keys, Home and End navigate the tabs with a keyboard. The last tab is remembered for the browser session. Queue, Start and saved presets are accessible outside the tabs. Use the **Admin** tab for email settings, notification toggles, test email and delivery history.

### Output title metadata

Every output's container title is explicitly set to its final filename without the extension, replacing any source title. This includes cleaned names, year/edition labels, and numeric collision suffixes. The final filename is reserved within the queue before encoding so concurrent jobs write matching titles. Existing files are never overwritten. If another program creates that exact filename during encoding, the job stops safely; Retry selects a new name and matching title. Source files and per-track audio/subtitle titles remain unchanged.

### One folder per movie

Enable **Place each movie in its own folder** under Sources & destination to create/reuse a subfolder named from the cleaned movie title and year, excluding edition labels. Different editions share that folder. Enable **Clean up file names** too for `Movie Title (2020)/Movie Title (2020) {Edition- Criterion Collection}.mkv`. Filename cleanup remains an independent option. Existing output files get numeric suffixes; title metadata matches the actual filename without its extension. The folder choice is saved in presets and captured per batch. Encoded temp files and subtitle preparation folders are staged inside `_FFtmp/` in the selected destination root. Final folders are created when publishing a successful encode; existing folders are reused. Free-space checks cover the destination root and the nearest existing final directory.


### Complete email configuration through environment variables

All email settings can be supplied without configuring the Admin form. Non-empty environment variables override saved Admin settings; blank or unset variables use saved settings (or built-in defaults). To disable saved notifications explicitly, set `FRAMEFORGE_SMTP_ENABLED=false`. Restart after changing environment variables. The Admin form displays effective settings; edits to environment-controlled fields take effect only after those variables are removed or changed.

| Variable | Meaning / default when no saved value exists |
| --- | --- |
| `FRAMEFORGE_SMTP_ENABLED` | Automatic notifications: `true` or `false` (default false) |
| `FRAMEFORGE_SMTP_HOST` | SMTP server hostname |
| `FRAMEFORGE_SMTP_PORT` | SMTP port (default 587) |
| `FRAMEFORGE_SMTP_TLS` | `starttls` (default), `ssl`, or `none` |
| `FRAMEFORGE_SMTP_USERNAME` | SMTP login username |
| `FRAMEFORGE_SMTP_PASSWORD` | SMTP password/app password; never returned by the API or saved in SQLite |
| `FRAMEFORGE_SMTP_SENDER` | Sender's plain email address |
| `FRAMEFORGE_SMTP_RECIPIENTS` | Comma-separated recipient addresses |
| `FRAMEFORGE_SMTP_ON_FAILURE` | Failure / low-disk notifications (default true) |
| `FRAMEFORGE_SMTP_ON_FINISHED` | Queue-completion notifications (default true) |

Docker: copy `.env.example` to `.env`, fill in the email entries, then recreate using `docker compose up -d --build` (or your usual NVIDIA Compose command). Keep `.env` private; do not include it in shared archives or source control. It is excluded from the Docker build context.

Standalone Windows PowerShell example (substitute your own values):

```powershell
$env:FRAMEFORGE_SMTP_ENABLED = "true"
$env:FRAMEFORGE_SMTP_HOST = "smtp.gmail.com"
$env:FRAMEFORGE_SMTP_PORT = "587"
$env:FRAMEFORGE_SMTP_TLS = "starttls"
$env:FRAMEFORGE_SMTP_USERNAME = "you@gmail.com"
$env:FRAMEFORGE_SMTP_PASSWORD = "your-app-password"
$env:FRAMEFORGE_SMTP_SENDER = "you@gmail.com"
$env:FRAMEFORGE_SMTP_RECIPIENTS = "you@example.com"
$env:FRAMEFORGE_SMTP_ON_FAILURE = "true"
$env:FRAMEFORGE_SMTP_ON_FINISHED = "true"
python app.py
```

These PowerShell variables apply to that terminal and child processes only. The standalone app does not automatically load `.env`. Open Admin and use **Save and send test email** to verify delivery after configuration.


## Versioning and releases

`VERSION` is the authoritative application version. It is displayed in the browser header/title, returned as `version` by `/api/state`, printed at startup, and available without FFmpeg through `python app.py --version`. Docker copies this same file into the image.

Current beta **0.9.0-beta.8**: the main features and login are implemented, and NVENC encoding is confirmed working by the user; Docker build/start and Dolby Vision visual validation remain outstanding in this development environment. Earlier packages have no formal version and are not retroactively assigned release numbers. After validation and remaining beta fixes, release **1.0.0**.

Use semantic versioning: PATCH for compatible fixes, MINOR for compatible features, MAJOR for breaking changes. During the beta, increment the prerelease suffix (`0.9.0-beta.8`, etc.) for stabilization; use `0.10.0-beta.1` for a new beta feature cycle. This application version is separate from SQLite schema changes and file revision history.

Release checklist: update `VERSION`, add a dated CHANGELOG entry, run the relevant tests, and package as `FrameForge-<version>.zip`. Build a traceable Docker image with:

```sh
docker build -t frameforge:0.9.0-beta.8 -t frameforge:local .
```

Compose uses the versioned `frameforge:0.9.0-beta.8` tag. In Portainer you can use `image: frameforge:0.9.0-beta.8` after building that tag on the target Docker host. Recreate containers after rebuilding; preserve the mounted data folder.

## Desktop workspace and output layout

FrameForge now uses a wide desktop layout (1280px or wider recommended), with batch presets and settings in the main editor and a persistent queue on the right. The queue action bar remains available while scrolling long settings. Sources & destination, Video, Audio & subtitles and Admin remain keyboard-accessible tabs.

Encoded media is always written to a unique hidden `.frameforge-<job-id>.<format>` temp file in **`<selected destination>/_FFtmp/`**. Subtitle preparation uses a unique `.frameforge-subs-*` folder inside that same `_FFtmp/` directory. The directory is created automatically and reused; it remains in place when empty. Folder scans exclude this staging directory. After encoding and verification, the completed file is published into its final directory and the staging file is removed. Movie folders are created at publication, rather than before encoding. Cancellation and failure remove staging files; an abrupt process kill may leave them for manual cleanup. Existing final files are never overwritten. Root and final paths must be on a filesystem that supports the app's atomic hard-link publication; moving into a different mounted filesystem is not supported by this publication method.

Enable **Include subdirectories**, then **Mirror source subdirectories in destination** to preserve paths relative to each selected source folder. `Source/Drama/Classics/Movie.mkv` becomes `Destination/Drama/Classics/Movie_converted.mkv` (or a cleaned filename if enabled). The selected source folder name itself is omitted. With per-movie folders enabled, a cleaned example is `Destination/Drama/Classics/Movie Title (2020)/Movie Title (2020) {Edition- Criterion Collection}.mkv`. Individually selected files go into the destination root (or their movie folder). Multiple source roots merge their relative trees; duplicate inputs use their first selected source root, and existing filenames receive numeric suffixes. Disabling mirroring flattens the output tree. Both recursion and mirroring are saved with presets; turning recursion off also turns mirroring off.

## Movie / TV naming and optional suffix

**Add _converted to unchanged filenames** is enabled by default for compatibility with older presets. Turn it off to retain the source basename when cleanup is off. Filename cleanup continues to omit _converted. The source and existing outputs are never replaced; numeric collision suffixes still apply, and container title metadata matches the final video basename.

Before cleaning a name, FrameForge locally detects TV episode markers (S01E02, 1x02, multi-episode variants), valid air dates, or numbered files in a `Series/Season 01` directory. A year without an episode marker is treated as movie-like; names without either are Unknown and use the previous movie-style cleanup with a review notice. This is a filename/context heuristic, not verified movie-database identification. Use **Content type** to override it, and **Preview selected / sample name** before batch processing. Folder-only batches need a representative sample selected through Browse sample. No online service is used.

TV filename styles, applied when cleanup is enabled:

| Style | Example |
| --- | --- |
| Standard | Series Name (2020) - S01E02 - Pilot.mkv |
| Compact | Series Name (2020) S01E02.mkv |
| 1x02 | Series Name (2020) - 1x02 - Pilot.mkv |
| Multi-episode | Series Name - S01E02-E03 - Double Episode.mkv |
| Daily episode | Daily Show - 2024-03-05 - Guest.mkv |

Choose whether to retain detected episode titles and series years. Common resolution/source/codec tags are removed from the episode-title tail. Unknown release abbreviations and incorrectly named episodes may need manual source renaming. An explicit TV override with insufficient episode information stops naming rather than inventing episode numbers. Numeric series titles such as 1923 are preserved.

TV output folders can be None, Series, or Series / Season 01; daily episodes use the air-date year as season. TV folder choices are independent of filename cleanup and are added inside any mirrored parent tree. The movie-folder checkbox applies only to movie/unknown names, not to individual TV episodes. Different source layouts should use separate batches/presets.

## Export SRT subtitles

Under Audio & subtitles, choose **SRT sidecar export**: None, All text tracks, Forced text tracks, or Choose tracks below. Custom enables an independent **Export SRT** checkbox beside Keep and Burn in the subtitle editor. A track can be exported without being embedded or burned. Custom selection requires custom subtitle mode.

Files are named from the final video basename, language and original subtitle ordinal: `Movie Title (2020).eng.s1.forced.srt`. Track ordinals avoid duplicate-language collisions. All/Forced exports skip bitmap/unknown non-text tracks and show a queue notice; an explicitly selected bitmap export fails because OCR is not included. Forced mode uses stream flags, not individual forced events inside a mixed track. SRT keeps text/timestamps but may lose ASS styling, positioning or other source features.

All export files stage in `_FFtmp`. After video encoding, HDR verification and SRT extraction succeed, sidecars are linked beside the final video and the video is published last. A sidecar collision selects a new shared video basename before encoding. Normal publication failures roll back newly linked sidecars; an abrupt power loss can still interrupt a multi-file publication. Existing files are never overwritten. Generated files are listed in the queue.

## Interlace detection, deinterlacing and telecine

Use **Analyze selected / sample file** to run FFmpeg idet over the opening 300 frames. Auto correction or the per-file detection checkbox samples up to three positions with 300 frames each (one for short files), records progressive/interlaced/undetermined and repeated-field counts, and suggests a field order where clear. Repeated fields indicate possible telecine, but sampling cannot certify a whole-file cadence; static scenes, animation and mixed footage can mislead it. Auto applies single-rate BWDIF only when classified interlaced, and leaves progressive/unknown footage unfiltered. It never automatically decimates suspected telecine.

Manual options include BWDIF or YADIF at one output frame per input frame, or bob at one frame per field. Bob doubles the output rate, for example 29.97 → 59.94, so the frame-rate control is kept at Original. Auto field parity uses source metadata, or detected parity for Auto correction; TFF/BFF overrides are available. Wrong parity can cause judder. These filters run on the CPU, including when NVENC performs the final encode.

**3:2 inverse telecine** uses `fieldmatch`, BWDIF for remaining combed frames, then `decimate=cycle=5`; use only for consistent 29.97/30 fps film cadence to recover 23.976/24 fps. The app rejects other input rates for this mode. **Field matching only** omits decimation for appropriate 2:2 material. Neither option guarantees repair of mixed film/video, broken edits or changing cadence. Inspect motion and audio synchronization on a sample first. Soft-telecine repeat flags alone do not establish that the decoded frames need hard-telecine correction; inspect the decoded cadence first.

The pipeline is **scan correction → HDR conversion → crop → resize → subtitle burn → encoding**. Crop detection sees the same scan/HDR preprocessing. These corrections require video re-encoding; stream copy may still be used with detection/reporting alone. SRT timestamps remain on the original timeline because these filters change frame representation/cadence rather than playback speed. Explicit frame-rate conversions outside these correction modes may drop/duplicate frames.

The Docker image includes FFmpeg and its supporting filter libraries. A custom host FFmpeg build must provide the selected filters; unavailable features stop the queue with an FFmpeg error. See [FFmpeg filter documentation](https://ffmpeg.org/ffmpeg-filters.html) for idet, bwdif, yadif, fieldmatch and decimate.

## Shared audio and conditional English subtitles

In **Audio & subtitles**, choose **Shared settings · all or selected tracks** to apply one output codec to every included audio stream. Passthrough preserves the original compressed audio; AAC, Dolby Digital (AC-3), and Dolby Digital Plus (E-AC-3) encode it. Available codecs still depend on the container: MP4/MKV/MOV offer these shared choices, whereas WebM requires its supported codecs. Passthrough does not change channels or bitrate and must be compatible with the destination container. For multiple outputs from the same source, use advanced per-track mode instead.

Use All tracks, First track, or **Choose specific tracks**. Inspect a sample to view language, codec and channel metadata, then check the required positions. Selected positions are reused for every file of the batch; missing required positions stop the queue. Unchecked tracks are omitted. All audio settings and selected positions save with presets.

The subtitle option **Add English subtitles if first audio is foreign** checks the language metadata of the first source audio stream, regardless of which audio tracks you output. A recognized non-English tag includes one existing tagged English subtitle stream as the default: full subtitles are preferred over forced-only tracks, then the source default, then the first English track. Language variants such as en-US/eng and common two-/three-letter language tags are recognized. This is metadata detection, not speech recognition. Unknown/untagged/multiple-language tags, no audio, or no English subtitle produce a queue notice instead of guessing. Nothing is translated, generated or downloaded by this rule.

The selected English subtitle uses the normal container-compatible soft-subtitle path (text conversion for MP4/MOV/WebM, text or bitmap copy for MKV). Unsupported bitmap/container combinations fail clearly rather than dropping the requested track. AVI cannot use this soft-subtitle rule. Players can override default-subtitle flags according to their own preferences. Explicit subtitle selection and SRT exports remain available separately.

Validation update: the user confirmed Dolby Vision profile 7 → HDR conversion working on their files. This validates the supported path used by that installation; it does not certify every profile-7 variant or full enhancement-layer/FEL reconstruction. NVENC encoding is also user-confirmed.

During encoding, each running file shows its percentage and FFmpeg-reported FPS (for example, `Converting 42% · 78.6 fps`). FPS is per job, not the total across the queue. Before the first speed report it displays FPS pending; preparation, detection and export phases show their phase names instead. Short jobs may report zero FPS; stream-copy operations show FPS n/a because no frames are encoded.
