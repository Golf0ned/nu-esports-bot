<div align="center">
<pre>
                ████████  █████ ████                         
               ░░███░░███░░███ ░███                          
                ░███ ░███ ░███ ░███                          
                ░███ ░███ ░███ ░███                          
                ████ █████░░████████          █████          
               ░░░░ ░░░░░  ░░░░░░░░          ░░███           
  ██████  █████ ████████   ██████  ████████  ███████   █████ 
 ███░░██████░░ ░░███░░███ ███░░███░░███░░███░░░███░   ███░░  
░███████░░█████ ░███ ░███░███ ░███ ░███ ░░░   ░███   ░░█████ 
░███░░░  ░░░░███░███ ░███░███ ░███ ░███       ░███ ███░░░░███
░░██████ ██████ ░███████ ░░██████  █████      ░░█████ ██████ 
 ░░░░░░ ░░░░░░  ░███░░░   ░░░░░░  ░░░░░        ░░░░░ ░░░░░░  
                ░███        █████               █████        
                █████      ░░███               ░░███         
               ░░░░░        ░███████   ██████  ███████       
                            ░███░░███ ███░░███░░░███░        
                            ░███ ░███░███ ░███  ░███         
                            ░███ ░███░███ ░███  ░███ ███     
                            ████████ ░░██████   ░░█████      
                           ░░░░░░░░   ░░░░░░     ░░░░░       

---------------------------------------------------------------------------
The official Discord bot for Northwestern Esports.

Also affectionately referred to as Miku.
</pre>
</div>

## About

TODO

## Getting Started

### Setting up Discord

Create a new app in the [Discord Developer Portal](https://discord.com/developers/applications).

There's a couple of additional things you need to do here to configure the bot:

- Installation: Make sure the scopes `application.commands` and `bot` are selected for guild install.
- Bot: Create a bot user, and copy the token.
- Bot: Make sure all privileged gateway intents are enabled.
- Emojis: If you want to utilize any custom emojis for features like special users or ping reacts, you'll need to upload them here.

### Setting up Config

The bot uses the files `config.yaml` and `secrets.yaml` to store configuration.

Copy the `config.yaml.example` and `secrets.yaml.example` files to `config.yaml` and `secrets.yaml`, respectively.

> [!CAUTION]
> The `config.yaml` and `secrets.yaml` files should stay gitignored. Pushing them to the repository can leak sensitive info such as discord ids, tokens, and passwords.

Values that need to be input are marked with comments. The only ones that are strictly required to run the bot are:

- `secrets.yaml -> discord.token`: The bot token you copied from the Discord Developer Portal.
- `secrets.yaml -> guild_id`: The guild id of the server you want to install the bot in. If you're not sure how to get this, follow [this guide](https://support-dev.discord.com/hc/en-us/articles/360028717192-Where-can-I-find-my-Application-Team-Server-ID).

### Running via Docker Compose (Recommended)

Make sure you have [Docker](https://docs.docker.com/desktop/) and [Docker Compose](https://docs.docker.com/compose/install/) installed.

From the root directory of the repository, run the following command:

```bash
docker-compose up
```

### Running Locally

Running the bot locally requires a few additional steps.

Make sure you have [Python 3.10+](https://www.python.org/downloads/) installed. From here, make and activate a virtual environment with your favorite tool ([venv](https://docs.python.org/3/library/venv.html), [conda](https://anaconda.org/anaconda/conda), etc.) and install the requirements:

```bash
pip install -r requirements.txt
```

You will also need a Postgres database to connect to. There are multiple ways to set this up:

- Install and run [locally](https://www.postgresql.org/download/)
- Use [Docker](https://hub.docker.com/_/postgres)
- Use a cloud provider of your choice ([AWS](https://aws.amazon.com/rds/postgresql/), [DigitalOcean](https://www.digitalocean.com/products/managed-databases-postgresql), [Railway](https://docs.railway.com/guides/postgresql), etc.)

## Contributing

TODO
