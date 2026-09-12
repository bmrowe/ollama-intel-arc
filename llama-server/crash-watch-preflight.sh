#!/usr/bin/env bash
# Preflight for the Unraid reset watch (see crash-analysis-2026-08-16.md).
# Run from any machine on the LAN. Verifies the capture path is armed.
# Host-shell checks it cannot do are listed at the end.

PARENT=192.168.1.195:19999
UNRAID=192.168.1.198
PVE=192.168.1.199
LLAMA=192.168.1.2:8080

pass=0; fail=0
ok()   { printf '  \033[32mPASS\033[0m  %s\n' "$1"; pass=$((pass+1)); }
bad()  { printf '  \033[31mFAIL\033[0m  %s\n' "$1"; fail=$((fail+1)); }

echo "=== reachability ==="
for hp in "$PVE:22 pve" "$UNRAID:80 unraid" "${PARENT%:*}:19999 netdata-parent" "${LLAMA%:*}:8080 llama-server"; do
  set -- $hp; hostport=$1; name=$2
  h=${hostport%:*}; p=${hostport##*:}
  if nc -z -G 4 "$h" "$p" 2>/dev/null; then ok "$name ($h:$p)"; else bad "$name ($h:$p) unreachable"; fi
done

echo "=== netdata parent ==="
info=$(curl -s -m 8 "http://$PARENT/api/v1/info")
if grep -q '"unraid"' <<<"$info"; then ok "unraid is a mirrored host"; else bad "unraid NOT mirrored — streaming is down"; fi

last=$(curl -s -m 8 "http://$PARENT/host/unraid/api/v1/data?chart=system.cpu&after=-60&points=1&format=csv" | tail -1 | cut -d, -f1)
if [ -n "$last" ]; then
  age=$(( $(date +%s) - $(date -j -f "%Y-%m-%d %H:%M:%S" "$last" +%s 2>/dev/null || date -d "$last" +%s) ))
  if [ "$age" -lt 180 ]; then ok "fresh unraid data through parent (${age}s old)"
  else bad "stale unraid data through parent (${age}s old)"; fi
else
  bad "no unraid data through parent"
fi

echo "=== llama-server ==="
code=$(curl -s -m 8 -o /dev/null -w '%{http_code}' "http://$LLAMA/health")
[ "$code" = "200" ] && ok "health 200" || bad "health $code"
props=$(curl -s -m 8 "http://$LLAMA/props")
grep -q 'Qwen3-VL-4B-Instruct-Q4_K_M' <<<"$props" && ok "running the 4B" || bad "model is NOT the 4B — auto-update may have changed it"
grep -q '"n_ctx":8192' <<<"$props" && ok "n_ctx 8192" || bad "n_ctx is not 8192"
curl -s -m 8 "http://$LLAMA/v1/models" | grep -q '"qwen3-vl"' && ok "alias qwen3-vl present (Frigate contract)" || bad "alias missing — Frigate will fail init"

echo "=== vision (image path actually works) ==="
if python3 "$(dirname "$0")/crash-watch-vision.py" "http://$LLAMA"; then pass=$((pass+1)); else fail=$((fail+1)); fi

echo
echo "$pass passed, $fail failed"
echo
cat <<'MANUAL'
Still needs a host shell:

  # pve — NIC fix holding?
  journalctl -k --since "24 hours ago" | grep -c "Detected Hardware Unit Hang"   # want 0
  ethtool -k nic0 | grep -E "^(tcp|generic)-.*offload"                            # want off
  systemctl is-active nic-watchdog.timer                                          # if installed

  # LXC 110 — syslog actually receiving, and disk sane
  ls -la --time-style=full-iso /var/log/remote/ ; df -h /

  # unraid — VRAM footprint unchanged after any auto-update
  P=$(docker inspect -f '{{.State.Pid}}' llama-server)
  grep -h drm-total-local0 /proc/$P/fdinfo/* | sort -u                            # want ~4418400 KiB (post 2026-08-17 build)
MANUAL
