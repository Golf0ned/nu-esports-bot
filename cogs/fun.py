import random

import discord
from discord.ext import commands

from config import Config


GUILD_ID = Config.secrets['discord']['guild_id']


class Fun(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author == self.bot.user:
            return

        if self.bot.user.mentioned_in(message):
            chess_emojis = Config.config['fun']['chess_emojis']
            emoji, id = random.choice(list(chess_emojis.items()))
            await message.add_reaction(f'<:{emoji}:{id}>')


def setup(bot):
    bot.add_cog(Fun(bot))

