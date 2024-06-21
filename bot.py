import os

import discord
import dotenv


dotenv.load_dotenv()
TOKEN = os.getenv('TOKEN')
GUILD_ID = os.getenv('GUILD_ID')


bot = discord.Bot()
guild = discord.Object(id=GUILD_ID)


@bot.event
async def on_ready():
    print(f'--------------------------------------------------')
    
    print(f'Logged in as {bot.user} (ID: {bot.user.id})')

    print(f'Ready!')
    
    print(f'--------------------------------------------------')


@bot.slash_command(name="test", description="test cmd")
async def test(ctx: discord.ApplicationContext):
    await ctx.respond("YAYAYAYYAY")


bot.run(TOKEN)