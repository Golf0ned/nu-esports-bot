import discord

from utils import config, db


TOKEN = config.secrets["discord"]["token"]

bot = discord.Bot(intents=discord.Intents.all())

@bot.event
async def on_ready():
    await db.open_pool()
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")

cogs_list = [
    "fun",
    "gameroom",
    "points",
    "teams",
    "valorant",
]

for cog in cogs_list:
    bot.load_extension(f"cogs.{cog}")
    print(f"Loaded cog: {cog}")

bot.run(TOKEN)

