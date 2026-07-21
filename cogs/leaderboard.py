import discord
from discord.ext import commands

from utils import config
from utils import db


GUILD_ID = config.secrets["discord"]["guild_id"]
GAME_CHOICES = list(config.game_data.keys())
PAGE_SIZE = 10

async def fetch_leaderboard_rows(game: str) -> list[tuple]:
    """Fetch every player's win/loss + tag for a game, ranked by elo (elo itself not selected)."""
    return await db.fetch_all(
        """
        SELECT pe.discordid, COALESCE(ps.wins, 0) AS wins, COALESCE(ps.losses, 0) AS losses, p.tag
        FROM profile_elo pe
        LEFT JOIN profile_stats ps ON ps.discordid = pe.discordid AND ps.game = pe.game
        LEFT JOIN profiles p ON p.discordid = pe.discordid
        WHERE pe.game = %s
        ORDER BY pe.elo DESC;
        """,
        (game,),
    )

def format_entry(guild: discord.Guild, rank: int, discordid: int, wins: int, losses: int, tag: str | None) -> str:
    """Format one leaderboard row: rank, tag (defaulting to a star), display name, and W/L record."""
    member = guild.get_member(discordid)
    name = member.display_name if member else f"<@{discordid}>"
    tag = tag or "⭐"
    return f"{rank}. {tag} *{name}* — **{wins}W** / **{losses}L**"

def build_leaderboard_pages(guild: discord.Guild, game: str, rows: list[tuple], caller_id: int) -> list[discord.Embed]:
    """Build one embed per page of 10 leaderboard entries, ordered by elo but never showing it.

    The caller's own line is always visible: pinned at the bottom of a page while their real rank
    is still further down the list, pinned at the top once you've paged past it, and left out of
    the pinned spot entirely on the page their rank actually falls on (already part of that page).
    """
    present_rows = [row for row in rows if guild.get_member(row[0]) is not None]
    if not present_rows:
        return None

    total_pages = max(1, -(-len(present_rows) // PAGE_SIZE)) #ceiling divison

    caller_rank = None
    caller_line = None
    for rank, (discordid, wins, losses, tag) in enumerate(present_rows, start=1):
        if discordid == caller_id:
            caller_rank = rank
            caller_line = format_entry(guild, rank, discordid, wins, losses, tag)
            break

    pages = []
    for page in range(total_pages):
        start = page * PAGE_SIZE
        chunk = present_rows[start:start+ PAGE_SIZE]
        lines = [
            format_entry(guild, start + i + 1, discordid, wins, losses, tag)
            for i, (discordid, wins, losses, tag) in enumerate(chunk)
        ]

        page_start_rank = start + 1
        page_end_rank = start + len(chunk)

        if caller_rank is None:
            lines.append(f"...\nYou haven't played {game.title()} yet!")
        elif caller_rank < page_start_rank:
            lines.insert(0, f"{caller_line}\n...")
        elif caller_rank > page_end_rank:
            lines.append(f"...\n{caller_line}")
        # else: caller's own rank falls on this page already

        embed = discord.Embed(
            title=f"{game.title()} Leaderboard",
            description="\n".join(lines),
            color=discord.Color.from_rgb(78, 42, 132),
        )
        embed.set_footer(text=f"Page {page+1}/{total_pages}")
        pages.append(embed)

    return pages

class GameSelectView(discord.ui.View):
    """Dropdown for switching the leaderboard to a different game, restricted to whoever ran /leaderboard."""

    def __init__(self, requester_id: int, guild: discord.Guild):
        super().__init__(timeout=120)
        self.requester_id = requester_id
        self.guild = guild

        options = [discord.SelectOption(label=g.title(), value=g) for g in GAME_CHOICES]
        self.select = discord.ui.Select(placeholder="Pick a game", options=options)
        self.select.callback = self.on_select
        self.add_item(self.select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Block anyone but whoever ran /leaderboard from switching games."""
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message(
                "This isn't your interaction call to flip through!", ephemeral=True
            )
            return False
        return True
    
    async def on_select(self, interaction: discord.Interaction) -> None:
        """Rebuild the leaderboard for the newly chosen game."""
        game = self.select.values[0]

        rows = await fetch_leaderboard_rows(game)
        pages = build_leaderboard_pages(self.guild, game, rows, self.requester_id)

        if pages is None:
            await interaction.response.edit_message(
                content=f"No one currently in the server has played {game.title()} yet!",
                embed=None,
                view=EmptyLeaderboardView(requester_id=self.requester_id, guild=self.guild),
            )
            return

        paginator = LeaderboardPaginator(requester_id=self.requester_id, pages=pages, guild=self.guild)
        await interaction.response.edit_message(content=None, embed=pages[0], view=paginator)
        paginator.message = await interaction.original_response()

class EmptyLeaderboardView(discord.ui.View):
    """Shown when a game's leaderboard has nobody on it, just a way to switch games."""

    def __init__(self, requester_id: int, guild: discord.Guild):
        super().__init__(timeout=120)
        self.requester_id = requester_id
        self.guild = guild

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Block anyone but whoever ran /leaderboard from switching games."""
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message(
                "This isn't your leaderboard call to flip through!", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="Change Game", style=discord.ButtonStyle.primary)
    async def change_game(self, button: discord.ui.Button, interaction: discord.Interaction) -> None:
        """Swap to a dropdown for picking a different game's leaderboard."""
        await interaction.response.edit_message(content=None, view=GameSelectView(requester_id=self.requester_id, guild=self.guild))

class LeaderboardPaginator(discord.ui.View):
    """Left/right paginator over a leaderboard's pages of 10, restricted to whoever ran the command."""

    def __init__(self, requester_id: int, pages: list[discord.Embed], guild: discord.Guild):
        super().__init__(timeout=120)
        self.requester_id = requester_id
        self.pages = pages
        self.guild = guild
        self.index = 0
        self.update_buttons()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Block anyone but whoever ran /leaderboard from flipping through it."""
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message(
                "This isn't your interaction to flip through!", ephemeral=True,
            )
            return False
        return True
    
    def update_buttons(self) -> None:
        """Disable ◀ on the first page and ▶ on the last page."""
        self.back.disabled = (self.index == 0)
        self.forward.disabled = (self.index == len(self.pages) - 1)

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary)
    async def back(self, button: discord.ui.Button, interaction: discord.Interaction) -> None:
        """Go to the previous page."""
        self.index -= 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.pages[self.index], view=self)

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary)
    async def forward(self, button: discord.ui.Button, interaction: discord.Interaction) -> None:
        """Go to the next page."""
        self.index += 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.pages[self.index], view=self)

    @discord.ui.button(label="Change Game", style=discord.ButtonStyle.primary, row=1)
    async def change_game(self, button: discord.ui.Button, interaction: discord.Interaction) -> None:
        """Swap to a dropdown for picking a different game's leaderboard."""
        await interaction.response.edit_message(view=GameSelectView(requester_id=self.requester_id, guild=self.guild))

    async def on_timeout(self) -> None:
        """Disable both buttons once the view times out, so it doesn't look interactive anymore."""
        for child in self.children:
            child.disabled = True
        await self.message.edit(view=self)

class Leaderboard(commands.Cog):
    """Cog housing the /leaderboard command: per-game rankings, ordered by elo but displayed by win/loss record."""

    def __init__(self, bot):
        self.bot = bot

    @discord.slash_command(
        name="leaderboard",
        description="Show the top players for a game",
        guild_ids=[GUILD_ID]
    )
    async def leaderboard(
        self,
        ctx: discord.ApplicationContext,
        game: discord.Option (
            str,
            description= "Game to show leaderboard for",
            choices=GAME_CHOICES,
        )
    ) -> None:
        """Show the top 10 players for a game, ranked by elo but displayed as win/loss"""
        await ctx.defer()

        rows = await fetch_leaderboard_rows(game)

        if not rows:
            await ctx.followup.send(f"No one's played {game.title()} yet!")
            return

        pages = build_leaderboard_pages(ctx.guild, game, rows, ctx.author.id)

        if pages is None:
            await ctx.followup.send(
                f"No one currently in the server has played {game.title()} yet!",
                view=EmptyLeaderboardView(requester_id=ctx.author.id, guild=ctx.guild),
            )
            return

        paginator = LeaderboardPaginator(requester_id=ctx.author.id, pages=pages, guild=ctx.guild)
        message = await ctx.followup.send(embed=pages[0], view=paginator)
        paginator.message = message

def setup(bot: discord.Bot) -> None:
    bot.add_cog(Leaderboard(bot))