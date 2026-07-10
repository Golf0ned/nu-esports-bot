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
    game = ctx.options.get("game")
    return [discord.OptionChoice(r) for r in get_roles(game)] if game else []

async def mains_autocomplete(ctx: discord.AutocompleteContext):
    game = ctx.options.get("game")
    return [discord.OptionChoice(m) for m in get_mains(game)] if game else []


def build_home_embed(target, profile_row, total_pages):
    bio = profile_row[0] if profile_row and profile_row[0] else "No bio set."
    picture_url = profile_row[1] if profile_row and profile_row[1] else None

    embed = discord.Embed(
        title=f"{target.display_name}'s Profile",
        description=bio,
        color=discord.Color.from_rgb(78, 42, 132),
    )
    embed.set_thumbnail(url=picture_url or target.display_avatar.url)
    embed.set_footer(text=f"Page 1/{total_pages}")
    return embed

def build_game_embed(target, game, row, page_number, total_pages):
    rank_label = row[1] if row else "Not set"
    role = row[2] if row else "Not set"
    main = row[3] if row else "Not set"

    embed = discord.Embed(
        title=f"{target.display_name} - {game.title()}",
        color=discord.Color.from_rgb(78, 42, 132),
    )
    embed.add_field(name="Rank", value=rank_label, inline=True)
    embed.add_field(name="Role", value=role, inline=True)
    embed.add_field(name="Main", value=main, inline=True)
    embed.set_footer(text=f"Page {page_number}/{total_pages}")
    return embed


class Profile(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    profile = discord.SlashCommandGroup("profile", "Profile tools")
    set_grp = profile.create_subgroup("set", "Set something on your profile")

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
    ):
        await ctx.defer(ephemeral=True)

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
            INSERT INTO profile_stats (discordid, game, rank_value, rank_label, updated_at)
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
    ):
        await ctx.defer(ephemeral=True)

        if role not in get_roles(game):
            await ctx.followup.send(
                "Invalid role. Please select from dropdown.", ephemeral=True
            )
            return
        sql = '''
            INSERT INTO profile_stats (discordid, game, role, updated_at)
            VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (discordid, game)
            DO UPDATE SET
                role = EXCLUDED.role,
                updated_at = CURRENT_TIMESTAMP;
        '''

        await db.perform_one(sql, (ctx.author.id, game, role))

        embed = discord.Embed(
            title="Role Updated",
            description=f"{game.title()}: **{role}**",
            color=discord.Color.from_rgb(78, 42, 132),
        )
        await ctx.followup.send(embed=embed, ephemeral=True)

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
    ):
        await ctx.defer(ephemeral=True)

        if main not in get_mains(game):
            await ctx.followup.send(
                "Invalid main. Please select from dropdown.", ephemeral=True
            )
            return
        sql = '''
            INSERT INTO profile_stats (discordid, game, main, updated_at)
            VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (discordid, game)
            DO UPDATE SET
                main = EXCLUDED.main,
                updated_at = CURRENT_TIMESTAMP;
        '''

        await db.perform_one(sql, (ctx.author.id, game, main))

        embed = discord.Embed(
            title="Main Updated",
            description=f"{game.title()}: **{main}**",
            color=discord.Color.from_rgb(78, 42, 132),
        )
        await ctx.followup.send(embed=embed, ephemeral=True)


    @profile.command(
            name = "view",
            guild_ids = [GUILD_ID]
    )
    async def view(
        self,
        ctx,
        user: discord.Option(
            discord.User,
            description="Defaults to you",
            default=None
        ),
        game: discord.Option(
            str,
            name="game",
            description="Game to change something about",
            choices=GAME_CHOICES,
            default=None
        )
    ):
        await ctx.defer()

        target = user or ctx.author

        profile_row = await db.fetch_one(
            "SELECT bio, picture_url FROM profiles WHERE discordid = %s;",
            (target.id,)
        )
        stats_rows = await db.fetch_all(
            "SELECT game, rank_label, role, main FROM profile_stats WHERE discordid = %s",
            (target.id,)
        )
        stats_by_game = {row[0]: row for row in stats_rows}

        total_pages = len(GAME_CHOICES) +1
        pages = [build_home_embed(target, profile_row, total_pages)]
        for i, g in enumerate(GAME_CHOICES, start=2):
            row = stats_by_game.get(g)
            pages.append(build_game_embed(target, g, row, i, total_pages))

        if game is not None:
            start_index = GAME_CHOICES.index(game) +1
        else:
            start_index = 0
        
        paginator = ProfilePaginator(requester_id=ctx.author.id, pages=pages,start_index=start_index)
        message = await ctx.followup.send(embed=pages[start_index], view=paginator)
        paginator.message = message

class ProfilePaginator(discord.ui.View):
    def __init__(self, requester_id, pages, start_index=0):
        super().__init__(timeout=120)
        self.requester_id = requester_id
        self.pages = pages
        self.index = start_index
        self.update_buttons()

    async def interaction_check(self, interaction):
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message(
                "This isnt your profile call to flip through!", ephemeral=True
            )
            return False
        return True

    
    def update_buttons(self):
        self.back.disabled = (self.index == 0)
        self.forward.disabled = (self.index == len(self.pages)-1)
    
    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary)
    async def back(self, button, interaction):
        self.index -= 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.pages[self.index], view=self)

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary)
    async def forward(self, button, interaction):
        self.index += 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.pages[self.index], view=self)
    
    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        await self.message.edit(view=self)

def setup(bot):
    bot.add_cog(Profile(bot))