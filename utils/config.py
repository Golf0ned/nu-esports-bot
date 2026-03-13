import yaml
from pathlib import Path


def load_config():
    """Load config from config.yaml file."""
    config_file = Path("config.yaml")
    if not config_file.exists():
        raise FileNotFoundError("config.yaml not found in local directory")
    with open(config_file, "r") as f:
        return yaml.safe_load(f)


def load_secrets():
    """Load secrets from secrets.yaml file."""
    secrets_file = Path("secrets.yaml")
    if not secrets_file.exists():
        raise FileNotFoundError("secrets.yaml not found in local directory")
    with open(secrets_file, "r") as f:
        return yaml.safe_load(f)


config = load_config()
secrets = load_secrets()
