import discord
import emoji
import re
from discord.ext import commands

from utils import config
from utils import db


GUILD_ID = config.secrets["discord"]["guild_id"]
GAME_CHOICES = list(config.config.get("profile", {}).get("games", {}).keys())
CUSTOM_EMOJI_RE = re.compile(r"^<a?:\w+:\d+>$")

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

def normalize_tag(value):
    if not value:
        return None
    value = emoji.emojize(value.strip(), language="alias").replace("\uFE0F", "")
    if CUSTOM_EMOJI_RE.fullmatch(value):
        return value
    matches = emoji.emoji_list(value)
    if len(matches) == 1 and sum(len(m["emoji"]) for m in matches) == len(value):
        return value
    return None

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

async def picture_autocomplete(ctx: discord.AutocompleteContext):
    return ["Main", "Thumbnail"]

async def primary_autocomplete(ctx: discord.AutocompleteContext):
    game = ctx.options.get("game")
    if not game:
        return []
    rows = await db.fetch_all(
        "SELECT main FROM profile_mains WHERE discordid = %s AND game = %s;",
        (ctx.interaction.user.id, game),
    )
    return [discord.OptionChoice(r[0]) for r in rows]
    

def build_home_embed(target, profile_row, total_pages):
    bio = profile_row[0] if profile_row and profile_row[0] else "No bio set."
    picture_url = profile_row[1] if profile_row and profile_row[1] else None
    thumbnail_url = profile_row[2] if profile_row and profile_row[2] else None
    tag = profile_row[3] if profile_row and profile_row[3] else "💬"

    embed = discord.Embed(
        title=f"{tag} {target.display_name}'s Profile",
        description=bio,
        color=discord.Color.from_rgb(78, 42, 132),
    )
    embed.set_thumbnail(url=thumbnail_url or target.display_avatar.url)
    if picture_url:
        embed.set_image(url=picture_url)
    embed.set_footer(text=f"Page 1/{total_pages}")
    return embed

def build_game_embed(target, game, row, roles, mains, primary_main, tag, page_number, total_pages):
    rank_label = row[1] if row else "Not set"
    wins = row[2] if row else "N/A"
    losses = row[3] if row else "N/A"
    role_display = ", ".join(roles) if roles else "Not set"
    main_display = ", ".join(mains) if mains else "Not set"

    embed = discord.Embed(
        title=f"{tag} {target.display_name} - {game.title()}",
        color=discord.Color.from_rgb(78, 42, 132),
    )
    embed.add_field(name="Rank", value=rank_label, inline=True)
    embed.add_field(name="Role", value=role_display, inline=True)
    embed.add_field(name="Main", value=main_display, inline=True)
    embed.add_field(name="Wins", value=f"{wins}", inline=True)
    embed.add_field(name="Losses", value=f"{losses}", inline=True)

    if primary_main:
        primary_main = (primary_main[0].upper() + primary_main[1:].lower()).replace(" ", "")
        if game == "league":
            embed.set_thumbnail(url=f"https://static.bigbrain.gg/assets/lol/riot_static/16.13.1/img/champion/{primary_main}.webp")
    embed.set_footer(text=f"Page {page_number}/{total_pages}")
    return embed


class Profile(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    profile = discord.SlashCommandGroup("profile", "Profile tools")
    set_grp = profile.create_subgroup("set", "Set something on your profile")

    @set_grp.command(
            name = "bio",
            guild_ids = [GUILD_ID]
    )
    async def bio(
        self,
        ctx,
        bio: discord.Option(
            str,
            name="bio",
            description="About you!"
        )
    ):
        await ctx.defer(ephemeral=True)

        sql = """
            INSERT INTO profiles (discordid, bio, updated_at)
            VALUES (%s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (discordid)
            DO UPDATE SET
                bio = EXCLUDED.bio,
                updated_at = CURRENT_TIMESTAMP;
        """
        await db.perform_one(sql, (ctx.author.id, bio))

        embed = discord.Embed(
            title="Bio Updated",
            description=f"{bio}",
            color=discord.Color.from_rgb(78, 42, 132),
        )
        await ctx.followup.send(embed=embed, ephemeral=True)

    @set_grp.command(
            name = "picture",
            guild_ids = [GUILD_ID]
    )
    async def picture(
        self,
        ctx,
        picture: discord.Option(
            str,
            name="url",
            description="URL to picture to set on your profile",
            default=None
        ),
        option: discord.Option(
            str,
            name="position",
            description="Main or thumbnail",
            autocomplete=picture_autocomplete,
            default="main"
        )
    ):
        await ctx.defer(ephemeral=True)

        if picture and (not picture.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"))):
            await ctx.followup.send("URL must point directly to an image file (.png, .jpg, .gif, .webp, .svg).", ephemeral=True)
            return
        sql = None
        option = option.lower()
        if option == "main":
            sql = """
            INSERT INTO profiles (discordid, picture_url, updated_at)
            VALUES (%s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (discordid)
            DO UPDATE SET
                picture_url = EXCLUDED.picture_url,
                updated_at = CURRENT_TIMESTAMP;
            """
        elif option == "thumbnail":
            sql = """
            INSERT INTO profiles (discordid, thumbnail_url, updated_at)
            VALUES (%s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (discordid)
            DO UPDATE SET
                thumbnail_url = EXCLUDED.thumbnail_url,
                updated_at = CURRENT_TIMESTAMP;
            """

        await db.perform_one(sql, (ctx.author.id, picture))

        embed = discord.Embed(
            title="Picture updated",
            color=discord.Color.from_rgb(78, 42, 132)
        )
        embed.set_image(url=picture)
        try:
            await ctx.followup.send(embed=embed, ephemeral=True)
        except discord.HTTPException:
            await ctx.followup.send("Picture saved, but but Discord couldn't render that image — double check the link works in a browser.", ephemeral=True)

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
        )
    ):
        await ctx.defer(ephemeral=True)

        rows = await db.fetch_all(
            "SELECT role FROM profile_roles WHERE discordid = %s AND game = %s;",
            (ctx.author.id , game),
        )

        current_roles = [r[0] for r in rows]

        view = RoleSelectView(requester_id=ctx.author.id, game=game, current_roles=current_roles)
        await ctx.followup.send("Pick your role(s):", view=view, ephemeral=True)

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
    ):
        rows = await db.fetch_all(
            "SELECT main FROM profile_mains WHERE discordid = %s AND game = %s;",
            (ctx.author.id, game),
        )
        current_mains = [r[0] for r in rows]
        await ctx.send_modal(MainsModal(requester_id=ctx.author.id, game=game, current_mains=current_mains))

    @set_grp.command(
            name = "primary",
            guild_ids = [GUILD_ID]
    )
    async def primary(
        self,
        ctx,
        game: discord.Option(
            str,
            name="game",
            description="Game to change something about",
            choices=GAME_CHOICES,
        ),
        primary: discord.Option(
            str,
            name="primary",
            description="Used for the little picture on your profile",
            autocomplete=primary_autocomplete
        )
    ):
        await ctx.defer(ephemeral=True)

        mains = get_mains(game)

        if primary not in mains:
            await ctx.followup.send(f"{primary} not in your list of mains, {' ,'.join(mains[:-1])} and {mains[-1]}.")

        sql = """
            INSERT INTO profile_primary_mains (discordid, game, prime)
            VALUES (%s, %s, %s)
            ON CONFLICT (discordid, game)
            DO UPDATE SET
                prime = EXCLUDED.prime
            """

        await db.perform_one(sql, (ctx.author.id, game, primary))

        embed = discord.Embed(
            title="Primary updated",
            color=discord.Color.from_rgb(78, 42, 132)
        )

        primary = primary[0].upper() + primary[1:].lower()
        if game == "league":
            embed.set_image(url=f"https://ddragon.leagueoflegends.com/cdn/img/champion/splash/{primary}_0.jpg")
        await ctx.followup.send(embed=embed, ephemeral=True)

    @set_grp.command(
            name = "tag",
            guild_ids = [GUILD_ID]
    )
    async def tag(
        self,
        ctx,
        tag: discord.Option(
            str,
            name="tag",
            description="Emoji tag to identify yourself by!",
            default=None
        )
    ):
        await ctx.defer(ephemeral=True)

        if tag is not None:
            normalized = normalize_tag(tag)
            if normalized is None:
                await ctx.followup.send("That's not a valid emoji :<", ephemeral=True)
                return
            tag = normalized

        sql = """
            INSERT INTO profiles (discordid, tag, updated_at)
            VALUES (%s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (discordid)
            DO UPDATE SET
                tag = EXCLUDED.tag,
                updated_at = CURRENT_TIMESTAMP;
        """
        await db.perform_one(sql, (ctx.author.id, tag))

        embed = discord.Embed(
            title="Tag Updated!",
            description=f"New tag: {tag}" if tag else "New Tag: Default",
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
            "SELECT bio, picture_url, thumbnail_url, tag FROM profiles WHERE discordid = %s;",
            (target.id,)
        )
        stats_rows = await db.fetch_all(
            "SELECT game, rank_label, wins, losses FROM profile_stats WHERE discordid = %s",
            (target.id,)
        )
        role_rows = await db.fetch_all(
            "SELECT game, role FROM profile_roles WHERE discordid = %s;",
            (target.id,)
        )
        main_rows = await db.fetch_all(
            "SELECT game, main FROM profile_mains WHERE discordid = %s;",
            (target.id,)
        )
        primary_rows = await db.fetch_all(
            "SELECT game, prime FROM profile_primary_mains WHERE discordid = %s;",
            (target.id,)
        )

        stats_by_game = {row[0]: row for row in stats_rows}
        roles_by_game = {}
        for g, r in role_rows:
            roles_by_game.setdefault(g, []).append(r)
        mains_by_game = {}
        for g, m in main_rows:
            mains_by_game.setdefault(g, []).append(m)
        primary_by_game = {g: p for g, p in primary_rows}

        total_pages = len(GAME_CHOICES) +1
        pages = [build_home_embed(target, profile_row, total_pages)]
        for i, g in enumerate(GAME_CHOICES, start=2):
            row = stats_by_game.get(g)
            roles = roles_by_game.get(g, [])
            mains = mains_by_game.get(g, [])
            primary_main = primary_by_game.get(g)
            tag = profile_row[3] if profile_row and profile_row[3] else "💬"
            pages.append(build_game_embed(target, g, row, roles, mains, primary_main, tag, i, total_pages))

        if game is not None:
            start_index = GAME_CHOICES.index(game) +1
        else:
            start_index = 0
        
        paginator = ProfilePaginator(requester_id=ctx.author.id, pages=pages,start_index=start_index)
        message = await ctx.followup.send(embed=pages[start_index], view=paginator)
        paginator.message = message
        await message.edit(embed=pages[start_index], view=paginator)

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

class RoleSelectView(discord.ui.View):
    def __init__(self, requester_id, game, current_roles):
        super().__init__(timeout=120)
        self.requester_id = requester_id
        self.game = game

        options = [
            discord.SelectOption(label=r, value=r, default=(r in current_roles))
            for r in get_roles(game)
        ]
        self.select = discord.ui.Select(
            placeholder="Choose your role(s)",
            min_values=0,
            max_values=len(options),
            options=options
        )
        self.select.callback = self.on_select
        self.add_item(self.select)
    
    async def interaction_check(self, interaction):
        return interaction.user.id == self.requester_id
    
    async def on_select(self, interaction):
        chosen = self.select.values

        await db.perform_one(
            "DELETE FROM profile_roles WHERE discordid = %s AND game = %s;",
            (self.requester_id, self.game)
        )
        if chosen:
            await db.perform_many(
                "INSERT INTO profile_roles (discordid, game, role) VALUES (%s, %s, %s);",
                [(self.requester_id, self.game, r) for r in chosen],
            )
        
        await interaction.response.edit_message(
            content=f"Roles updated: {', '.join(chosen) if chosen else 'None'}",
            view=None,
        )

class MainsModal(discord.ui.Modal):
    def __init__(self, requester_id, game, current_mains):
        super().__init__(title=f"Set your {game.title()} mains")
        self.requester_id = requester_id
        self.game = game
        self.add_item(
            discord.ui.InputText(
                label="Mains (comma-seperated)",
                placeholder="e.g. Lux, Kayn, Locke",
                value=", ".join(current_mains),
                required=False
            )
        )

    async def callback(self, interaction: discord.Interaction):
        raw = self.children[0].value or ""
        candidates = [c.strip() for c in raw.split(",") if c.strip]

        lookup = {m.lower(): m for m in get_mains(self.game)}
        resolved, invalid = [], []
        for c in candidates:
            match = lookup.get(c.lower())
            (resolved if match else invalid).append(match or c)

        if invalid:
            await interaction.response.send_message(
                f"Didn't recognize \"{', '.join(invalid)}. Nothing was saved, double check and try again",
                ephemeral=True
            )
            return
        
        await db.perform_one(
            "DELETE FROM profile_mains WHERE discordid = %s AND game = %s;",
            (self.requester_id, self.game),
        )
        if resolved:
            await db.perform_many(
                "INSERT INTO profile_mains (discordid, game, main) VALUES (%s, %s, %s);",
                [(self.requester_id, self.game, m) for m in resolved]
            )
        if len(resolved) == 1:
            await interaction.response.send_message(
                f"Main updated to {resolved}.",
                ephemeral=True
            )
            return
        
        await interaction.response.send_message(
            f"Mains updated to {', '.join(resolved[:-1])} and {resolved[-1]}.",
            ephemeral=True
        )

def setup(bot):
    bot.add_cog(Profile(bot))