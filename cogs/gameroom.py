import datetime
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

    @gameroom.command(name='hours', description='Lists current game room hours', guild_ids=[GUILD_ID])
    async def hours(self, ctx):
        # Monday to Sunday
        default_hours = [
            '2:30PM - 11:00PM',
            '2:30PM - 11:00PM',
            '2:30PM - 11:00PM',
            '2:30PM - 11:00PM',
            '12:30PM - 11:00PM',
            '12:30PM - 11:00PM',
            '2:30PM - 11:00PM',
        ]
        
        # List of days the game room is closed:
        # (yes, we're adding by hand)
        # - MLK Jr Day
        days_closed = [
            datetime.date(2025, 1, 20)
        ]

        today = datetime.date.today()
        start = today - datetime.timedelta(days=today.weekday())
        end = start + datetime.timedelta(days=6)
        week = [start + datetime.timedelta(days=i) for i in range(7)]

        embed = discord.Embed(
            title='Game Room Hours',
            color=discord.Color.from_rgb(78, 42, 132),
        )

        embed.add_field(name=f'Week of {start.strftime("%-m/%-d")} - {end.strftime("%-m/%-d")}', value='')

        for i, day in enumerate(week):
            value = default_hours[i] if day not in days_closed else 'Closed'
            embed.add_field(name=day.strftime('%A'), value=value, inline=False)

        embed.set_image(url='https://www.northwestern.edu/norris/arts-recreation/game-room/nexus_general_awareness-01.png')

        await ctx.respond('', embed=embed)


def setup(bot):
    bot.add_cog(Gameroom(bot))

