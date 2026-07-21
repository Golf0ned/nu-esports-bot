import discord

from utils import config, db, migrate


TOKEN = config.secrets["discord"]["token"]

bot = discord.Bot(intents=discord.Intents.all())


@bot.event
async def on_ready():
    await db.open_pool()
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")


# Bring the schema up to date before any cog loads, so nothing can query a table
# that doesn't exist yet. This has to run on the bot's own loop: asyncio.run() would
# close the loop it creates and leave the thread with no current loop, which breaks
# every cog that calls get_event_loop() to start a task at import time.
bot.loop.run_until_complete(migrate.run_migrations())

cogs_list = [
    "fun",
    "gameroom",
    "points",
    "teams",
    "valorant",
    "pcs",
    "game",
    "connections",
    "pugs",
    "matchmaking",
    "moderation",
    "presence",
    "profile",
    "leaderboard"
]

for cog in cogs_list:
    bot.load_extension(f"cogs.{cog}")
    print(f"Loaded cog: {cog}")

bot.run(TOKEN)
