import discord
from discord.ext import commands, tasks

from utils import config, db


GUILD_ID = config.secrets["discord"]["guild_id"]


class Points(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        self.messaged = {}
        self.update_points.start()

    @commands.Cog.listener()
    async def on_message(self, message):
        user = message.author
        if user == self.bot.user or user.bot:
            return

        self.messaged[user.id] = self.messaged.get(user.id, 0) + 1

    @tasks.loop(seconds=60)
    async def update_points(self):
        if not self.messaged:
            return

        sql = """INSERT INTO users (discordid, points)
            VALUES (%s, %s)
            ON CONFLICT (discordid)
            DO UPDATE SET points = users.points + EXCLUDED.points;
        """
        data = [(user_id, message_count) for user_id, message_count in self.messaged.items()]
        async with db.cursor() as cur:
            await cur.executemany(sql, data)

        self.messaged.clear()


def setup(bot):
    bot.add_cog(Points(bot))

