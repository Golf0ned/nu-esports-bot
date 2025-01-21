import os
import random

import discord
from discord.ext import commands
import dotenv


dotenv.load_dotenv()
GUILD_ID = os.getenv('GUILD_ID')


class Valorant(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

    def random_map(self, flags):
        maps = [
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

        maps_active = [0, 1, 2, 6, 7, 8, 10]

        match flags:
            case 'active':
                return maps[random.choice(maps_active)]
            case 'newest':
                return maps[-1]
            case _:
                return random.choice(maps)

    def random_team(self, flags):
        # Note that Viper's grouped with the sentinels.
        # From an agent pick perspective, it leads to better random teams.
        # (we do not endorse solo viper!)
        controllers = ['Brimstone', 'Omen', 'Astra', 'Harbor', 'Clove']
        duelists = ['Phoenix', 'Jett', 'Raze', 'Reyna', 'Yoru', 'Neon', 'Iso']
        initiators = ['Sova', 'Breach', 'Skye', 'KAY/O', 'Fade', 'Gekko', 'Tejo']
        sentinels = ['Viper', 'Cypher', 'Sage', 'Killjoy', 'Chamber', 'Deadlock', 'Vyse']

        match flags:
            case 'role-balanced':
                team = [
                    controllers.pop(random.randrange(len(controllers))),
                    duelists.pop(random.randrange(len(duelists))),
                    initiators.pop(random.randrange(len(initiators))),
                    sentinels.pop(random.randrange(len(sentinels))),
                ]
                all = controllers + duelists + initiators + sentinels
                team.append(random.choice(all))
                random.shuffle(team)
                return team
            case _:
                all = controllers + duelists + initiators + sentinels
                return random.sample(all, 5)
        
    valorant = discord.SlashCommandGroup('valorant', 'Valorant-related utils')

    @valorant.command(name='random-lobby', description='Generates a randomized Valorant lobby', guild_ids=[GUILD_ID])
    async def random_lobby(
            self,
            ctx,
            map_flags: discord.Option(
                str,
                name='maps',
                choices=['active', 'newest', 'all'],
                default='all',
            ),
            team_flags: discord.Option(str,
                                       name='teams',
                                       choices=['role-balanced', 'random'],
                                       default='role-balanced',
            ),
    ):
        map = self.random_map(map_flags)
        attackers = self.random_team(team_flags)
        defenders = self.random_team(team_flags)

        embed = discord.Embed(
            title='Valorant Randomized Lobby',
            color=discord.Color.from_rgb(78, 42, 132),
        )

        embed.add_field(name=':map: Map', value=map, inline=False)
        embed.add_field(name=':red_square: Attackers', value='\n'.join(attackers), inline=True)
        embed.add_field(name=':blue_square: Defenders', value='\n'.join(defenders), inline=True)

        await ctx.respond('', embed=embed)


def setup(bot):
    bot.add_cog(Valorant(bot))

