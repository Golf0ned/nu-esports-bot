import datetime

import discord
from discord.ext import commands

from utils import config


GUILD_ID = config.secrets["discord"]["guild_id"]


class Gameroom(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

    gameroom = discord.SlashCommandGroup("gameroom", "Game Room and Nexus Gaming Lounge commands")

    @gameroom.command(name="hours", description="Lists current game room hours", guild_ids=[GUILD_ID])
    async def hours(self, ctx):
        default_hours = config.config["gameroom"]["default_hours"]
        adjusted_hours = config.config["gameroom"]["adjusted_hours"]

        today = datetime.date.today()
        start = today - datetime.timedelta(days=today.weekday())
        end = start + datetime.timedelta(days=6)
        week = [start + datetime.timedelta(days=i) for i in range(7)]

        embed = discord.Embed(
            title="Game Room Hours",
            color=discord.Color.from_rgb(78, 42, 132),
        )

        embed.add_field(name=f"Week of {start.strftime('%-m/%-d')} - {end.strftime('%-m/%-d')}", value="")

        for i, day in enumerate(week):

            value = adjusted_hours.get(day, default_hours[i]) # adjusted hours if available, otherwise default hours
            embed.add_field(name=day.strftime("%A"), value=value, inline=False)

        embed.set_image(url="https://www.northwestern.edu/norris/arts-recreation/game-room/nexus_general_awareness-01.png")

        await ctx.respond("", embed=embed)

    @gameroom.command(name="games", description="Lists games available on game room consoles", guild_ids=[GUILD_ID])
    async def games(self, ctx):
        games = config.config["gameroom"]["games"]

        embed = discord.Embed(
            title="Game Room Games",
            color=discord.Color.from_rgb(78, 42, 132),
        )

        embed.add_field(name="PS4", value="\n".join(games["ps4"]), inline=True)
        embed.add_field(name="PS5", value="\n".join(games["ps5"]), inline=True)
        embed.add_field(name="Nintendo 64", value="\n".join(games["n64"]), inline=True)
        embed.add_field(name="Nintendo Switch", value="\n".join(games["switch"]), inline=True)
        embed.add_field(name="Wii U", value="\n".join(games["wii_u"]), inline=True)
        embed.add_field(name="Xbox One", value="\n".join(games["xbox"]), inline=True)

        await ctx.respond("", embed=embed)


def setup(bot):
    bot.add_cog(Gameroom(bot))

