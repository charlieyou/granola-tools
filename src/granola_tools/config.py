"""Configuration management for granola-tools."""
import json
import os
import sys
from pathlib import Path
from datetime import datetime

# Default paths
DEFAULT_GRANOLA_HOME = Path.home() / ".granola"
GRANOLA_APP_TOKENS = Path.home() / "Library" / "Application Support" / "Granola" / "supabase.json"


def get_global_config_path() -> Path:
    """Get path to global config that stores GRANOLA_HOME location."""
    return Path.home() / ".config" / "granola" / "config.json"


def load_global_config() -> dict:
    """Load global config (just stores path to GRANOLA_HOME)."""
    path = get_global_config_path()
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    return {}


def save_global_config(config: dict):
    """Save global config."""
    path = get_global_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2))


def get_granola_home() -> Path:
    """Get GRANOLA_HOME path from config or env."""
    # Env override
    if os.getenv("GRANOLA_HOME"):
        return Path(os.getenv("GRANOLA_HOME"))
    
    # Check global config
    global_config = load_global_config()
    if global_config.get("granola_home"):
        return Path(global_config["granola_home"])
    
    return DEFAULT_GRANOLA_HOME


def get_config_path() -> Path:
    """Get path to main config file."""
    return get_granola_home() / "config.json"


def load_config() -> dict:
    """Load config from GRANOLA_HOME/config.json."""
    path = get_config_path()
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    return {}


def save_config(config: dict):
    """Save config to GRANOLA_HOME/config.json."""
    path = get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    config["updated_at"] = datetime.now().isoformat()
    path.write_text(json.dumps(config, indent=2))


def is_configured() -> bool:
    """Check if granola-tools is configured."""
    config = load_config()
    return bool(config.get("refresh_token") and config.get("client_id"))


def extract_tokens_from_app() -> dict | None:
    """Extract tokens from Granola app's storage."""
    if not GRANOLA_APP_TOKENS.exists():
        return None
    
    try:
        data = json.loads(GRANOLA_APP_TOKENS.read_text())
        workos_tokens = json.loads(data.get("workos_tokens", "{}"))
        
        refresh_token = workos_tokens.get("refresh_token")
        access_token = workos_tokens.get("access_token")
        
        if not refresh_token or not access_token:
            return None
        
        # Extract client_id from JWT payload
        import base64
        payload_b64 = access_token.split(".")[1]
        # Fix padding
        payload_b64 = payload_b64.replace("-", "+").replace("_", "/")
        padding = 4 - len(payload_b64) % 4
        if padding != 4:
            payload_b64 += "=" * padding
        
        payload = json.loads(base64.b64decode(payload_b64))
        iss = payload.get("iss", "")
        # Extract client_id from issuer URL
        client_id = iss.split("/")[-1] if "client_" in iss else None
        
        if not client_id:
            return None
        
        return {
            "refresh_token": refresh_token,
            "client_id": client_id,
        }
    except Exception as e:
        return None


def setup_interactive() -> bool:
    """Interactive setup flow."""
    print("Welcome to granola-tools setup!\n")
    
    # Ask for GRANOLA_HOME
    default_home = str(DEFAULT_GRANOLA_HOME)
    home_input = input(f"Where should granola store data? [{default_home}]: ").strip()
    granola_home = Path(home_input) if home_input else DEFAULT_GRANOLA_HOME
    
    # Create directories
    granola_home.mkdir(parents=True, exist_ok=True)
    (granola_home / "transcripts").mkdir(exist_ok=True)
    (granola_home / "index").mkdir(exist_ok=True)
    
    # Save global config with path
    save_global_config({"granola_home": str(granola_home)})
    print(f"\n✓ Created {granola_home}")
    
    # Check if Granola app tokens exist
    if not GRANOLA_APP_TOKENS.exists():
        print(f"\n⚠ Granola app not found at: {GRANOLA_APP_TOKENS.parent}")
        print("Please install and sign into Granola first.")
        return False
    
    # Prompt user to login
    print("\nPlease make sure you're signed into the Granola app.")
    input("Press Enter when ready...")
    
    # Extract tokens
    tokens = extract_tokens_from_app()
    if not tokens:
        print("\n✗ Could not extract tokens from Granola app.")
        print("Make sure you're signed in and try again.")
        return False
    
    # Save config
    config = {
        "refresh_token": tokens["refresh_token"],
        "client_id": tokens["client_id"],
    }
    save_config(config)
    print(f"✓ Saved credentials to {get_config_path()}")
    
    # Perform first sync
    print("\nPerforming initial sync...")
    from .sync import run_sync
    try:
        run_sync(str(granola_home / "transcripts"))
        print("\n✓ Setup complete!")
        return True
    except Exception as e:
        print(f"\n✗ Sync failed: {e}")
        return False
