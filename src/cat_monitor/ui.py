"""Minimal HTTP UI for recent frames and cat detections."""

from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse

from cat_monitor.store import SnapshotStore

logger = logging.getLogger(__name__)

_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Cat monitor</title>
  <style>
    :root { color-scheme: dark; }
    body { font-family: system-ui, sans-serif; margin: 0; background: #111; color: #eee; }
    header { padding: 1rem 1.25rem; background: #1c1c1c; border-bottom: 1px solid #333; }
    h1 { font-size: 1.15rem; margin: 0 0 .35rem; }
    .meta { color: #aaa; font-size: .9rem; }
    nav { display: flex; gap: .5rem; padding: 1rem 1.25rem 0; }
    button { background: #2a2a2a; color: #eee; border: 1px solid #444; border-radius: 6px; padding: .4rem .8rem; cursor: pointer; }
    button.active { background: #c45c00; border-color: #c45c00; }
    #grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: .75rem; padding: 1.25rem; }
    figure { margin: 0; background: #1a1a1a; border: 1px solid #333; border-radius: 8px; overflow: hidden; }
    img { width: 100%; height: 160px; object-fit: cover; display: block; background: #000; cursor: pointer; }
    figcaption { padding: .5rem .65rem; font-size: .8rem; color: #bbb; }
    .empty { padding: 2rem 1.25rem; color: #888; }
    dialog { border: none; padding: 0; background: transparent; max-width: 96vw; }
    dialog img { max-width: 96vw; max-height: 90vh; height: auto; object-fit: contain; }
  </style>
</head>
<body>
  <header>
    <h1>Cat monitor</h1>
    <div class="meta" id="status">Loading…</div>
  </header>
  <nav>
    <button id="tab-frames" class="active" type="button">Recent frames</button>
    <button id="tab-detections" type="button">Cat detections</button>
  </nav>
  <div id="grid"></div>
  <dialog id="lightbox"><img id="full" alt="Full snapshot"></dialog>
  <script>
    const grid = document.getElementById("grid");
    const status = document.getElementById("status");
    const lightbox = document.getElementById("lightbox");
    const full = document.getElementById("full");
    let kind = "frames";

    function show(next) {
      kind = next;
      document.getElementById("tab-frames").classList.toggle("active", kind === "frames");
      document.getElementById("tab-detections").classList.toggle("active", kind === "detections");
      load();
    }
    document.getElementById("tab-frames").onclick = () => show("frames");
    document.getElementById("tab-detections").onclick = () => show("detections");
    lightbox.onclick = () => lightbox.close();

    async function load() {
      const res = await fetch("/api/" + kind);
      const items = await res.json();
      status.textContent = items.length
        ? items.length + " " + (kind === "frames" ? "recent frames" : "cat detections")
        : (kind === "frames" ? "No frames captured yet." : "No cat detections yet.");
      if (!items.length) {
        grid.innerHTML = '<div class="empty">Nothing here yet. Frames appear as the camera is polled.</div>';
        return;
      }
      grid.innerHTML = items.map(item => `
        <figure>
          <img src="${item.url}" alt="${item.name}" data-full="${item.url}">
          <figcaption>${item.label}</figcaption>
        </figure>`).join("");
      grid.querySelectorAll("img").forEach(img => {
        img.onclick = () => { full.src = img.dataset.full; lightbox.showModal(); };
      });
    }
    load();
    setInterval(load, 5000);
  </script>
</body>
</html>
"""


class SnapshotRequestHandler(BaseHTTPRequestHandler):
    store: SnapshotStore

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        logger.debug("%s - %s", self.address_string(), format % args)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path in {"/", "/index.html"}:
            self._send(200, "text/html; charset=utf-8", _PAGE.encode("utf-8"))
            return
        if path == "/api/frames":
            self._send_json(self._items("frames", self.store.list_frames()))
            return
        if path == "/api/detections":
            self._send_json(self._items("detections", self.store.list_detections()))
            return
        if path.startswith("/media/frames/") or path.startswith("/media/detections/"):
            _, _, kind, name = path.split("/", 3)
            file_path = self.store.resolve(kind, name)
            if file_path is None:
                self._send(404, "text/plain; charset=utf-8", b"Not found")
                return
            self._send(200, "image/jpeg", file_path.read_bytes())
            return
        self._send(404, "text/plain; charset=utf-8", b"Not found")

    def _items(self, kind: str, paths) -> list[dict[str, str]]:
        items = []
        for path in paths:
            items.append(
                {
                    "name": path.name,
                    "url": f"/media/{kind}/{path.name}",
                    "label": path.name,
                }
            )
        return items

    def _send(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, payload: object) -> None:
        body = json.dumps(payload).encode("utf-8")
        self._send(200, "application/json", body)


class SnapshotUI:
    """Background HTTP server for the snapshot gallery."""

    def __init__(self, store: SnapshotStore, host: str = "0.0.0.0", port: int = 8787) -> None:
        handler = type(
            "BoundSnapshotHandler",
            (SnapshotRequestHandler,),
            {"store": store},
        )
        self.httpd = ThreadingHTTPServer((host, port), handler)
        self.host, self.port = self.httpd.server_address[0], int(self.httpd.server_address[1])
        self._thread = threading.Thread(target=self.httpd.serve_forever, name="snapshot-ui", daemon=True)

    def start(self) -> None:
        self._thread.start()
        logger.info("Snapshot UI listening on http://%s:%s", self.host, self.port)

    def stop(self) -> None:
        self.httpd.shutdown()
        self._thread.join(timeout=5)
        self.httpd.server_close()


def start_snapshot_ui(store: SnapshotStore, host: str = "0.0.0.0", port: int = 8787) -> SnapshotUI:
    ui = SnapshotUI(store, host=host, port=port)
    ui.start()
    return ui
