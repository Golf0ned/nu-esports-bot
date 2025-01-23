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
        
        # List of days the game room is closed
        # (yes, we're adding by hand)
        days_closed = {
            datetime.date(2025, 1, 20): 'MLK Day',
        }

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
            value = default_hours[i] if day not in days_closed else f'Closed ({days_closed[day]})'
            embed.add_field(name=day.strftime('%A'), value=value, inline=False)

        embed.set_image(url='https://www.northwestern.edu/norris/arts-recreation/game-room/nexus_general_awareness-01.png')

        await ctx.respond('', embed=embed)

    @gameroom.command(name='games', description='Lists games available on game room consoles', guild_ids=[GUILD_ID])
    async def games(self, ctx):
        ps4 = ['Call of Duty: Black Ops 4', 'FIFA 23', 'NBA 2K22', 'Street Fighter V', 'Guilty Gear Strive', 'Guilty Gear Xrd Rev 2', 'The King of Fighters XV', 'Tekken 7', 'Madden NFL 23', 'Madden NFL 24', 'Under Night In-Birth']
        ps5 = ['NBA 2K25', 'NBA 2K22', 'Madden NFL 25', 'FC25', 'Garfield Lasagna Party', 'Hogwarts Legacy']
        n64 = ['F-Zero X', 'Goldeneye 007', 'Mario Kart 64', 'Pokemon Stadium', 'Super Smash Bros.']
        switch = ['Super Smash Bros. Ultimate', 'Mario Party Superstars', 'New Super Mario Bros Deluxe', 'Nintendo Switch Sports', 'Mario Kart 8 Deluxe', 'Snipperclips Plus', 'Mario Strikers: Battle League']
        wii_u = ['Splatoon', 'Super Smash Bros. Brawl', 'Super Smash Bros. Wii U', 'Mario Kart Wii', 'Lego Marvel Super Heroes']
        xbox = ['Battlefield 1', 'Mortal Kombat X', 'Halo 5', 'Madden 23', 'Call of Duty: Black Ops 3', 'Call of Duty: Modern Warfare II']

        embed = discord.Embed(
            title='Game Room Games',
            color=discord.Color.from_rgb(78, 42, 132),
        )

        embed.add_field(name='PS4', value='\n'.join(ps4), inline=True)
        embed.add_field(name='PS5', value='\n'.join(ps5), inline=True)
        embed.add_field(name='Nintendo 64', value='\n'.join(n64), inline=True)
        embed.add_field(name='Nintendo Switch', value='\n'.join(switch), inline=True)
        embed.add_field(name='Wii U', value='\n'.join(wii_u), inline=True)
        embed.add_field(name='Xbox One', value='\n'.join(xbox), inline=True)

        await ctx.respond('', embed=embed)


def setup(bot):
    bot.add_cog(Gameroom(bot))

