import discord
from discord.ext import commands

from utils import config
from utils import db


GUILD_ID = config.secrets["discord"]["guild_id"]
GAME_CHOICES = list(config.game_data.keys())


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
            decription= "Game to show leaderboard for",
            choices=GAME_CHOICES,
        )
    ) -> None:
        """Show the top 10 players for a game, ranked by elo but displayed as win/loss"""
        await ctx.defer()

        rows = await db.fetch_all(
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

        if not rows:
            await ctx.followup.send(f"No one's played {game.title()} yet!")
            return
        
        lines = []
        caller_rank = None
        caller_line = None
        for rank, (discordid, wins, losses, tag) in enumerate(rows, start=1):
            member = ctx.guild.get_member(discordid)
            name = member.display_name if member else f"<@{discordid}>"
            tag = tag or "⭐"
            line = f"{rank}. {tag} {name} — {wins}W {losses}L"
            if rank <= 10:
                lines.append(line)
            if discordid == ctx.author.id:
                caller_rank = rank
                caller_line = line

            description = "\n".join(lines)
            if caller_rank is not None and caller_rank > 10:
                description += f"\n...\n{caller_line}"
            elif caller_rank is None:
                description += f"\n...\nYou haven't played {game.title()} yet!"

            embed = discord.Embed(
                title=f"{game.title()} Leaderboard",
                description=description,
            color=discord.Color.from_rgb(78, 42, 132),
        )
            
        await ctx.followup.send(embed=embed)

def setup(bot: discord.Bot) -> None:
    bot.add_cog(Leaderboard(bot))