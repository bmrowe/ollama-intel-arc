#!/usr/bin/env python3
"""End-to-end vision check for llama-server: builds a red/blue PNG in memory,
sends it, and verifies the model actually describes it. Exits 0 on success.
A clean startup is NOT proof the image path works -- the 5.64 GiB OOM run on
2026-08-16 reported 'model loaded' with the vision buffer dead."""
import zlib, struct, base64, json, sys, urllib.request

URL = sys.argv[1] if len(sys.argv) > 1 else "http://192.168.1.2:8080"

def png(w, h, rows):
    raw = b''.join(b'\x00' + bytes(r) for r in rows)
    def chunk(t, d):
        return struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)
    return (b'\x89PNG\r\n\x1a\n'
            + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))

W = H = 128
rows = [[c for x in range(W) for c in ([255, 0, 0] if x < W // 2 else [0, 0, 255])] for _ in range(H)]
b64 = base64.b64encode(png(W, H, rows)).decode()

body = json.dumps({"model": "qwen3-vl", "max_tokens": 64, "messages": [{"role": "user", "content": [
    {"type": "text", "text": "What two colors are in this image, and which side is each on?"},
    {"type": "image_url", "image_url": {"url": "data:image/png;base64," + b64}}]}]}).encode()

import subprocess, tempfile, os
# NOTE: POST via curl, not urllib. macOS Local Network privacy can block the python
# binary from LAN sockets (EHOSTUNREACH) while curl is permitted -- observed 2026-08-18.
with tempfile.NamedTemporaryFile("wb", suffix=".json", delete=False) as f:
    f.write(body); payload = f.name
try:
    r = subprocess.run(["curl", "-s", "-m", "120", URL + "/v1/chat/completions",
                        "-H", "Content-Type: application/json", "--data-binary", "@" + payload],
                       capture_output=True, text=True)
    txt = (json.loads(r.stdout)["choices"][0]["message"].get("content") or "").lower()
except Exception as e:
    print(f"  \033[31mFAIL\033[0m  vision request failed: {type(e).__name__} {e}")
    sys.exit(1)
finally:
    os.unlink(payload)

if "red" in txt and "blue" in txt and "left" in txt:
    print("  \033[32mPASS\033[0m  vision path works (image correctly described)")
    sys.exit(0)
print(f"  \033[31mFAIL\033[0m  vision path suspect, model said: {txt[:160]!r}")
sys.exit(1)
