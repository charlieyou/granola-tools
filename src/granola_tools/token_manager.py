"""Token management for Granola API authentication."""
import logging
from datetime import datetime, timedelta

import requests

from .config import load_config, save_config

logger = logging.getLogger(__name__)


class TokenManager:
    def __init__(self):
        config = load_config()
        self.refresh_token = config.get("refresh_token")
        self.client_id = config.get("client_id")
        self.access_token = config.get("access_token")
        expiry_str = config.get("token_expiry")
        self.token_expiry = datetime.fromisoformat(expiry_str) if expiry_str else None

    def _save_tokens(self):
        """Save tokens back to config file."""
        try:
            config = load_config()
            config["refresh_token"] = self.refresh_token or ""
            config["access_token"] = self.access_token or ""
            if self.token_expiry:
                config["token_expiry"] = self.token_expiry.isoformat()
            save_config(config)
            logger.debug("Tokens saved to config")
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
            logger.error("No refresh_token in config. Run 'granola init' to set up.")
            return False

        if not self.client_id:
            logger.error("No client_id in config. Run 'granola init' to set up.")
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

            self._save_tokens()
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
