import os

import discord
import dotenv


dotenv.load_dotenv()
TOKEN = os.getenv('TOKEN')
GUILD_ID = os.getenv('GUILD_ID')

bot = discord.Bot()

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user} (ID: {bot.user.id})')


cogs_list = [
    'gameroom',
    'valorant',
    'banana',
]

for cog in cogs_list:
    bot.load_extension(f'cogs.{cog}')
    print(f'Loaded cog: {cog}')

bot.run(TOKEN)

