"""
YouTube Uploader — handles OAuth2 auth and video uploads via YouTube Data API v3.
"""

import os
import logging
import pickle

from google_auth_oauthlib.flow import Flow, InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

from config import CLIENT_SECRETS_FILE, TOKEN_FILE, YOUTUBE_SCOPES

logger = logging.getLogger(__name__)


class YouTubeUploader:
    """Manages YouTube OAuth credentials and video uploads."""

    def __init__(self):
        self.credentials = None
        self.youtube = None
        self._channel_name = None
        self._load_credentials()

    # ── Credential Management ─────────────────────────────────────────────────

    def _load_credentials(self):
        """Load saved credentials from disk if they exist."""
        if os.path.exists(TOKEN_FILE):
            try:
                with open(TOKEN_FILE, "rb") as f:
                    self.credentials = pickle.load(f)
                logger.info("Credentials loaded from token file.")
                self._refresh_if_needed()
                self._build_service()
            except Exception as e:
                logger.warning(f"Failed to load credentials: {e}")
                self.credentials = None

    def _save_credentials(self):
        """Persist credentials to disk."""
        with open(TOKEN_FILE, "wb") as f:
            pickle.dump(self.credentials, f)
        logger.info("Credentials saved.")

    def _refresh_if_needed(self):
        """Refresh expired credentials."""
        if self.credentials and self.credentials.expired and self.credentials.refresh_token:
            try:
                self.credentials.refresh(Request())
                self._save_credentials()
                logger.info("Credentials refreshed.")
            except Exception as e:
                logger.error(f"Failed to refresh credentials: {e}")
                self.credentials = None

    def _build_service(self):
        """Build the YouTube API service object."""
        if self.credentials and self.credentials.valid:
            self.youtube = build("youtube", "v3", credentials=self.credentials)

    def is_authenticated(self) -> bool:
        """Return True if we have valid credentials."""
        if self.credentials is None:
            return False
        self._refresh_if_needed()
        return self.credentials is not None and self.credentials.valid

    # ── OAuth Flow ────────────────────────────────────────────────────────────

    def get_auth_url(self) -> str:
        """
        Create an OAuth flow and return the authorization URL.
        Stores the flow object for later code exchange.
        """
        if not os.path.exists(CLIENT_SECRETS_FILE):
            raise FileNotFoundError(
                f"'{CLIENT_SECRETS_FILE}' not found. "
                "Download it from Google Cloud Console → Credentials."
            )

        self._flow = Flow.from_client_secrets_file(
            CLIENT_SECRETS_FILE,
            scopes=YOUTUBE_SCOPES,
            redirect_uri="http://localhost",  # Standard localhost flow
        )

        auth_url, _ = self._flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
        )
        return auth_url

    def exchange_code(self, code: str) -> str:
        """
        Exchange the authorization code for credentials.
        Returns the YouTube channel name on success.
        """
        if not hasattr(self, "_flow") or self._flow is None:
            raise RuntimeError("No active auth flow. Call get_auth_url() first.")

        self._flow.fetch_token(code=code)
        self.credentials = self._flow.credentials
        self._save_credentials()
        self._build_service()
        self._flow = None

        return self.get_channel_name()

    def revoke_credentials(self):
        """Delete stored credentials."""
        self.credentials = None
        self.youtube = None
        self._channel_name = None
        if os.path.exists(TOKEN_FILE):
            os.remove(TOKEN_FILE)
        logger.info("Credentials revoked.")

    # ── Channel Info ──────────────────────────────────────────────────────────

    def get_channel_name(self) -> str:
        """Return the authenticated user's YouTube channel name."""
        if self._channel_name:
            return self._channel_name

        if not self.youtube:
            return "Unknown"

        try:
            response = self.youtube.channels().list(
                part="snippet", mine=True
            ).execute()
            items = response.get("items", [])
            if items:
                self._channel_name = items[0]["snippet"]["title"]
                return self._channel_name
        except Exception as e:
            logger.error(f"Failed to get channel name: {e}")

        return "Unknown Channel"

    # ── Video Upload ──────────────────────────────────────────────────────────

    def upload_video(
        self,
        video_path: str,
        title: str,
        description: str = "",
        privacy_status: str = "public",
        category_id: str = "22",  # 22 = People & Blogs
    ) -> str:
        """
        Upload a video to YouTube.

        Args:
            video_path: Local path to the video file.
            title: Video title (max 100 chars).
            description: Video description.
            privacy_status: 'public', 'private', or 'unlisted'.
            category_id: YouTube category ID.

        Returns:
            The YouTube video ID of the uploaded video.

        Raises:
            RuntimeError: If not authenticated.
            HttpError: If the YouTube API returns an error.
        """
        if not self.is_authenticated():
            raise RuntimeError("Not authenticated. Use /login first.")

        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Video file not found: {video_path}")

        body = {
            "snippet": {
                "title": title,
                "description": description,
                "categoryId": category_id,
            },
            "status": {
                "privacyStatus": privacy_status,
                "selfDeclaredMadeForKids": False,
            },
        }

        media = MediaFileUpload(
            video_path,
            mimetype="video/*",
            resumable=True,
            chunksize=5 * 1024 * 1024,  # 5 MB chunks
        )

        logger.info(f"Starting upload: '{title}' ({video_path})")

        request = self.youtube.videos().insert(
            part=",".join(body.keys()),
            body=body,
            media_body=media,
        )

        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                progress = int(status.progress() * 100)
                logger.info(f"Upload progress: {progress}%")

        video_id = response["id"]
        logger.info(f"Upload complete. Video ID: {video_id}")
        return video_id
