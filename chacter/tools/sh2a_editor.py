#!/usr/bin/env python3
"""Minimal browser editor for shell-embedded ANSI half-block art.

The editor treats the source as a 45x46 half-pixel grid, lets the user erase
pixels with left-drag, restore from the original art with right-click, and
saves back to the same `printf "..."` shell format.
"""

from __future__ import annotations

import argparse
import json
import re
import threading
import webbrowser
from copy import deepcopy
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_INPUT = SCRIPT_DIR.parent / "bob_tui_ansi.sh"
PRINTF_RE = re.compile(
    r'^\s*printf\s+(?P<quote>["\'])(?P<body>.*)(?P=quote)\s*;?\s*$',
    re.DOTALL,
)
SGR_RE = re.compile(r"\x1b\[([0-9;]*)m")


def extract_printf_body(source: str) -> str:
    match = PRINTF_RE.match(source.replace("\ufeff", "").strip())
    if not match:
        raise ValueError("Input does not match a single printf-quoted payload.")
    return match.group("body")


def decode_shell_escapes(body: str) -> str:
    out: list[str] = []
    i = 0
    n = len(body)
    simple = {
        "a": "\a",
        "b": "\b",
        "e": "\x1b",
        "E": "\x1b",
        "f": "\f",
        "n": "\n",
        "r": "\r",
        "t": "\t",
        "v": "\v",
        "\\": "\\",
        '"': '"',
        "'": "'",
    }
    while i < n:
        ch = body[i]
        if ch != "\\":
            out.append(ch)
            i += 1
            continue

        i += 1
        if i >= n:
            out.append("\\")
            break

        esc = body[i]
        if esc in simple:
            out.append(simple[esc])
            i += 1
            continue

        if esc in "01234567":
            j = i
            while j < n and (j - i) < 3 and body[j] in "01234567":
                j += 1
            out.append(chr(int(body[i:j], 8)))
            i = j
            continue

        if esc == "x":
            j = i + 1
            hexchars: list[str] = []
            while j < n and len(hexchars) < 2 and body[j] in "0123456789abcdefABCDEF":
                hexchars.append(body[j])
                j += 1
            if hexchars:
                out.append(chr(int("".join(hexchars), 16)))
                i = j
            else:
                out.append("x")
                i += 1
            continue

        out.append(esc)
        i += 1

    return "".join(out)


def encode_shell_string(text: str) -> str:
    text = text.replace("\\", "\\\\")
    text = text.replace('"', '\\"')
    text = text.replace("\x1b", "\\e")
    return text


def xterm_to_rgb(index: int) -> str:
    if not 0 <= index <= 255:
        raise ValueError(f"Invalid ANSI 256 color index: {index}")
    base16 = [
        "#000000",
        "#800000",
        "#008000",
        "#808000",
        "#000080",
        "#800080",
        "#008080",
        "#c0c0c0",
        "#808080",
        "#ff0000",
        "#00ff00",
        "#ffff00",
        "#0000ff",
        "#ff00ff",
        "#00ffff",
        "#ffffff",
    ]
    if index < 16:
        return base16[index]
    if index < 232:
        value = index - 16
        r = value // 36
        g = (value % 36) // 6
        b = value % 6
        scale = [0, 95, 135, 175, 215, 255]
        return f"#{scale[r]:02x}{scale[g]:02x}{scale[b]:02x}"
    gray = 8 + (index - 232) * 10
    return f"#{gray:02x}{gray:02x}{gray:02x}"


def apply_sgr_codes(codes: list[int], state: dict[str, int | None]) -> None:
    if not codes:
        state["fg"] = None
        state["bg"] = None
        return

    i = 0
    while i < len(codes):
        code = codes[i]
        if code == 0:
            state["fg"] = None
            state["bg"] = None
        elif code == 39:
            state["fg"] = None
        elif code == 49:
            state["bg"] = None
        elif code == 38 and i + 2 < len(codes) and codes[i + 1] == 5:
            state["fg"] = codes[i + 2]
            i += 2
        elif code == 48 and i + 2 < len(codes) and codes[i + 1] == 5:
            state["bg"] = codes[i + 2]
            i += 2
        i += 1


@dataclass
class ArtDocument:
    path: Path
    width: int
    pixels: list[list[int | None]]
    original_pixels: list[list[int | None]]

    @property
    def height(self) -> int:
        return len(self.pixels)

    @classmethod
    def load(cls, path: Path) -> "ArtDocument":
        source = path.read_text(encoding="utf-8")
        body = extract_printf_body(source)
        decoded = decode_shell_escapes(body)
        rows = cls._parse_pixels(decoded)
        width = len(rows[0]) if rows else 0
        if width == 0 or len(rows) % 2 != 0:
            raise ValueError("Parsed art has an invalid grid size.")
        return cls(path=path, width=width, pixels=deepcopy(rows), original_pixels=deepcopy(rows))

    @staticmethod
    def _parse_pixels(decoded: str) -> list[list[int | None]]:
        half_rows: list[list[int | None]] = []
        for raw_line in decoded.splitlines():
            state: dict[str, int | None] = {"fg": None, "bg": None}
            top_row: list[int | None] = []
            bottom_row: list[int | None] = []
            cursor = 0
            for match in SGR_RE.finditer(raw_line):
                for ch in raw_line[cursor:match.start()]:
                    top, bottom = ArtDocument._char_to_halves(ch, state["fg"], state["bg"])
                    top_row.append(top)
                    bottom_row.append(bottom)
                codes = [int(part) for part in match.group(1).split(";") if part]
                apply_sgr_codes(codes, state)
                cursor = match.end()
            for ch in raw_line[cursor:]:
                top, bottom = ArtDocument._char_to_halves(ch, state["fg"], state["bg"])
                top_row.append(top)
                bottom_row.append(bottom)
            half_rows.append(top_row)
            half_rows.append(bottom_row)

        width = max((len(row) for row in half_rows), default=0)
        for row in half_rows:
            row.extend([None] * (width - len(row)))
        return half_rows

    @staticmethod
    def _char_to_halves(
        ch: str,
        fg: int | None,
        bg: int | None,
    ) -> tuple[int | None, int | None]:
        if ch == " ":
            return bg, bg
        if ch == "▀":
            return fg, bg
        if ch == "▄":
            return bg, fg
        raise ValueError(f"Unsupported visible character in art: {ch!r}")

    def replace_pixels(self, pixels: list[list[int | None]]) -> None:
        if len(pixels) != self.height:
            raise ValueError("Pixel height mismatch.")
        for row in pixels:
            if len(row) != self.width:
                raise ValueError("Pixel width mismatch.")
        self.pixels = pixels

    def save(self) -> None:
        backup = self.path.with_suffix(self.path.suffix + ".bak")
        if not backup.exists():
            backup.write_text(self.path.read_text(encoding="utf-8"), encoding="utf-8")
        rendered = self._render_shell_script()
        self.path.write_text(rendered, encoding="utf-8")

    def _render_shell_script(self) -> str:
        lines: list[str] = []
        for row_index in range(0, self.height, 2):
            chars: list[tuple[str, int | None, int | None]] = []
            top_row = self.pixels[row_index]
            bottom_row = self.pixels[row_index + 1]
            for col in range(self.width):
                chars.append(self._halves_to_char(top_row[col], bottom_row[col]))
            lines.append(self._render_line(chars))
        payload = "\n".join(lines)
        return f'printf "{encode_shell_string(payload)}\n";\n'

    @staticmethod
    def _halves_to_char(
        top: int | None,
        bottom: int | None,
    ) -> tuple[str, int | None, int | None]:
        if top is None and bottom is None:
            return " ", None, None
        if top == bottom and top is not None:
            return " ", None, top
        if top is not None and bottom is None:
            return "▀", top, None
        if top is None and bottom is not None:
            return "▄", bottom, None
        return "▀", top, bottom

    @staticmethod
    def _render_line(chars: list[tuple[str, int | None, int | None]]) -> str:
        out = ["\x1b[49m"]
        current_fg: int | None = None
        current_bg: int | None = None
        for ch, fg, bg in chars:
            codes: list[str] = []
            if fg != current_fg:
                codes.append("39" if fg is None else f"38;5;{fg}")
                current_fg = fg
            if bg != current_bg:
                codes.append("49" if bg is None else f"48;5;{bg}")
                current_bg = bg
            if codes:
                out.append(f"\x1b[{';'.join(codes)}m")
            out.append(ch)
        out.append("\x1b[m")
        return "".join(out)

    def to_json(self) -> dict[str, Any]:
        palette = {str(index): xterm_to_rgb(index) for index in self._used_colors()}
        return {
            "sourcePath": str(self.path.resolve()),
            "width": self.width,
            "height": self.height,
            "pixels": self.pixels,
            "originalPixels": self.original_pixels,
            "palette": palette,
        }

    def _used_colors(self) -> list[int]:
        used = {
            color
            for row in (self.pixels + self.original_pixels)
            for color in row
            if color is not None
        }
        return sorted(used)


HTML_PAGE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>SH2A Eraser</title>
  <style>
    :root {
      --bg: #efe9de;
      --panel: #fffaf1;
      --ink: #211b18;
      --muted: #6c625a;
      --accent: #8b3d2b;
      --accent-2: #c56a3d;
      --line: #d7c8b5;
      --shadow: rgba(51, 30, 19, 0.14);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: Georgia, "Times New Roman", serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(197, 106, 61, 0.14), transparent 28%),
        radial-gradient(circle at bottom right, rgba(139, 61, 43, 0.16), transparent 32%),
        linear-gradient(180deg, #f6f0e6 0%, var(--bg) 100%);
    }
    .shell {
      max-width: 1180px;
      margin: 0 auto;
      min-height: 100vh;
      padding: 24px;
    }
    .toolbar {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      align-items: center;
      padding: 14px;
      border: 1px solid var(--line);
      border-radius: 16px;
      background: rgba(255, 250, 241, 0.88);
      box-shadow: 0 12px 32px var(--shadow);
      backdrop-filter: blur(10px);
      position: sticky;
      top: 12px;
      z-index: 10;
    }
    .toolbar button {
      border: 0;
      border-radius: 999px;
      padding: 10px 16px;
      background: var(--accent);
      color: white;
      cursor: pointer;
      font: inherit;
    }
    .toolbar button.secondary {
      background: #dbc8b2;
      color: var(--ink);
    }
    .toolbar .zoom {
      display: flex;
      gap: 8px;
      align-items: center;
      padding: 0 4px;
      color: var(--muted);
    }
    .toolbar input[type="range"] {
      accent-color: var(--accent-2);
    }
    .meta {
      margin-left: auto;
      color: var(--muted);
      font-size: 14px;
    }
    .status {
      padding: 12px 2px 0;
      color: var(--muted);
      min-height: 36px;
    }
    .canvas-wrap {
      margin-top: 14px;
      padding: 18px;
      border: 1px solid var(--line);
      border-radius: 20px;
      background: linear-gradient(180deg, rgba(255,255,255,0.85), rgba(255,247,235,0.94));
      box-shadow: 0 18px 42px var(--shadow);
      overflow: auto;
    }
    canvas {
      display: block;
      cursor: crosshair;
      image-rendering: pixelated;
      transform-origin: top left;
      background:
        linear-gradient(45deg, #f2eadf 25%, transparent 25%, transparent 75%, #f2eadf 75%, #f2eadf),
        linear-gradient(45deg, #f2eadf 25%, transparent 25%, transparent 75%, #f2eadf 75%, #f2eadf);
      background-position: 0 0, 8px 8px;
      background-size: 16px 16px;
      border-radius: 12px;
      border: 1px solid #d5c4ad;
    }
    .legend {
      margin-top: 10px;
      color: var(--muted);
      font-size: 14px;
    }
    .legend code {
      background: rgba(0,0,0,0.05);
      padding: 2px 6px;
      border-radius: 999px;
    }
  </style>
</head>
<body>
  <div class="shell">
    <div class="toolbar">
      <button id="saveBtn">Save</button>
      <button id="undoBtn" class="secondary">Undo</button>
      <button id="reloadBtn" class="secondary">Reload</button>
      <button id="resetBtn" class="secondary">Reset To Original</button>
      <label class="zoom">
        Zoom
        <input id="zoom" type="range" min="8" max="28" value="14">
        <span id="zoomValue">14px</span>
      </label>
      <div class="meta" id="meta"></div>
    </div>
    <div class="status" id="status">Loading...</div>
    <div class="canvas-wrap">
      <canvas id="art" width="10" height="10"></canvas>
      <div class="legend">
        Left drag erases pixels. Right click restores the original pixel. <code>Ctrl+S</code> saves.
      </div>
    </div>
  </div>
  <script>
    const canvas = document.getElementById('art');
    const ctx = canvas.getContext('2d');
    const statusEl = document.getElementById('status');
    const metaEl = document.getElementById('meta');
    const zoomEl = document.getElementById('zoom');
    const zoomValueEl = document.getElementById('zoomValue');
    const saveBtn = document.getElementById('saveBtn');
    const undoBtn = document.getElementById('undoBtn');
    const reloadBtn = document.getElementById('reloadBtn');
    const resetBtn = document.getElementById('resetBtn');

    let data = null;
    let history = [];
    let cellSize = Number(zoomEl.value);
    let drawMode = null;

    function clonePixels(pixels) {
      return pixels.map(row => row.slice());
    }

    function colorFor(value) {
      return value == null ? null : (data.palette[String(value)] || '#000000');
    }

    function setStatus(message, isError = false) {
      statusEl.textContent = message;
      statusEl.style.color = isError ? '#8b1e1e' : 'var(--muted)';
    }

    function resizeCanvas() {
      canvas.width = data.width * cellSize;
      canvas.height = data.height * cellSize;
      zoomValueEl.textContent = `${cellSize}px`;
      draw();
    }

    function drawGrid() {
      ctx.save();
      ctx.strokeStyle = 'rgba(74, 47, 32, 0.08)';
      ctx.lineWidth = 1;
      for (let x = 0; x <= data.width; x += 1) {
        ctx.beginPath();
        ctx.moveTo(x * cellSize + 0.5, 0);
        ctx.lineTo(x * cellSize + 0.5, canvas.height);
        ctx.stroke();
      }
      for (let y = 0; y <= data.height; y += 1) {
        ctx.beginPath();
        ctx.moveTo(0, y * cellSize + 0.5);
        ctx.lineTo(canvas.width, y * cellSize + 0.5);
        ctx.stroke();
      }
      ctx.restore();
    }

    function draw() {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      for (let y = 0; y < data.height; y += 1) {
        for (let x = 0; x < data.width; x += 1) {
          const value = data.pixels[y][x];
          const color = colorFor(value);
          if (!color) continue;
          ctx.fillStyle = color;
          ctx.fillRect(x * cellSize, y * cellSize, cellSize, cellSize);
        }
      }
      drawGrid();
    }

    function eventToPixel(event) {
      const rect = canvas.getBoundingClientRect();
      const x = Math.floor((event.clientX - rect.left) * (canvas.width / rect.width) / cellSize);
      const y = Math.floor((event.clientY - rect.top) * (canvas.height / rect.height) / cellSize);
      if (x < 0 || y < 0 || x >= data.width || y >= data.height) {
        return null;
      }
      return { x, y };
    }

    function pushHistory() {
      history.push(clonePixels(data.pixels));
      if (history.length > 50) history.shift();
    }

    function applyAt(event) {
      const pos = eventToPixel(event);
      if (!pos) return;
      if (drawMode === 'erase') {
        data.pixels[pos.y][pos.x] = null;
      } else if (drawMode === 'restore') {
        data.pixels[pos.y][pos.x] = data.originalPixels[pos.y][pos.x];
      }
      draw();
    }

    async function loadArt() {
      const response = await fetch('/api/art');
      if (!response.ok) throw new Error('Failed to load art');
      data = await response.json();
      history = [];
      metaEl.textContent = `${data.width} x ${data.height} half-pixels | ${data.sourcePath}`;
      resizeCanvas();
      setStatus('Loaded. Left drag erases. Right click restores.');
    }

    async function saveArt() {
      const response = await fetch('/api/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pixels: data.pixels })
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.error || 'Save failed');
      }
      setStatus(payload.message);
    }

    canvas.addEventListener('contextmenu', (event) => event.preventDefault());
    canvas.addEventListener('mousedown', (event) => {
      if (!data) return;
      drawMode = event.button === 2 ? 'restore' : 'erase';
      pushHistory();
      applyAt(event);
    });
    window.addEventListener('mouseup', () => {
      drawMode = null;
    });
    canvas.addEventListener('mousemove', (event) => {
      if (!drawMode) return;
      applyAt(event);
    });

    zoomEl.addEventListener('input', () => {
      cellSize = Number(zoomEl.value);
      resizeCanvas();
    });

    saveBtn.addEventListener('click', async () => {
      try {
        await saveArt();
      } catch (error) {
        setStatus(error.message, true);
      }
    });

    undoBtn.addEventListener('click', () => {
      if (history.length === 0) {
        setStatus('Nothing to undo.');
        return;
      }
      data.pixels = history.pop();
      draw();
      setStatus('Undid the last edit.');
    });

    reloadBtn.addEventListener('click', async () => {
      try {
        await loadArt();
      } catch (error) {
        setStatus(error.message, true);
      }
    });

    resetBtn.addEventListener('click', () => {
      pushHistory();
      data.pixels = clonePixels(data.originalPixels);
      draw();
      setStatus('Reset the canvas to the original file.');
    });

    window.addEventListener('keydown', async (event) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
        event.preventDefault();
        try {
          await saveArt();
        } catch (error) {
          setStatus(error.message, true);
        }
        return;
      }
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'z') {
        event.preventDefault();
        undoBtn.click();
      }
    });

    loadArt().catch((error) => setStatus(error.message, true));
  </script>
</body>
</html>
"""


class EditorHandler(BaseHTTPRequestHandler):
    server: "EditorServer"

    def do_GET(self) -> None:  # noqa: N802
        if self.path in ("/", "/index.html"):
            body = HTML_PAGE.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if self.path == "/api/art":
            payload = json.dumps(self.server.document.to_json()).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/api/save":
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length)
            payload = json.loads(body.decode("utf-8"))
            pixels = payload["pixels"]
            self.server.document.replace_pixels(pixels)
            self.server.document.save()
            response = {
                "message": f"Saved {self.server.document.path} "
                f"and wrote a one-time backup next to it if needed.",
            }
            self._send_json(HTTPStatus.OK, response)
        except Exception as exc:  # pragma: no cover - interactive error path
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})

    def _send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        return


class EditorServer(ThreadingHTTPServer):
    def __init__(self, server_address: tuple[str, int], document: ArtDocument):
        super().__init__(server_address, EditorHandler)
        self.document = document


def run_roundtrip_check(path: Path) -> int:
    document = ArtDocument.load(path)
    rendered = document._render_shell_script()
    reparsed = ArtDocument._parse_pixels(decode_shell_escapes(extract_printf_body(rendered)))
    if reparsed != document.pixels:
        print("Roundtrip failed.")
        return 1
    print(f"Roundtrip OK for {path}")
    print(f"Grid: {document.width} x {document.height} half-pixels")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", nargs="?", default=str(DEFAULT_INPUT))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--check-roundtrip", action="store_true")
    args = parser.parse_args()

    path = Path(args.input).resolve()
    if args.check_roundtrip:
        return run_roundtrip_check(path)

    document = ArtDocument.load(path)
    server = EditorServer((args.host, args.port), document)
    url = f"http://{args.host}:{args.port}/"
    print(f"Editing {path}")
    print(f"Open {url}")

    if not args.no_browser:
        threading.Timer(0.35, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping editor.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
