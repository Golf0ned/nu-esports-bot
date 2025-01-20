import os

import discord
from discord.ext import commands
import dotenv


dotenv.load_dotenv()
GUILD_ID = os.getenv('GUILD_ID')

class Gameroom(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

    gameroom = discord.SlashCommandGroup('gameroom', 'Game Room and Nexus Gaming Lounge commands')

    @gameroom.command(description='Lists current game room hours', guild_ids=[GUILD_ID])
    async def hours(self, ctx):
        hours = {
            'Sunday': '2:30 PM - 11:00 PM',
            'Monday': '2:30 PM - 11:00 PM',
            'Tuesday': '2:30 PM - 11:00 PM',
            'Wednesday': '2:30 PM - 11:00 PM',
            'Thursday': '2:30 PM - 11:00 PM',
            'Friday': '12:30 PM - 11:00 PM',
            'Saturday': '12:30 PM - 11:00 PM',
        }

        embed = discord.Embed(
            title='Game Room Hours',
            color=discord.Color.from_rgb(78, 42, 132),
        )

        for day, hours in hours.items():
            embed.add_field(name=day, value=hours, inline=False)

        await ctx.respond('', embed=embed)


def setup(bot):
    bot.add_cog(Gameroom(bot))
