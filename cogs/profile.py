import discord
from discord.ext import commands

from utils import config
from utils import db


GUILD_ID = config.secrets["discord"]["guild_id"]
GAME_CHOICES = list(config.config.get("profile", {}).get("games", {}).keys())

def get_tiers(game):
    return config.config["profile"]["games"][game]["tiers"]

def get_divisions(game):
    return config.config["profile"]["games"][game]["divisions"]

def get_roles(game):
    return config.config["profile"]["games"][game]["roles"]

def get_mains(game):
     return config.config[game]["agents"]

def tier_has_divisions(game, tier):
    return tier not in config.config["profile"]["games"][game]["no_division_tiers"]

def compute_rank_value(game, tier, division):
    index = get_tiers(game).index(tier)
    divisions = get_divisions(game)
    if tier_has_divisions(game, tier):
        return index * divisions + (division - 1)
    else:
        return index * divisions
    
def format_rank_label(game, tier, division):
    return f"{tier} {division}" if tier_has_divisions(game, tier) else tier


async def tier_autocomplete(ctx: discord.AutocompleteContext):
    game = ctx.options.get("game")
    return [discord.OptionChoice(t) for t in get_tiers(game)] if game else []

async def division_autocomplete(ctx: discord.AutocompleteContext):
    game, tier = ctx.options.get("game"), ctx.options.get("tier")
    if not game or not tier_has_divisions(game, tier):
        return ["1"]
    divisions_per_tier = get_divisions(game)
    return [str(d) for d in range(1, divisions_per_tier+1)]

async def roles_autocomplete(ctx: discord.AutocompleteContext):
    game, role = ctx.options.get("game"), ctx.options.get("role")
    if not game or not role:
        return []
    return [discord.OptionsChoice(r) for r in get_roles(game)]

async def mains_autocomplete(ctx: discord.AutocompleteCotnext):
    game, main = ctx.options.get("game"), ctx.options.get("main")
    if not game or not main:
        return []
    return [discord.OptionsChoice(m) for m in get_mains(game)]



class Profile(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    profile = discord.SlashCommandGroup("profile", "Profile tools")
    set_grp = discord.create_subgroup("set", "Set something on your profile")

    @set_grp.command(
            name = "rank",
            guild_ids = [GUILD_ID]
    )
    async def rank(
        self, 
        ctx,
        game: discord.Option(
            str,
            name="game",
            description="Game to change something about",
            choices=GAME_CHOICES,
        ),
        tier: discord.Option(
            str,
            name="tier",
            description="Your rank tier",
            autocomplete=tier_autocomplete,
        ),
        division: discord.Option(
            str,
            name="division",
            description="Your division (if applicable)",
            autocomplete=division_autocomplete,
            default="1",
        )
    )
        return NotImplementedError

    @set_grp.command(
            name = "role",
            guild_ids = [GUILD_ID]
    )
    async def role(
        self,
        ctx,
        game: discord.Option(
            str,
            name="game",
            description="Game to change something about",
            choices=GAME_CHOICES,
        ),
        role: discord.Option(
            str,
            name="role",
            description="The role you play",
            autocomplete=roles_autocomplete
        )
    )
        return NotImplementedError

    @set_grp.command(
            name = "main",
            guild_ids = [GUILD_ID]
    )
    async def main(
        self,
        ctx,
        game: discord.Option(
            str,
            name="game",
            description="Game to change something about",
            choices=GAME_CHOICES,
        ),
        main: discord.Option(
            str,
            name="main",
            description="Your main in the game",
            autocomplete=mains_autocomplete
        )
    )
        return NotImplementedError

    
    @profile.command(
            name = "view",
            guild_ids = [GUILD_ID]
    )
    async def view(
        self,
        ctx,
        user: discordOption(
            discord.User,
            description="Defaults to you",
            default=None
        ),
        game: discord.Option(
            str,
            name="game",
            description="Game to change something about",
            choices=GAME_CHOICES,
        )
    )
        return NotImplementedError
    





    @profile.command(
        name = "set",
        description = "Set something on your profile",
        guild_ids=[GUILD_ID]
    )
    async def set(
        self, 
        ctx,
        game: discord.Option(
            str,
            name="game",
            description="Game to change something about",
            choices=GAME_CHOICES,
        ),
        tier: discord.Option(
            str,
            name="tier",
            description="Your rank tier",
            autocomplete=tier_autocomplete,
        ),
        division: discord.Option(
            str,
            name="division",
            description="Your division (if applicable)",
            autocomplete=division_autocomplete,
            default="1",
        )
    ):
        await ctx.defer(ephemeral=True)

        if thing not in THINGS:
            await ctx.followup.send(
                "Invalid thing. Please select from dropdown.", ephemeral=True
            )
            return

        if tier not in get_tiers(game):
            await ctx.followup.send(
                "Invalid tier. Please select from dropdown.", ephemeral=True
            )
            return
        
        try:
            division_int = int(division)
            if division_int > get_divisions(game):
                await ctx.followup.send(
                "Invalid division. Please select from dropdown.", ephemeral=True
                )
                return
        except ValueError:
            await ctx.followup.send(
                "Invalid division. Please select from dropdown.", ephemeral=True
            )
            return

        rank_value = compute_rank_value(game, tier, division_int)
        rank_label = format_rank_label(game, tier, division_int)

        sql = """
            INSERT INTO player_ranks (discordid, game, rank_value, rank_label, updated_at)
            VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (discordid, game)
            DO UPDATE SET
                rank_value = EXCLUDED.rank_value,
                rank_label = EXCLUDED.rank_label,
                updated_at = CURRENT_TIMESTAMP;
        """
        await db.perform_one(sql, (ctx.author.id, game, rank_value, rank_label))

        embed = discord.Embed(
            title="Rank Updated",
            description=f"{game.title()}: **{rank_label}**",
            color=discord.Color.from_rgb(78, 42, 132),
        )
        await ctx.followup.send(embed=embed, ephemeral=True)



    @rank.command(
            name="view",
            description="View a user's profile",
            guild_ids=[GUILD_ID],
    )
    async def view_rank(
            self,
            ctx,
            user: discord.Option(discord.User, description="User to view (defaults to you)", default=None),
    ):
        await ctx.defer()

        target = user or ctx.author

        sql = "SELECT game, rank_label FROM player_ranks WHERE discordid = %s ORDER BY game;"
        rows = await db.fetch_all(sql, (target.id,))

        embed = discord.Embed(
            title=f"{target.display_name}'s Ranks",
            color=discord.Color.from_rgb(78, 42, 132),
        ) 

        if not rows:
            embed.description = "No ranks set."
        else:
            for game, rank_label in rows:
                embed.add_field(name=game.title(), value=rank_label, inline=True)

        await ctx.followup.send(embed=embed)

class ProfilePaginator(discord.ui.View):
    def __init__(self, requester_id, pages, start_index=0):
        super().__init__(timeout=120)
        self.requester_id= requester_id
        self.pages = pages
        self.index = start_index,
        self.update_buttons()

    async def interaction_check(self, interaction):
        return NotImplementedError
    
    def update_buttons(self):
        return NotImplementedError
    
    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary)
    async def back(self, button, interaction):
        return NotImplementedError

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary)
    async def forward(self, button, interaction):
        return NotImplementedError
    
    async def on_timeout(self):
        return NotImplementedError

def setup(bot):
    bot.add_cog(Profile(bot))