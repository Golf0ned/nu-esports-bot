import yaml
import os
from pathlib import Path


def is_railway():
    """Check if running on Railway."""
    return os.getenv("RAILWAY_ENVIRONMENT") is not None


def load_config():
    """Load config from environment variable (Railway) or file (local)."""
    if is_railway():
        # On Railway: load from environment variable
        config_yaml = os.getenv("CONFIG_YAML")
        if not config_yaml:
            raise ValueError("CONFIG_YAML environment variable not set on Railway")
        return yaml.safe_load(config_yaml)
    else:
        # Local development: load from file
        config_file = Path("config.yaml")
        if not config_file.exists():
            raise FileNotFoundError("config.yaml not found in local directory")
        with open(config_file, "r") as f:
            return yaml.safe_load(f)


def load_secrets():
    """Load secrets from environment variable (Railway) or file (local)."""
    if is_railway():
        # On Railway: load from environment variable
        secrets_yaml = os.getenv("SECRETS_YAML")
        if not secrets_yaml:
            raise ValueError("SECRETS_YAML environment variable not set on Railway")
        return yaml.safe_load(secrets_yaml)
    else:
        # Local development: load from file
        secrets_file = Path("secrets.yaml")
        if not secrets_file.exists():
            raise FileNotFoundError("secrets.yaml not found in local directory")
        with open(secrets_file, "r") as f:
            return yaml.safe_load(f)


config = load_config()
secrets = load_secrets()
