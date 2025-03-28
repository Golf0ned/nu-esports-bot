import random

import discord
from discord.ext import commands

from utils import config


GUILD_ID = config.secrets["discord"]["guild_id"]
SPECIAL_USERS = config.secrets["discord"]["special_users"]


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
        if random.randint(1, 100) <= 15 and message.author.id in SPECIAL_USERS:
            emoji_set = random.choice(SPECIAL_USERS[message.author.id])
            if isinstance(emoji_set, list):
                # List of reactions
                for emoji in emoji_set:
                    await message.add_reaction(emoji)
            else:
                # Single reaction
                await message.add_reaction(emoji_set)



def setup(bot):
    bot.add_cog(Fun(bot))

