import discord

from config import Config


TOKEN = Config.secrets['discord']['token']

bot = discord.Bot(intents=discord.Intents.all())

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user} (ID: {bot.user.id})')

cogs_list = [
    'fun',
    'gameroom',
    'teams',
    'valorant',
]

for cog in cogs_list:
    bot.load_extension(f'cogs.{cog}')
    print(f'Loaded cog: {cog}')

bot.run(TOKEN)

