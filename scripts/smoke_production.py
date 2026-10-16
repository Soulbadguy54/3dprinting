"""Safe read-only production smoke; invalid username never touches a real account."""
import json
import secrets
import time
import urllib.error
import urllib.request

BASE = "https://rateapp-delta.vercel.app"


def probe(method, path, body=None):
    request = urllib.request.Request(
        BASE + path,
        data=json.dumps(body).encode() if body is not None else None,
        method=method,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "RateApp-CI-Smoke/1.0",
            "Cache-Control": "no-store",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            status = response.status
            content = response.read(4000)
    except urllib.error.HTTPError as err:
        status = err.code
        content = err.read(4000)
    return status, content


# The latest Git deployment can still be rolling out when CI finishes.
for attempt in range(12):
    try:
        status, body = probe("GET", "/api/health")
        payload = json.loads(body)
        if status == 200 and payload.get("database", {}).get("reachable"):
            break
        print(f"Health check not ready: status {status}, attempt {attempt + 1}")
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Health check unavailable: {type(exc).__name__}, attempt {attempt + 1}")
    time.sleep(10)
else:
    raise SystemExit("Production API/DB was not ready after polling")

for method, endpoint, body, expected in [
    ("GET", "/api/bootstrap", None, 401),
    ("GET", "/api/export", None, 401),
    ("POST", "/api/auth/login", {"identifier": "ci-nonexistent-" + secrets.token_hex(8), "pin": "12345678"}, 401),
]:
    status, _ = probe(method, endpoint, body)
    print(f"{method} {endpoint}: HTTP {status}")
    if status != expected:
        raise SystemExit(f"Unexpected response for {endpoint}: {status}, expected {expected}")
print("Production smoke: PASS")
