import asyncio
from typing import Dict, Tuple, List
import random

import discord
from discord.ext import commands

from utils import config

# from utils import db


GUILD_ID = config.secrets["discord"]["guild_id"]


class PUGSession:
    def __init__(
        self,
        lobby_channel: discord.VoiceChannel,
        blue_channel: discord.VoiceChannel,
        red_channel: discord.VoiceChannel,
        num_players: int,
    ):
        self.lobby_channel = lobby_channel
        self.blue_channel = blue_channel
        self.red_channel = red_channel
        self.num_players = num_players
        self.blue_team: List[discord.Member] = []
        self.red_team: List[discord.Member] = []
        self.active: bool = True
        self.player_session_stats: Dict[int, Tuple[int, int]] = {}


class PUGs(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot: commands.Bot = bot
        self.active_sessions: Dict[int, PUGSession] = {}

    pugs_group = discord.SlashCommandGroup(
        "pugs", "Lobby and voice channel tools for PUGs"
    )

    @pugs_group.command(
        name="start", description="Start a PUGs session", guild_ids=[GUILD_ID]
    )
    @discord.option(
        name="blue",
        description="Voice channel for blue team",
        channel_types=[discord.ChannelType.voice],
    )
    @discord.option(
        name="red",
        description="Voice channel for red team",
        channel_types=[discord.ChannelType.voice],
    )
    @discord.option(
        name="num_players",
        description="Maximum number of players (defaults to 10)",
        channel_types=[discord.ChannelType.voice],
        default=10,
    )
    async def start(
        self,
        ctx: discord.ApplicationContext,
        blue: discord.VoiceChannel,
        red: discord.VoiceChannel,
        num_players: int,
    ):
        """
        @brief Start a new lobby and add it to `active_sessions`.
        @param blue The blue team's voice channel.
        @param red The red team's voice channel.
        """
        await ctx.defer()

        # Check voice channel
        if ctx.user.voice:
            lobby_channel: discord.VoiceChannel = ctx.user.voice.channel
        else:
            await ctx.send_followup("You are not in a voice channel!", ephemeral=True)
            return

        # Create lobby based on user's current voice channel
        if (
            lobby_channel.id in self.active_sessions
            and self.active_sessions[lobby_channel.id].active
        ):
            await ctx.send_followup(
                "Lobby already active in this channel!", ephemeral=True
            )
        else:
            self.active_sessions[lobby_channel.id] = PUGSession(
                lobby_channel, blue, red, num_players
            )

        await ctx.send_followup(
            f"Lobby created in channel {lobby_channel.mention}!",
            view=LobbyCreatedView(self, self.active_sessions[lobby_channel.id]),
        )

    @pugs_group.command(
            name = "finish", description="Mark PUGs session as done", guild_ids=[GUILD_ID]
    )
    async def finish(
        self,
        ctx: discord.ApplicationContext
    ):
        """
        @brief End the PUGs lobby in this current channel.
        """
        await ctx.defer()

        # Check voice channel
        if ctx.user.voice:
            lobby_channel: discord.VoiceChannel = ctx.user.voice.channel
        else:
            await ctx.send_followup("You are not in a voice channel!", ephemeral=True)
            return
        
        if (
            lobby_channel.id in self.active_sessions
            and self.active_sessions[lobby_channel.id].active
        ):
            self.active_sessions[lobby_channel.id].active = False
        else:
            await ctx.send_followup(
                "No active lobby in this channel!", ephemeral=True
            )


    async def _generate_match_logic(self, session: PUGSession):
        players = session.lobby_channel.members

        # TODO: real team creation logic
        # First approach: people who have played the least
        # Second approach: balance by wins/losses in session
        # Third approach: DB-backed MMR system
        # Keep this method in this class in case we do global MMR system
        player_count = min(len(players), session.num_players)

        selected_players = random.sample(players, player_count)
        mid = len(selected_players) // 2
        session.blue_team = selected_players[:mid]
        session.red_team = selected_players[mid:]

    async def _process_match_results(self, session: PUGSession, winner: str):
        # Keep this method in this class in case we do global MMR system
        # In that case, TODO: coalesce results to DB
        if winner == "blue":
            winning_team, losing_team = session.blue_team, session.red_team
        else:
            winning_team, losing_team = session.red_team, session.blue_team

        for p in winning_team:
            wins, losses = session.player_session_stats.get(p.id, (0, 0))
            session.player_session_stats[p.id] = (wins + 1, losses)

        for p in losing_team:
            wins, losses = session.player_session_stats.get(p.id, (0, 0))
            session.player_session_stats[p.id] = (wins, losses + 1)


class LobbyCreatedView(discord.ui.View):
    """
    View class allowing the first match to be generated.
    """

    def __init__(self, cog: PUGs, session: PUGSession):
        super().__init__()
        self.cog = cog
        self.session = session

    @discord.ui.button(
        label="Generate Match", style=discord.ButtonStyle.primary, emoji="🤖"
    )
    async def button_callback(
        self, button: discord.ui.Button, interaction: discord.Interaction
    ):
        # Get the cog's defined teams and pass them along to MatchStartView
        await interaction.response.defer()
        await self.cog._generate_match_logic(self.session)
        start_view = MatchStartView(self.cog, self.session)
        start_embed = start_view.generate_embed()

        await interaction.edit_original_response(
            content=None, view=start_view, embed=start_embed
        )


class MatchStartView(discord.ui.View):
    """
    View class to show teams and move players before/during a match.
    """

    def __init__(self, cog: PUGs, session: PUGSession):
        super().__init__(timeout=None)
        self.cog = cog
        self.session = session
        self.blue_team = session.blue_team
        self.red_team = session.red_team

    def generate_embed(self) -> discord.Embed:
        embed = discord.Embed(title="Current Match")
        embed.add_field(
            name="🟦 Blue",
            value="\n".join([p.display_name for p in self.blue_team]),
            inline=True,
        )
        embed.add_field(
            name="🟥 Red",
            value="\n".join([p.display_name for p in self.red_team]),
            inline=True,
        )
        return embed

    @discord.ui.button(
        label="Move Players", style=discord.ButtonStyle.secondary, emoji="🚀"
    )
    async def move_callback(
        self, button: discord.ui.Button, interaction: discord.Interaction
    ):
        button.disabled = True
        await interaction.response.edit_message(view=self)

        async_tasks = []
        for p in self.blue_team:
            async_tasks.append(p.move_to(self.session.blue_channel))
        for p in self.red_team:
            async_tasks.append(p.move_to(self.session.red_channel))

        results = await asyncio.gather(*async_tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, Exception):
                print(result)

    @discord.ui.button(label="Blue Wins", style=discord.ButtonStyle.primary, emoji="🟦")
    async def blue_win_callback(self, button, interaction: discord.Interaction):
        await self.process_winner(interaction, winner="blue")

    @discord.ui.button(label="Red Wins", style=discord.ButtonStyle.danger, emoji="🟥")
    async def red_win_callback(self, button, interaction: discord.Interaction):
        await self.process_winner(interaction, winner="red")

    async def process_winner(self, interaction: discord.Interaction, winner: str):
        await interaction.response.defer()

        # Process match results in PUGs session storage
        await self.cog._process_match_results(self.session, winner=winner)

        # Move everyone back to lobby
        async_tasks = []
        for p in self.session.blue_channel.members:
            async_tasks.append(p.move_to(self.session.lobby_channel))
        for p in self.session.red_channel.members:
            async_tasks.append(p.move_to(self.session.lobby_channel))

        results = await asyncio.gather(*async_tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, Exception):
                print(result)

        # Prepare end card
        end_view = MatchEndView(
            self.cog, self.session, self.blue_team, self.red_team, winner
        )
        end_embed = end_view.generate_embed()
        await interaction.edit_original_response(view=end_view, embed=end_embed)


class MatchEndView(discord.ui.View):
    """
    View class showing results from last match.
    """

    def __init__(
        self,
        cog: PUGs,
        session: PUGSession,
        blue_team: List[discord.Member],
        red_team: List[discord.Member],
        winner: str,
    ):
        super().__init__(timeout=None)
        self.cog = cog
        self.session = session
        self.blue_team = blue_team
        self.red_team = red_team
        self.winner = winner

    def generate_embed(self):
        embed = discord.Embed(title=f"{self.winner.title()} Wins!")
        return embed

    @discord.ui.button(
        label="Generate Next Match", style=discord.ButtonStyle.primary, emoji="🤖"
    )
    async def button_callback(
        self, button: discord.ui.Button, interaction: discord.Interaction
    ):
        button.disabled = True
        await interaction.response.edit_message(view=self)

        # Get the cog's defined teams and pass them along to MatchStartView
        await self.cog._generate_match_logic(self.session)
        start_view = MatchStartView(self.cog, self.session)
        start_embed = start_view.generate_embed()

        await interaction.followup.send(view=start_view, embed=start_embed)


def setup(bot):
    bot.add_cog(PUGs(bot))
