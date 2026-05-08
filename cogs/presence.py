import asyncio
import discord
from discord import default_permissions
from discord.ext import commands, tasks

from utils import config

GUILD_ID = config.secrets["discord"]["guild_id"]
BOT_DEVS = config.config["bot_devs"]
STREAM_LINK = "https://twitch.tv/NorthwesternEsports"

STATUSES = [
    discord.Activity(type=discord.ActivityType.listening, name="UNCA / Composure"),
    discord.Activity(type=discord.ActivityType.listening, name="Weston Super Mare"),
    discord.Activity(type=discord.ActivityType.listening, name="Flyen"),
    discord.Activity(type=discord.ActivityType.listening, name="Polo Ponies")
]

class Presence(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.index = 0

    @commands.Cog.listener()
    async def on_ready(self):
        if not self.cycle_status.is_running():
            self.cycle_status.start()

    @tasks.loop(minutes=0.1)
    async def cycle_status(self):
        await self.bot.change_presence(activity=STATUSES[self.index])
        self.index = (self.index + 1) % len(STATUSES)

    @discord.slash_command(
            name="status",
            description="Changes status of the bot",
            guild_ids=[GUILD_ID],
    )
    async def status(self, 
                    ctx: discord.ApplicationContext, 
                    type: str = discord.Option(str, "What kind of status?", choices=["streaming", "default", "custom"]),
                    status: str = ""):
        if ctx.author.id not in BOT_DEVS:
            await ctx.respond("You don't have permission to use this command.", ephemeral=True)
            return
        
        if type == "streaming":
            self.cycle_status.stop()
            if status == "":
                status = "NU Esports is live!"
            await self.bot.change_presence(activity=discord.Streaming(name=status, url=STREAM_LINK))
            await ctx.respond("🚨 Showing stream in status!", ephemeral=True)

        elif type == "custom":
            self.cycle_status.stop()
            await self.bot.change_presence(activity=discord.Activity(type=discord.ActivityType.playing, name=status))
            await ctx.respond(f"📝 Changed status to \"{status}\"!", ephemeral=True)

        else: #default
            self.cycle_status.start()
            await ctx.respond("🤖 Resumed cycling status!")

def setup(bot):
    bot.add_cog(Presence(bot))