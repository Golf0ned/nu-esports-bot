from discord.ext import commands

from utils import config


GUILD_ID = config.secrets["discord"]["guild_id"]


class Teams(commands.Cog):
    def __init__(self, bot):
        self.bot = bot


def setup(bot):
    bot.add_cog(Teams(bot))
