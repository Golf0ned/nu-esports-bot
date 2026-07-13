import discord
from discord.ext import commands

from utils import config
from utils import db


GUILD_ID = config.secrets["discord"]["guild_id"]
GAME_CHOICES = list(config.config.get("profile", {}).get("games", {}).keys())

class MatchmakingSession:
    def __init__(self, game):
        self.game = game
        self.joined: list[discord.Member] = []
        self.team_a: list[discord.Member] = []
        self.team_b: list[discord.Member] = []
        self.role_assignments: dict[int, str] = {} #member.id to role

class Matchmaking(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active_sessions = {}

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
    ):
        if ctx.channel.id in self.active_sessions:
            await ctx.respond("Match already in session in this channel!", ephemeral=True)
            return
        
        session = MatchmakingSession(game)
        self.active_sessions[ctx.channel.id] = session

        view = LobbyView(session)
        embed = view.generate_embed()
        await ctx.respond(embed=embed, view=view)
    
class LobbyView(discord.ui.View):
    def __init__(self, session):
        super().__init__(timeout=None)
        self.session = session

    def generate_embed(self):
        embed = discord.Embed(
            title=f"{self.session.game.title()} Lobby",
            color = discord.Color.from_rgb(78,42,132),
        )
        roster = "\n".join(m.display_name for m in self.session.joined) or "None yet!"
        embed.add_field(name=f"Joined ({len(self.session.joined)}/10)", value=roster, inline=False)
        return embed


    @discord.ui.button(label="Join", style=discord.ButtonStyle.success)
    async def join(self, button, interaction):
        if any(m.id == interaction.user.id for m in self.session.joined):
            await interaction.response.send_message("You've already joined!", ephemeral=True)
            return
        if len(self.session.joined) >= 10:
            await interaction.response.send_message("Lobby already full... :/", ephemeral=True)
            return
        
        self.session.joined.append(interaction.user)
        await interaction.response.edit_message(embed=self.generate_embed(), view=self)


    @discord.ui.button(label="leave", style=discord.ButtonStyle.danger)
    async def leave(self, button, interaction):
        if not any(m.id == interaction.user.id for m in self.session.joined):
            await interaction.response.send_message("You haven't joined this lobby!", ephemeral=True)
            return
        
        self.session.joined = [m for m in self.session.joined if m.id != interaction.user.id]
        await interaction.response.edit_message(embed=self.generate_embed(), view=self)
    
    @discord.ui.button(label="shuffle", style=discord.ButtonStyle.primary)
    async def shuffle(self, button, interaction):
        #TODO: add gamehead barrier
        if len(self.session.joined) != 10:
            await interaction.response.send_message("Find a full 10 first!", ephemeral=True)
            return
        
        #TODO: rank balancing
        await interaction.response.send_message("shuffling TBD...", ephemeral=True)

def setup(bot):
    bot.add_cog(Matchmaking(bot))