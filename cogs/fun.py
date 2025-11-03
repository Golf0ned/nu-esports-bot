import asyncio
import random
from datetime import timedelta

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

        # Get the target user ID from config
        target_user_id = config.config["fun"]["hannah"]

        # Fetch the member
        try:
            member = await ctx.guild.fetch_member(target_user_id)
        except discord.NotFound:
            await ctx.respond("Hannah is not in this server!", ephemeral=True)
            return
        except discord.HTTPException:
            await ctx.respond("Failed to fetch Hannah from the server!", ephemeral=True)
            return

        # Apply timeout for text channels (3 minutes)
        try:
            await member.timeout_for(
                timedelta(minutes=3), reason="Muted by /mutehannah command"
            )
        except discord.Forbidden:
            await ctx.respond(
                "I don't have permission to timeout Hannah!", ephemeral=True
            )
            return
        except discord.HTTPException as e:
            await ctx.respond(f"Failed to timeout Hannah: {e}", ephemeral=True)
            return

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
                    "Hannah has been timed out for 3 minutes, but I don't have permission to voice mute!",
                    ephemeral=True,
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
                "Hannah has been timed out for 3 minutes in text channels! 🤫"
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
