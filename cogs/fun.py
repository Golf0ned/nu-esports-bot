import os

import discord
from discord.ext import commands
import dotenv


dotenv.load_dotenv()
GUILD_ID = os.getenv('GUILD_ID')


class Fun(commands.Cog):

    def __init__(self, bot):
        self.bot = bot


def setup(bot):
    bot.add_cog(Fun(bot))
