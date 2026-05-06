import discord
from discord import default_permissions
from discord.ext import commands

from utils import config

GUILD_ID = config.secrets["discord"]["guild_id"]

class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @discord.slash_command(
        name="purge",
        description="Delete recent messages",
        guild_ids=[GUILD_ID]
    )
    @default_permissions(manage_messages=True)
    async def purge(self, ctx: discord.ApplicationContext, amount: int):
        if not ctx.channel.permissions_for(ctx.author).manage_messages:
            await ctx.respond("You do not have permission to use this command.", ephemeral=True)
            return

        await ctx.defer(ephemeral=True)
        deleted = await ctx.channel.purge(limit=amount)
        await ctx.followup.send(f"Deleted {len(deleted)} messages.", ephemeral=True)


def setup(bot):
    bot.add_cog(Moderation(bot))