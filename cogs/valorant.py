import copy
import random

import discord
from discord.ext import commands

from config import Config


GUILD_ID = Config.secrets['discord']['guild_id']


class Valorant(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
       
    valorant = discord.SlashCommandGroup('valorant', 'Valorant-related utils')

    @valorant.command(name='stack', description='any stackas', guild_ids=[GUILD_ID])
    async def stack(
        self,
        ctx,
        name: discord.Option(
            str,
            name='name',
            description='Name of the stack',
            default='',
        ),
        size: discord.Option(
            int,
            name='size',
            description='Number of stackas (default 5)',
            choices=[5, 10],
            default=5,
        )
    ):
        if name == '':
            name = f'{ctx.author.display_name}\'s stack'

        embed = discord.Embed(
            title=name,
            color=discord.Color.from_rgb(78, 42, 132),
        )
        embed.add_field(name=''.join([':white_medium_square:' for _ in range(size)]), value='empty :/')
        await ctx.respond(embed=embed, view=ValorantStackView(embed, size))

    @valorant.command(name='random-lobby', description='Generates a randomized Valorant lobby', guild_ids=[GUILD_ID])
    async def random_lobby(
        self,
        ctx,
        map_flags: discord.Option(
            str,
            name='maps',
            description='Map pool used for randomization (default all)',
            choices=['active', 'newest', 'all'],
            default='all',
        ),
        team_flags: discord.Option(
            str,
            name='teams',
            description='Agent selection used for randomization (default role-balanced)',
            choices=['role-balanced', 'random'],
            default='role-balanced',
        ),
    ):
        map = random_map(map_flags)
        attackers = random_team(team_flags)
        defenders = random_team(team_flags)

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


class ValorantStackView(discord.ui.View):

    def __init__(self, embed, size):
        super().__init__(timeout=1200)
        self.embed = embed
        self.joined = {}
        self.pinged = False
        self.stack_size = size

    def update_embed(self):
        # Title:
        # - Green square: Person joined under limit
        # - Yellow square: Person joined over stack size
        # - White square: Empty slot
        num_joined = len(self.joined)
        name = ''.join([':green_square:' if i < self.stack_size else ':yellow_square:' for i in range(num_joined)])
        if num_joined < self.stack_size:
            name += ''.join([':white_medium_square:' for _ in range(self.stack_size - num_joined)])

        # Value: display name of every user
        value = '\n'.join(user.mention for user in self.joined.values()) if self.joined else 'empty :/'

        self.embed.remove_field(0)
        self.embed.add_field(name=name, value=value)

    async def on_timeout(self):
        self.disable_all_items()
        await self.message.edit(view=self)

    @discord.ui.button(label='Join', style=discord.ButtonStyle.green)
    async def join_callback(self, button, interaction):
        self.joined[interaction.user.id] = interaction.user
        self.update_embed()
        await interaction.response.edit_message(embed=self.embed)

        if not self.pinged and len(self.joined) >= self.stack_size:
            self.pinged = True
            await interaction.followup.send(' '.join(user.mention for user in self.joined.values()))

    @discord.ui.button(label='Leave', style=discord.ButtonStyle.red)
    async def leave_callback(self, button, interaction):
        if interaction.user.id in self.joined:
            self.joined.pop(interaction.user.id)
        self.update_embed()
        await interaction.response.edit_message(embed=self.embed)

    @discord.ui.button(label='Bump!', style=discord.ButtonStyle.grey)
    async def refresh_callback(self, button, interaction):
        # TODO: fix issue with race condition spamming console and nuking the stack altogether
        await self.message.delete()
        await interaction.response.send_message(embed=self.embed, view=self)


def random_map(flags):
    maps = Config.config['valorant']['maps']
    maps_active = Config.config['valorant']['maps_active']

    match flags:
        case 'active':
            return maps[random.choice(maps_active)]
        case 'newest':
            return maps[-1]
        case _:
            return random.choice(maps)

def random_team(flags):
    agents = Config.config['valorant']['agents']
    agents_roles = copy.deepcopy(Config.config['valorant']['agents_roles']) # copy because pop

    match flags:
        case 'role-balanced':
            # pop random agent from each role
            team = [agents[role.pop(random.randrange(len(role)))] for role in agents_roles.values()]

            # fill in remaining agent
            remaining_agents = [i for role in agents_roles.values() for i in role]
            team.append(agents[random.choice(remaining_agents)])

            # shuffle and return
            random.shuffle(team)
            return team
        case _:
            return random.sample(agents, 5)

