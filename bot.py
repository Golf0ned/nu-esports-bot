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


"""
Example command, for Ben reference:

Creates a command named "test" that responds with "This is a test command" when called.

@bot.command(description="Test command")
async def test(ctx):
    await ctx.respond("This is a test command")

"""

@bot.slash_command(description="Test command", guild_ids=[GUILD_ID])
async def test_main(ctx):
    await ctx.respond("This is a test command")

for cog in cogs_list:
    bot.load_extension(f'cogs.{cog}')
    print(f'Loaded cog: {cog}')

bot.run(TOKEN)
