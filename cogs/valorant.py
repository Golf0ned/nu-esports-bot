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
       
    valorant = discord.SlashCommandGroup('valorant', 'Valorant-related utils')

    @valorant.command(name='stack', description='any stackas', guild_ids=[GUILD_ID])
    async def stack(self, ctx):
        embed = discord.Embed(
            title='Valorant Stack',
            color=discord.Color.from_rgb(78, 42, 132),
        )
        embed.add_field(name=':green_square::white_medium_square::white_medium_square::white_medium_square::white_medium_square:', value=ctx.author.display_name)
        await ctx.respond(embed=embed, view=ValorantStackView(embed))

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

    def __init__(self, embed):
        super().__init__(timeout=1200)
        self.embed = embed
        self.joined = {}
    
    def update_embed(self):
        field_value = '\n'.join(self.joined.values()) if self.joined else 'empty :/'

        # Add a green square per person joined, yellow square per person over 5, and white square per empty slot
        num_joined = len(self.joined)
        name = ''.join([':green_square:' if i < 5 else ':yellow_square:' for i in range(num_joined)])
        if num_joined < 5:
            name += ''.join([':white_medium_square:' for _ in range(5 - num_joined)])

        self.embed.remove_field(0)
        self.embed.add_field(name=name, value=field_value)

    async def on_timeout(self):
        self.disable_all_items()
        await self.message.edit(view=self)

    @discord.ui.button(label='Join', style=discord.ButtonStyle.green)
    async def join_callback(self, button, interaction):
        self.joined[interaction.user.id] = interaction.user.display_name
        self.update_embed()
        await interaction.response.edit_message(embed=self.embed)

    @discord.ui.button(label='Leave', style=discord.ButtonStyle.red)
    async def leave_callback(self, button, interaction):
        if interaction.user.id in self.joined:
            self.joined.pop(interaction.user.id)
        self.update_embed()
        await interaction.response.edit_message(embed=self.embed)

def random_map(flags):
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

def random_team(flags):
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

