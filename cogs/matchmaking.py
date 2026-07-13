import discord
import random
from discord.ext import commands

from utils import config
from utils import db


GUILD_ID = config.secrets["discord"]["guild_id"]
GAME_CHOICES = list(config.config.get("profile", {}).get("games", {}).keys())
DEFAULT_TAG = "🖱️"
TEAM_NAMES = [tuple(pair) for pair in config.config["matchmaking"]["team_names"]]
class MatchmakingSession:
    def __init__(self, game):
        self.game = game
        self.joined: list[discord.Member] = []
        self.tags: dict[int, str] = {} #member.id to tag
        self.team_a: list[discord.Member] = []
        self.team_b: list[discord.Member] = []
        self.team_names: tuple[(str, str)] = random.choice(TEAM_NAMES)
        self.role_assignments: dict[int, str] = {} #member.id to role
        self.message: discord.Message | None = None

class Matchmaking(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active_sessions: dict[tuple[int, str], MatchmakingSession] = {}

    matchmaking_group = discord.SlashCommandGroup("matchmaking", "matchmaking tools")

    @matchmaking_group.command(name="start", guild_ids=[GUILD_ID])
    async def start(
        self,
        ctx,
        game: discord.Option(
            str,
            description="Game to matchmake for",
            choices=GAME_CHOICES
        ),
        teamOne: discord.Option(
            str,
            name="team_one",
            description="Team one's name",
            default=None
        ),
        teamTwo: discord.Option(
            str,
            name="team_two",
            description="Team two's name",
            default=None
        ),
    ):
        await ctx.defer()

        key = (ctx.channel.id, game)

        if key in self.active_sessions:
            session = self.active_sessions[key]
            if session.message is not None:
                try:
                    await session.message.delete()
                except discord.NotFound:
                    pass
        else:
            session = MatchmakingSession(game)
            self.active_sessions[key] = session

        if teamOne:
            session.team_names = (teamOne, session.team_names[1])
        if teamTwo:
            session.team_names = (session.team_names[0], teamTwo)

        view = LobbyView(session)
        embed = view.generate_embed()
        message = await ctx.followup.send(embed=embed, view=view)
        session.message = message
    
class LobbyView(discord.ui.View):
    def __init__(self, session):
        super().__init__(timeout=None)
        self.session = session

    def generate_embed(self):
        embed = discord.Embed(
            title=f"{self.session.game.title()} Lobby",
            description=f"({len(self.session.joined)}/10)",
            color = discord.Color.from_rgb(78,42,132),
        )
        
        left_rows = ["-"] * 5
        right_rows = ["-"] * 5
        for i, member in enumerate(self.session.joined):
            tag = self.session.tags.get(member.id, DEFAULT_TAG)
            entry = f"{tag} {member.display_name}"
            row = i // 2
            if i % 2 == 0:
                left_rows[row] = entry
            else:
                right_rows[row] = entry

        embed.add_field(name=f"{self.session.team_names[0]}", value="\n".join(left_rows), inline=True)
        embed.add_field(name=f"{self.session.team_names[1]}", value="\n".join(right_rows), inline=True)
        return embed


    @discord.ui.button(label="Join", style=discord.ButtonStyle.success)
    async def join(self, button, interaction):
        if any(m.id == interaction.user.id for m in self.session.joined):
            await interaction.response.send_message("You've already joined!", ephemeral=True)
            return
        if len(self.session.joined) >= 10:
            await interaction.response.send_message("Lobby already full... :/", ephemeral=True)
            return
        
        row = await db.fetch_one("SELECT tag FROM profiles WHERE discordid = %s;", (interaction.user.id,))
        self.session.tags[interaction.user.id] = row[0] if row and row[0] else DEFAULT_TAG

        self.session.joined.append(interaction.user)
        await interaction.response.edit_message(embed=self.generate_embed(), view=self)


    @discord.ui.button(label="Leave", style=discord.ButtonStyle.danger)
    async def leave(self, button, interaction):
        if not any(m.id == interaction.user.id for m in self.session.joined):
            await interaction.response.send_message("You haven't joined this lobby!", ephemeral=True)
            return

        self.session.joined = [m for m in self.session.joined if m.id != interaction.user.id]
        self.session.tags.pop(interaction.user.id, None)
        await interaction.response.edit_message(embed=self.generate_embed(), view=self)
    
    @discord.ui.button(label="Shuffle", style=discord.ButtonStyle.primary)
    async def shuffle(self, button, interaction):
        #TODO: add gamehead barrier
        if len(self.session.joined) != 10:
            await interaction.response.send_message("Find a full 10 first!", ephemeral=True)
            return
        
        #TODO: rank balancing
        await interaction.response.send_message("shuffling TBD...", ephemeral=True)

def setup(bot):
    bot.add_cog(Matchmaking(bot))