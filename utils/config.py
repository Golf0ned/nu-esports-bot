import yaml


__config_file = "config.yaml"
__secrets_file = "secrets.yaml"

with open(__config_file, "r") as f:
    config = yaml.safe_load(f)

with open(__secrets_file, "r") as f:
    secrets = yaml.safe_load(f)
