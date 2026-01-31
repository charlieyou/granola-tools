import logging
import os
from datetime import datetime, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv, set_key

logger = logging.getLogger(__name__)

# Load .env from repo root or home
ENV_FILE = Path(__file__).parent.parent.parent / ".env"
if not ENV_FILE.exists():
    ENV_FILE = Path.home() / ".config" / "granola" / ".env"

load_dotenv(ENV_FILE)


class TokenManager:
    def __init__(self):
        self.refresh_token = os.getenv("GRANOLA_REFRESH_TOKEN")
        self.client_id = os.getenv("GRANOLA_CLIENT_ID")
        self.access_token = os.getenv("GRANOLA_ACCESS_TOKEN")
        expiry_str = os.getenv("GRANOLA_TOKEN_EXPIRY")
        self.token_expiry = datetime.fromisoformat(expiry_str) if expiry_str else None

    def _save_env(self):
        """Save tokens back to .env file."""
        try:
            if not ENV_FILE.parent.exists():
                ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
            
            set_key(str(ENV_FILE), "GRANOLA_REFRESH_TOKEN", self.refresh_token or "")
            set_key(str(ENV_FILE), "GRANOLA_ACCESS_TOKEN", self.access_token or "")
            if self.token_expiry:
                set_key(str(ENV_FILE), "GRANOLA_TOKEN_EXPIRY", self.token_expiry.isoformat())
            logger.debug(f"Tokens saved to {ENV_FILE}")
        except Exception as e:
            logger.error(f"Error saving tokens: {e}")

    def is_token_expired(self):
        if not self.access_token or not self.token_expiry:
            return True
        buffer = timedelta(minutes=5)
        return datetime.now() >= (self.token_expiry - buffer)

    def refresh_access_token(self):
        logger.info("Obtaining new access token from refresh token...")

        if not self.refresh_token:
            logger.error("No GRANOLA_REFRESH_TOKEN in environment")
            return False

        if not self.client_id:
            logger.error("No GRANOLA_CLIENT_ID in environment")
            return False

        url = "https://api.workos.com/user_management/authenticate"
        data = {
            "client_id": self.client_id,
            "grant_type": "refresh_token",
            "refresh_token": self.refresh_token
        }

        try:
            response = requests.post(url, json=data)
            response.raise_for_status()
            result = response.json()

            self.access_token = result.get("access_token")
            
            new_refresh_token = result.get("refresh_token")
            if new_refresh_token:
                self.refresh_token = new_refresh_token
                logger.info("Refresh token was rotated")

            expires_in = result.get("expires_in", 3600)
            self.token_expiry = datetime.now() + timedelta(seconds=expires_in)

            self._save_env()
            logger.info(f"Successfully obtained access token (expires in {expires_in}s)")
            return True

        except requests.exceptions.RequestException as e:
            logger.error(f"Error obtaining access token: {e}")
            if hasattr(e, "response") and e.response is not None:
                logger.debug(f"Response: {e.response.status_code} {e.response.text}")
            return False

    def get_valid_token(self):
        # Always refresh to keep session alive (refresh tokens may expire from inactivity)
        if not self.refresh_access_token():
            logger.error("Failed to obtain access token")
            return None
        return self.access_token
