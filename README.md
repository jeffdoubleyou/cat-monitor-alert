# Cat Monitor Alert

Watch an ONVIF camera over RTSP, detect cats in a snapshot every few seconds, then:

1. Play a sound on the camera speaker (ONVIF audio clip, with optional RTSP talk-back)
2. Send a push alert with the annotated frame to [ntfy](https://ntfy.sh)

Configuration is entirely environment variables / a `.env` file.

## How it works

1. Connect to the camera with ONVIF and ask for an RTSP URL (or use `CAMERA_RTSP_URL` if you already know it).
2. Grab a single JPEG frame with `ffmpeg` (OpenCV is the fallback).
3. Run [YOLO11n](https://docs.ultralytics.com/models/yolo11/) and look for the COCO `cat` class.
4. If a cat is found and the cooldown has expired, play a camera sound and `PUT` the JPEG to `https://ntfy.sh/<topic>`.

## Local setup

Needs Python 3.11+ and `ffmpeg` on your `PATH`.

```bash
cp .env.example .env
# edit .env with camera credentials and an unguessable ntfy topic

python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Or with `uv`:

```bash
uv python install 3.12
uv venv --python 3.12
source .venv/bin/activate
uv pip install -e ".[dev]"
```

Subscribe to the ntfy topic on your phone or at `https://ntfy.sh/<your-topic>` before testing alerts.

### Run

```bash
# live monitor (default interval: 5 seconds)
python -m cat_monitor

# one snapshot, then exit
python -m cat_monitor --once

# test detection on a photo (no RTSP)
python -m cat_monitor --image path/to/cat.jpg --dry-run

# speaker / ntfy smoke tests
python -m cat_monitor --play-sound
python -m cat_monitor --notify-test
```

`--dry-run` still runs detection but skips the camera speaker and ntfy.

### Tests

```bash
pytest
```

These cover config, ONVIF URL/audio handling, YOLO filtering, ntfy payloads, and the alert cooldown. They do not need a camera.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `CAMERA_HOST` | — | Camera IP or hostname |
| `CAMERA_ONVIF_PORT` | `80` | ONVIF HTTP port (`8000` / `8080` on some cameras) |
| `CAMERA_USER` / `CAMERA_PASSWORD` | — | ONVIF / RTSP credentials |
| `CAMERA_ONVIF_HTTPS` | `false` | Use HTTPS for ONVIF |
| `CAMERA_RTSP_URL` | empty | Skip ONVIF discovery and use this stream |
| `CAMERA_PROFILE_INDEX` | `0` | ONVIF media profile (use a substream if the main stream is heavy) |
| `SNAPSHOT_INTERVAL_SECONDS` | `5` | Time between frames |
| `RTSP_TRANSPORT` | `tcp` | `tcp` or `udp` |
| `YOLO_MODEL` | `yolo11n.pt` | Ultralytics model path or name |
| `DETECT_CLASSES` | `cat` | Comma-separated COCO labels |
| `DETECT_CONFIDENCE` | `0.45` | Minimum score |
| `ALERT_COOLDOWN_SECONDS` | `60` | Minimum time between alerts |
| `NTFY_SERVER` | `https://ntfy.sh` | ntfy base URL |
| `NTFY_TOPIC` | — | Topic name (treat it like a password) |
| `NTFY_TOKEN` | empty | Bearer token if the server requires auth |
| `ONVIF_AUDIO_CLIP_TOKEN` | empty | Play this clip; otherwise the first clip the camera reports |
| `TAPO_CLOUD_PASSWORD` | empty | Tapo app password for C100-style siren (not the ONVIF account) |
| `TAPO_ALARM_SECONDS` | `3` | How long to sound the Tapo alarm |
| `TAPO_ALARM_SOUND` | empty | Tapo sound: `siren`, `emergency`, `red_alert`, or a custom clip id |
| `AUDIO_BACKCHANNEL_URL` | empty | Optional RTSP talk-back URL if ONVIF clips, Tapo alarm, and CGI all fail |
| `SNAPSHOT_DIR` | empty | Write annotated JPEGs here |
| `DRY_RUN` | `false` | Detect only |
| `LOG_LEVEL` | `INFO` | Python log level |

## Camera sound

Most ONVIF Profile T cameras expose `PlayAudioClip`. Enable the speaker in the camera UI and, if the firmware has named clips (siren, doorbell, alert), set `ONVIF_AUDIO_CLIP_TOKEN` to that token.

**Tapo C100 and other Tapo cameras** only implement ONVIF Profile S, so they have no ONVIF/RTSP speaker. Set `TAPO_CLOUD_PASSWORD` to your Tapo app password (this is **not** the ONVIF camera account). In the Tapo app, also turn on **Me → Tapo Lab → Third-Party Compatibility**. The monitor then plays the camera alarm for `TAPO_ALARM_SECONDS` (default 3). Pick the clip with `TAPO_ALARM_SOUND=siren`, `emergency`, or `red_alert`. You can also record up to two custom clips in the Tapo app and set `TAPO_ALARM_SOUND` to that clip id. Test with:

```bash
python -m cat_monitor --play-sound
python -m cat_monitor --notify-test
```

If that fails, the monitor posts a short G.711 A-law tone to Amcrest/Dahua `/cgi-bin/audio.cgi` talk-back.

If the camera has two-way audio but neither clips, Tapo alarm, nor CGI, set `AUDIO_BACKCHANNEL_URL` to the talk-back RTSP URL. The monitor will send the tone via `ffmpeg`.

## Docker

```bash
cp .env.example .env
# set SNAPSHOT_DIR=/app/snapshots if you want JPEGs on the bind mount

docker compose up --build
```

The compose file uses `network_mode: host` so the container can reach LAN cameras the same way the host can. That is the right default on Linux. On Docker Desktop (macOS/Windows), comment out `network_mode: host` and keep the camera IP reachable from the VM.

The image installs CPU PyTorch, `ffmpeg`, and downloads `yolo11n.pt` at build time so the first run is not blocked on a model download.
