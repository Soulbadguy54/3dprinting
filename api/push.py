"""Web Push transport and push-service endpoint validation for RateApp."""
import json
import logging
import os
from urllib.parse import urlsplit

from pywebpush import WebPushException, webpush

from api.models import PushSubscription

# A browser-chosen Web Push endpoint is a server-side POST destination.
# Restrict it to known push services to prevent SSRF via stored subscriptions.
PUSH_DOMAINS = (
    "fcm.googleapis.com",
    "updates.push.services.mozilla.com",
    "notify.windows.com",
    "push.apple.com",
    "push.services.mozilla.com",
    "push.microsoft.com",
    "push.vivaldi.net",
)


def valid_push_endpoint(endpoint: str) -> bool:
    if not isinstance(endpoint, str) or not 1 <= len(endpoint) <= 2048:
        return False
    try:
        parsed = urlsplit(endpoint)
        host = (parsed.hostname or "").lower().rstrip(".")
        return (
            parsed.scheme == "https"
            and parsed.port in (None, 443)
            and parsed.username is None
            and parsed.password is None
            and bool(parsed.path)
            and host != ""
            and any(host == domain or host.endswith("." + domain) for domain in PUSH_DOMAINS)
        )
    except ValueError:
        return False


def push_ready() -> bool:
    return bool(os.getenv("VAPID_PUBLIC_KEY") and os.getenv("VAPID_PRIVATE_KEY"))


def _push_cover_url(value: str | None) -> str | None:
    """Only accept cover thumbnails served by IGDB; never relay arbitrary URLs."""
    if not value:
        return None
    try:
        url = urlsplit(value)
    except ValueError:
        return None
    if (
        url.scheme == "https"
        and url.netloc == "images.igdb.com"
        and url.path.startswith("/igdb/image/upload/")
        and not url.username
        and not url.password
        and len(value) <= 1000
    ):
        return value
    return None


def send_push(subscription: PushSubscription, *, title: str, body: str,
              game_id: int, tag: str, cover_url: str | None = None) -> tuple[bool, bool]:
    """Returns (accepted_by_push_service, subscription_expired).

    A successful push-service response is not proof of an Android notification:
    user permission, network connection and OS delivery still apply.
    """
    if not push_ready():
        return False, False

    payload = json.dumps({
        "title": title,
        "body": body,
        "url": f"/?game={game_id}",
        "tag": tag,
        "coverUrl": _push_cover_url(cover_url),
    }, ensure_ascii=False)
    try:
        webpush(
            subscription_info={
                "endpoint": subscription.endpoint,
                "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth},
            },
            data=payload,
            vapid_private_key=os.environ["VAPID_PRIVATE_KEY"],
            vapid_claims={"sub": os.getenv("VAPID_SUBJECT", "https://rateapp-delta.vercel.app")},
            ttl=24 * 3600,
            timeout=8,
        )
        return True, False
    except WebPushException as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        logging.warning("Push delivery failed (subscription id=%s, HTTP=%s)",
                        subscription.id, status)
        return False, status in (404, 410)
    except Exception:
        logging.exception("Push transport error (subscription id=%s)", subscription.id)
        return False, False
