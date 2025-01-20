import random

import discord
from discord.ext import commands


class Valorant(commands.Cog):

    AGENTS = [
        'Brimstone',
        'Viper',
        'Omen',
        'Cypher',
        'Sova',
        'Sage',
        'Phoenix',
        'Jett',
        'Raze',
        'Breach',
        'Reyna',
        'Killjoy',
        'Skye',
        'Yoru',
        'Astra',
        'KAY-O',
        'Chamber',
        'Neon',
        'Fade',
        'Harbor',
        'Gekko',
        'Deadlock',
        'Iso',
        'Clove',
        'Vyse',
        'Tejo',
    ]

    AGENTS_GUARANTEED_SMOKE = [0, 2, 14, 19, 23] # say no to solo viper

    MAPS = [
        'Bind',
        'Haven',
        'Split',
        'Ascent',
        'Icebox',
        'Breeze',
        'Fracture',
        'Pearl',
        'Lotus',
        'Sunset',
        'Abyss',
    ]

    MAPS_IN_ROTATION = [0, 1, 2, 6, 7, 8, 10]

    def __init__(self, bot):
        self.bot = bot

    def random_map(self):
        # TODO: Implement map flags (in rotation, tdm, etc)
        return random.choice(self.MAPS)

    def random_team(self):
        # TODO: Implement team flags (guarantee smokes, role balanced, etc)
        return random.sample(self.AGENTS, 5)

    valorant = discord.SlashCommandGroup('valorant', 'help me')

    @valorant.command(description='Generates a randomized Valorant lobby', guild_ids=[458779555147022366])
    async def random_lobby(self, ctx):
        map = self.random_map()
        attackers = self.random_team()
        defenders = self.random_team()

        embed = discord.Embed(
            title='Valorant Randomized Lobby',
            color=discord.Color.from_rgb(78, 42, 132),
        )

        embed.add_field(name='Map', value=map)
        embed.add_field(name='Attackers', value='\n'.join(attackers), inline=True)
        embed.add_field(name='Defenders', value='\n'.join(defenders), inline=True)

        await ctx.respond('', embed=embed)

def setup(bot):
    bot.add_cog(Valorant(bot))

