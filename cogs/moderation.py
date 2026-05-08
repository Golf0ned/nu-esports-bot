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


    @discord.slash_command(
        name="lock",
        description="Locks a channel (hiding optional). /Unlock to undo",
        guild_ids=[GUILD_ID]
    )
    @default_permissions(manage_channels=True)
    async def lock(self, ctx: discord.ApplicationContext, hide: bool=True):
        if not ctx.channel.permissions_for(ctx.author).manage_channels:
            await ctx.respond("You do not have permission to use this command.", ephemeral=True)
            return
        
        overwrite = ctx.channel.overwrites_for(ctx.guild.default_role)
        overwrite.send_messages = False 
        if hide: overwrite.view_channel = False
        await ctx.channel.set_permissions(ctx.guild.default_role, overwrite=overwrite)
        await ctx.respond("🔒 Channel locked.")

    @discord.slash_command(
        name="unlock",
        description="Unlocks a channel (unhiding optional)",
        guild_ids=[GUILD_ID]
    )
    @default_permissions(manage_channels=True)
    async def unlock(self, ctx: discord.ApplicationContext, unhide: bool=True):
        if not ctx.channel.permissions_for(ctx.author).manage_channels:
            await ctx.respond("You do not have permission to use this command.", ephemeral=True)
            return
        
        overwrite = ctx.channel.overwrites_for(ctx.guild.default_role)
        overwrite.send_messages = True
        if unhide: overwrite.view_channel = True
        await ctx.channel.set_permissions(ctx.guild.default_role, overwrite=overwrite)
        await ctx.respond("🔓 Channel unlocked.", ephemeral=True)

def setup(bot):
    bot.add_cog(Moderation(bot))