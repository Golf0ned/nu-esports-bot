import yaml


config_file = 'config.yaml'
secrets_file = 'secrets.yaml'


class Config:

    with open(config_file, 'r') as f:
        config = yaml.safe_load(f)

    with open(secrets_file, 'r') as f:
        secrets = yaml.safe_load(f)
