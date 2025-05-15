import discord
from discord.ext import commands
import groupme

from utils import config

GUILD_ID = config.secrets["discord"]["guild_id"]
ANNOUNCEMENTS_CHANNEL_ID = config.config["groupme"]["announcements_channel_id"]
GROUPME_ACCESS_TOKEN = config.secrets["groupme"]["access_token"]
GROUPME_BOT_ID = config.secrets["groupme"]["bot_id"]
STUDENT_ROLE_ID = config.config["groupme"]["student_role_id"]


class GroupMe(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.groupme_client = groupme.bot.get_bot(GROUPME_ACCESS_TOKEN, GROUPME_BOT_ID)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        ids = [role.id for role in message.role_mentions]
        if message.channel.id == ANNOUNCEMENTS_CHANNEL_ID and (
            message.mention_everyone
            or STUDENT_ROLE_ID in ids
        ):
            self.groupme_client.send_message(
                f"From {message.author.name}: {message.content}"
            )
