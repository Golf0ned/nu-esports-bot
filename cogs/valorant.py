import copy
import random

import discord
from discord.ext import commands

from utils import config


GUILD_ID = config.secrets["discord"]["guild_id"]


class Valorant(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    valorant = discord.SlashCommandGroup("valorant", "Valorant-related utils")

    @valorant.command(
        name="random-lobby",
        description="Generates a randomized Valorant lobby",
        guild_ids=[GUILD_ID],
    )
    async def random_lobby(
        self,
        ctx,
        map_flags: discord.Option(
            str,
            name="maps",
            description="Map pool used for randomization (default all)",
            choices=["active", "newest", "all"],
            default="all",
        ),
        team_flags: discord.Option(
            str,
            name="teams",
            description="Agent selection used for randomization (default role-balanced)",
            choices=["role-balanced", "random"],
            default="role-balanced",
        ),
    ):
        map = random_map(map_flags)
        attackers = random_team(team_flags)
        defenders = random_team(team_flags)

        embed = discord.Embed(
            title="Valorant Randomized Lobby",
            color=discord.Color.from_rgb(78, 42, 132),
        )

        embed.add_field(name=":map: Map", value=map, inline=False)
        embed.add_field(
            name=":red_square: Attackers", value="\n".join(attackers), inline=True
        )
        embed.add_field(
            name=":blue_square: Defenders", value="\n".join(defenders), inline=True
        )

        await ctx.respond("", embed=embed)


def setup(bot):
    bot.add_cog(Valorant(bot))


def random_map(flags):
    maps = config.config["valorant"]["maps"]
    maps_active = config.config["valorant"]["maps_active"]

    match flags:
        case "active":
            return maps[random.choice(maps_active)]
        case "newest":
            return maps[-1]
        case _:
            return random.choice(maps)


def random_team(flags):
    agents = config.config["valorant"]["agents"]
    agents_roles = copy.deepcopy(
        config.config["valorant"]["agents_roles"]
    )  # copy because pop

    match flags:
        case "role-balanced":
            # pop random agent from each role
            team = [
                agents[role.pop(random.randrange(len(role)))]
                for role in agents_roles.values()
            ]

            # fill in remaining agent
            remaining_agents = [i for role in agents_roles.values() for i in role]
            team.append(agents[random.choice(remaining_agents)])

            # shuffle and return
            random.shuffle(team)
            return team

        case _:
            return random.sample(agents, 5)
