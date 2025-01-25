import os
import random

import discord
from discord.ext import commands
import dotenv


dotenv.load_dotenv()
GUILD_ID = os.getenv('GUILD_ID')


class Fun(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author == self.bot.user:
            return

        if self.bot.user.mentioned_in(message):
            # You can't test this locally, since the emoji IDs are hard-coded unfortunately.
            # You can, however, replace them temporarily to verify correctness!
            chess_reacts = [
                '<:blunder:1332816325952798853>',
                '<:mistake:1332816343078273037>',
                '<:inaccuracy:1332816354306424922>',
                '<:excellent:1332816405481127998>',
                '<:best:1332816418881671278>',
                '<:brilliant:1332816435122274324>',
            ]
            await message.add_reaction(random.choice(chess_reacts))


def setup(bot):
    bot.add_cog(Fun(bot))

