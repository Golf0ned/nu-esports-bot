import random

import discord
from discord.ext import commands

from config import Config


GUILD_ID = Config.secrets["discord"]["guild_id"]


class Fun(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author == self.bot.user:
            return

        # React with random chess emoji on ping
        if self.bot.user.mentioned_in(message):
            if message.mention_everyone:
                return
            chess_emojis = Config.config["fun"]["chess_emojis"]
            emoji, id = random.choice(list(chess_emojis.items()))
            await message.add_reaction(f"<:{emoji}:{id}>")

        # Affirm the glory of osu!
        if "i love osu" in message.content.lower():
            await message.reply("Osu 😻")

        # User-specific reactions
        special_users = Config.config["fun"]["special_users"]
        if random.randint(1, 100) <= 15 and message.author.id in special_users:
            emoji = random.choice(special_users[message.author.id])
            await message.add_reaction(emoji)


def setup(bot):
    bot.add_cog(Fun(bot))

