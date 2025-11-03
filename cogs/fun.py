import asyncio
import random

import discord
from discord.ext import commands

from utils import config


GUILD_ID = config.secrets["discord"]["guild_id"]


class Fun(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @discord.slash_command(
        name="mutehannah",
        description="Mutes Hannah for 3 minutes in text and voice",
        guild_ids=[GUILD_ID],
    )
    async def mutehannah(self, ctx):
        # Check if the user has the required role
        required_role_id = config.config["fun"]["hannah-haters"]
        if not ctx.author.get_role(required_role_id):
            await ctx.respond(
                "You don't have permission to use this command!", ephemeral=True
            )
            return

        # Defer the response to avoid timeout (processing takes time)
        await ctx.defer()

        # Get the target user ID from config
        target_user_id = config.config["fun"]["hannah"]

        # Fetch the member
        try:
            member = await ctx.guild.fetch_member(target_user_id)
        except discord.NotFound:
            await ctx.respond("Hannah is not in this server!")
            return
        except discord.HTTPException:
            await ctx.respond("Failed to fetch Hannah from the server!")
            return

        # Deny send message permissions in all text channels
        text_channels = [
            channel
            for channel in ctx.guild.channels
            if isinstance(channel, discord.TextChannel)
        ]

        # Store original permissions to restore later
        original_permissions = {}
        for channel in text_channels:
            try:
                overwrite = channel.overwrites_for(member)
                original_permissions[channel.id] = overwrite.send_messages
                overwrite.send_messages = False
                await channel.set_permissions(
                    member, overwrite=overwrite, reason="Muted by /mutehannah command"
                )
            except (discord.Forbidden, discord.HTTPException):
                pass  # Skip channels where we don't have permission

        # Schedule permission restore after 3 minutes
        async def restore_text_permissions():
            await asyncio.sleep(180)
            for channel in text_channels:
                try:
                    overwrite = channel.overwrites_for(member)
                    # Restore original permission state
                    original_perm = original_permissions.get(channel.id)
                    if original_perm is None:
                        # Remove the overwrite if it wasn't set before
                        overwrite.send_messages = None
                        if overwrite.is_empty():
                            await channel.set_permissions(
                                member,
                                overwrite=None,
                                reason="Auto-unmute after 3 minutes",
                            )
                        else:
                            await channel.set_permissions(
                                member,
                                overwrite=overwrite,
                                reason="Auto-unmute after 3 minutes",
                            )
                    else:
                        overwrite.send_messages = original_perm
                        await channel.set_permissions(
                            member,
                            overwrite=overwrite,
                            reason="Auto-unmute after 3 minutes",
                        )
                except (discord.Forbidden, discord.HTTPException):
                    pass  # Silently fail if we can't restore

        # Run the restore task in the background
        asyncio.create_task(restore_text_permissions())

        # Mute in voice if they're in a voice channel
        voice_muted = False
        if member.voice and member.voice.channel:
            try:
                await member.edit(mute=True, reason="Muted by /mutehannah command")
                voice_muted = True

                # Schedule unmute after 3 minutes
                async def unmute_after_delay():
                    await asyncio.sleep(180)
                    try:
                        # Check if member is still in voice
                        if member.voice and member.voice.channel:
                            await member.edit(
                                mute=False, reason="Auto-unmute after 3 minutes"
                            )
                    except (discord.Forbidden, discord.HTTPException):
                        pass  # Silently fail if we can't unmute

                # Run the unmute task in the background
                asyncio.create_task(unmute_after_delay())
            except discord.Forbidden:
                await ctx.respond(
                    "Hannah has been muted in text for 3 minutes, but I don't have permission to voice mute!"
                )
                return
            except discord.HTTPException:
                pass  # Voice mute failed, but timeout succeeded

        # Send confirmation message
        if voice_muted:
            await ctx.respond(
                "Hannah has been muted for 3 minutes in both text and voice! 🤫"
            )
        else:
            await ctx.respond(
                "Hannah has been muted for 3 minutes in text channels! 🤫"
            )

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author == self.bot.user:
            return

        if output := chess(self, message):
            await message.add_reaction(output)

        if output := i_love_osu(message):
            await message.reply(output)

        if output := oh_lord(message):
            await message.reply(output)

        if output := special_interactions(message):
            for emoji in output:
                await message.add_reaction(emoji)


def chess(self, message):
    if self.bot.user.mentioned_in(message):
        if message.mention_everyone:
            return None

        chess_emojis = config.config["fun"]["chess_emojis"]
        emoji, id = random.choice(list(chess_emojis.items()))
        output = f"<:{emoji}:{id}>"
        return output


def i_love_osu(message):
    lower_content = message.content.lower()
    if "i love osu" in lower_content:
        output = "Osu 😻"
        return output
    return None


def oh_lord(message):
    lower_content = message.content.lower()
    if random.randint(1, 100) <= 10 and "oh lord" in lower_content:
        output = "https://www.youtube.com/watch?v=YsoP6bjADic"
        return output
    return None


def special_interactions(message):
    special_users = config.config["fun"]["special_users"]
    if random.randint(1, 100) <= 15 and message.author.id in special_users:
        output = [random.choice(special_users[message.author.id])]
        return output
    return None


def setup(bot):
    bot.add_cog(Fun(bot))
