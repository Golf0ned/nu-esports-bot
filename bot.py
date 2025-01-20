import os

import discord
import dotenv


dotenv.load_dotenv()
TOKEN = os.getenv('TOKEN')
GUILD_ID = os.getenv('GUILD_ID')

bot = discord.Bot()

cogs_list = [
    'gameroom',
    'valorant',
]

@bot.event
async def on_ready():

    print(f'--------------------------------------------------')
    print(f'Logged in as {bot.user} (ID: {bot.user.id})')
    print(f'Ready!')
    print(f'--------------------------------------------------')

for cog in cogs_list:
    bot.load_extension(f'cogs.{cog}')
    print(f'Loaded cog: {cog}')

bot.run(TOKEN)
