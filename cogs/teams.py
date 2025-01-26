import discord
from discord.ext import commands

from config import Config


GUILD_ID = Config.secrets['discord']['guild_id']


class Teams(commands.Cog):

    def __init__(self, bot):
        self.bot = bot


def setup(bot):
    bot.add_cog(Teams(bot))
