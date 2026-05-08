import discord
import random
from discord.ext import commands, tasks

from utils import config
from utils.statuses import load_statuses

GUILD_ID = config.secrets["discord"]["guild_id"]
BOT_DEVS = config.config["bot_devs"]
STREAM_LINK = "https://twitch.tv/NorthwesternEsports"
STREAM_TEAM_ROLE_ID = 1170159172667584572
CYCLE_MINS = 3

class Presence(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.index = 0
        self.lastindex = -1
        self.statuses = load_statuses()

    @commands.Cog.listener()
    async def on_ready(self):
        if not self.cycle_status.is_running():
            self.cycle_status.start()

    @tasks.loop(minutes=CYCLE_MINS)
    async def cycle_status(self):
        while self.index == self.lastindex: #basic shuffle, won't do something twice in a row.
            self.index = random.randint(0,len(self.statuses)-1)
        await self.bot.change_presence(activity=self.statuses[self.index])
        self.lastindex = self.index

    @discord.slash_command(
            name="status",
            description="Changes status of the bot",
            guild_ids=[GUILD_ID],
    )
    async def status(self, 
                    ctx: discord.ApplicationContext, 
                    type: str = discord.Option(str, "What kind of status?", choices=["streaming", "default", "custom"]),
                    status: str = ""):
        if (ctx.author.id not in BOT_DEVS) and (not discord.utils.get(ctx.author.roles, id=STREAM_TEAM_ROLE_ID)):
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
            if status == "":
                await ctx.respond("🔮 Cleared status!", ephemeral=True)
            else:
                await ctx.respond(f"📝 Changed status to \"{status}\"!", ephemeral=True)

        else: #default
            try:
                self.cycle_status.start()
            except RuntimeError:
                await ctx.respond("❌ Something went wrong. Try again!", ephemeral=True)
                return
            await ctx.respond("🤖 Resumed cycling status!", ephemeral=True)

def setup(bot):
    bot.add_cog(Presence(bot))