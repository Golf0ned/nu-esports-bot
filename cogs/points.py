import random

import discord
from discord.ext import commands, tasks

from utils import config, db


GUILD_ID = config.secrets["discord"]["guild_id"]


class Points(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        self.points_buffer = {}
        self.update_points.start()

    points = discord.SlashCommandGroup("points", "points :)")

    @commands.Cog.listener()
    async def on_message(self, message):
        user = message.author
        if user == self.bot.user or user.bot:
            return

        self.points_buffer[user.id] = random.randint(7, 25)

    @points.command(name="balance", description="Get your points balance or another user's point balance", guild_ids=[GUILD_ID])
    async def balance(self, ctx, user: discord.Option(discord.User, default=None)):
        if user is None:
            user = ctx.author

        sql = "SELECT points FROM users WHERE discordid = %s"
        data = [user.id]
        async with db.cursor() as cur:
            await cur.execute(sql, data)
            result = await cur.fetchone()

        points = result[0] if result else 0
        embed = discord.Embed(
            title=f"{user.display_name}'s points",
            description=f"{points} points",
            color=discord.Color.from_rgb(78, 42, 132),
        )
        await ctx.respond(embed=embed)

    @tasks.loop(seconds=60)
    async def update_points(self):
        if not self.points_buffer:
            return

        sql = """INSERT INTO users (discordid, points)
            VALUES (%s, %s)
            ON CONFLICT (discordid)
            DO UPDATE SET points = users.points + EXCLUDED.points;
        """
        data = [(user_id, message_count) for user_id, message_count in self.points_buffer.items()]
        async with db.cursor() as cur:
            await cur.executemany(sql, data)

        self.points_buffer.clear()


def setup(bot):
    bot.add_cog(Points(bot))

