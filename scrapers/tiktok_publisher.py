"""
tiktok_publisher.py — TikTok Content Posting API v2 ile video yayınlar.
Token hazır olmadığında publish_video() {"success": False} döner, bot çalışmaya devam eder.
"""
import os
import time
import requests


class TikTokPublisher:
    BASE_URL = "https://open.tiktokapis.com/v2"

    def __init__(self, access_token: str):
        self.token = access_token.strip() if access_token else ""
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json; charset=UTF-8",
        }

    # ── Ana metod ───────────────────────────────────────────────────────────────
    def publish_video(
        self,
        video_path: str,
        caption: str,
        hashtags: list = None,
        privacy: str = "SELF_ONLY",   # Test modunda SELF_ONLY, hazırsa PUBLIC_TO_EVERYONE
    ) -> dict:
        """
        Videoyu TikTok'a yükler.
        Döner: {"success": bool, "share_id": str|None, "error": str|None}
        """
        if not self.token:
            return {"success": False, "error": "TikTok token ayarlanmamış"}

        # Caption + hashtagler
        tag_str = " ".join(f"#{t.strip().lstrip('#')}" for t in (hashtags or []) if t.strip())
        full_caption = f"{caption} {tag_str}".strip()[:2200]   # TikTok limit

        video_size = os.path.getsize(video_path)

        init = self._init_upload(video_size, full_caption, privacy)
        if not init:
            return {"success": False, "error": "Upload init başarısız (API yanıt vermedi)"}

        if not self._upload_bytes(init["upload_url"], video_path, video_size):
            return {"success": False, "error": "Video byte'ları gönderilemedi"}

        return self._poll_status(init["publish_id"])

    # ── 1. Upload init ──────────────────────────────────────────────────────────
    def _init_upload(self, video_size: int, caption: str, privacy: str) -> dict | None:
        try:
            r = requests.post(
                f"{self.BASE_URL}/post/publish/video/init/",
                headers=self.headers,
                json={
                    "post_info": {
                        "title": caption,
                        "privacy_level": privacy,
                        "disable_duet": False,
                        "disable_comment": False,
                        "disable_stitch": False,
                        "video_cover_timestamp_ms": 1000,
                    },
                    "source_info": {
                        "source": "FILE_UPLOAD",
                        "video_size": video_size,
                        "chunk_size": video_size,
                        "total_chunk_count": 1,
                    },
                },
                timeout=30,
            )
            if r.status_code == 200:
                data = r.json().get("data", {})
                return {
                    "publish_id": data.get("publish_id"),
                    "upload_url": data.get("upload_url"),
                }
            print(f"TikTok init HTTP {r.status_code}: {r.text[:300]}")
        except Exception as e:
            print(f"TikTok init istisnası: {e}")
        return None

    # ── 2. Video yükleme ────────────────────────────────────────────────────────
    def _upload_bytes(self, upload_url: str, video_path: str, video_size: int) -> bool:
        try:
            with open(video_path, "rb") as f:
                r = requests.put(
                    upload_url,
                    data=f,
                    headers={
                        "Content-Type": "video/mp4",
                        "Content-Range": f"bytes 0-{video_size - 1}/{video_size}",
                        "Content-Length": str(video_size),
                    },
                    timeout=180,
                )
            return r.status_code in (200, 201, 206)
        except Exception as e:
            print(f"TikTok upload istisnası: {e}")
            return False

    # ── 3. Status polling ───────────────────────────────────────────────────────
    def _poll_status(self, publish_id: str) -> dict:
        terminal_fail = {
            "FAILED",
            "SPAM_RISK_TOO_MANY_POSTS",
            "SPAM_RISK_USER_BANNED_FROM_POSTING",
            "AUDIENCE_NOT_ELIGIBLE",
        }
        for _ in range(15):
            time.sleep(4)
            try:
                r = requests.post(
                    f"{self.BASE_URL}/post/publish/status/fetch/",
                    headers=self.headers,
                    json={"publish_id": publish_id},
                    timeout=20,
                )
                if r.status_code == 200:
                    status = r.json().get("data", {}).get("status", "")
                    if status == "PUBLISH_COMPLETE":
                        return {"success": True,  "share_id": publish_id, "error": None}
                    if status in terminal_fail:
                        return {"success": False, "share_id": None, "error": f"TikTok: {status}"}
            except Exception:
                pass
        return {"success": False, "share_id": None, "error": "Status polling zaman aşımı (60s)"}
