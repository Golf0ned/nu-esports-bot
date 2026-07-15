import discord
import random
from discord.ext import commands

from utils import config
from utils import db


GUILD_ID = config.secrets["discord"]["guild_id"]
GAME_CHOICES = list(config.config.get("profile", {}).get("games", {}).keys())
DEFAULT_TAG = "🖱️"
TEAM_NAMES = [tuple(pair) for pair in config.config["matchmaking"]["team_names"]]
LEAGUE_LANES = [r for r in config.config["profile"]["games"]["league"]["roles"] if r != "Flex"]
RANK_JITTER = 2 # determines randomness in shuffling


def generate_embed(session):
    if session.role_assignments:
        return generate_results_embed(session)
    embed = discord.Embed(
        title=f"{session.game.title()} Lobby",
        description=f"({len(session.joined)}/10)",
        color = discord.Color.from_rgb(78,42,132),
    )
    left_rows = ["-"] * 5
    right_rows = ["-"] * 5
    for i, member in enumerate(session.joined):
        tag = session.tags.get(member.id, DEFAULT_TAG)
        entry = f"{tag} {member.display_name}"
        row = i // 2
        if i % 2 == 0:
            left_rows[row] = entry
        else:
            right_rows[row] = entry
    embed.add_field(name=f"{session.team_names[0]}", value="\n".join(left_rows), inline=True)
    embed.add_field(name=f"{session.team_names[1]}", value="\n".join(right_rows), inline=True)
    return embed

def generate_results_embed(session):
    embed = discord.Embed(
        title=f"{session.game.title()} Lobby — Teams",
        color=discord.Color.from_rgb(78, 42, 132),
    )
    lane_order = {lane: i for i, lane in enumerate(LEAGUE_LANES)}
    def team_rows(team):
        ordered = sorted(
            team,
            key=lambda m: lane_order.get(session.role_assignments.get(m.id, ""), 99),
        )
        rows = []
        for member in ordered:
            tag = session.tags.get(member.id, DEFAULT_TAG)
            lane = session.role_assignments.get(member.id, "?")
            rows.append(f"**{lane}** — {tag} {member.display_name}")
        return "\n".join(rows) if rows else "-"
    embed.add_field(name=session.team_names[0], value=team_rows(session.team_a), inline=True)
    embed.add_field(name=session.team_names[1], value=team_rows(session.team_b), inline=True)
    return embed


async def get_league_shuffle_data(joined):
    ids = [m.id for m in joined]

    rank_rows = await db.fetch_all(
        "SELECT discordid, rank_value FROM profile_stats WHERE discordid = ANY(%s) AND game = 'league';",
        (ids,),
    )
    rank_by_id = {discordid: rank_value for discordid, rank_value in rank_rows if rank_rows is not None}

    role_rows = await db.fetch_all(
        "SELECT discordid, role FROM profile_roles WHERE discordid = ANY(%s) AND game = 'league';",
        (ids,),
    )
    roles_by_id = {}
    for discordid, role in role_rows:
        roles_by_id.setdefault(discordid, []).append(role)

    known_ranks = list(rank_by_id.values())
    average_rank = sum(known_ranks) / len(known_ranks) if known_ranks else 0

    for member in joined:
        rank_by_id.setdefault(member.id, average_rank)
        roles_by_id.setdefault(member.id, ["Flex"])
    
    return rank_by_id, roles_by_id

def balance_league_teams(joined, rank_by_id, roles_by_id):
    lanes = LEAGUE_LANES.copy()
    random.shuffle(lanes)
    lanes = lanes[: len(joined) // 2] #AA

    effective_rank = {
        m.id: rank_by_id[m.id] + random.uniform(-RANK_JITTER, RANK_JITTER)
        for m in joined
    }

    remaining = list(joined)
    team_a, team_b = [], []
    team_a_total, team_b_total = 0, 0
    assignments = {}

    for lane in lanes:
        lane_pool = [m for m in remaining if lane in roles_by_id[m.id]]
        lane_pool_ids = {m.id for m in lane_pool}
        flex_pool = [m for m in remaining if "Flex" in roles_by_id[m.id] and m.id not in lane_pool_ids]

        candidates = lane_pool
        if len(candidates) < 2:
            candidate_ids = {m.id for m in candidates}
            needed = 2 - len(candidates)
            candidates += [m for m in flex_pool if m.id not in candidate_ids][:needed]
        if len(candidates) < 2:
            candidate_ids = {m.id for m in candidates}
            needed = 2 - len(candidates)
            candidates += [m for m in remaining if m.id not in candidate_ids][:needed]

        candidates = sorted(candidates, key=lambda m: effective_rank[m.id], reverse=True)[:2]
        first, second = candidates[0], candidates[1]

        if team_a_total <= team_b_total:
            team_a.append(first)
            team_b.append(second)
            team_a_total += effective_rank[first.id]
            team_b_total += effective_rank[second.id]
        else:
            team_b.append(first)
            team_a.append(second)
            team_b_total += effective_rank[first.id]
            team_a_total += effective_rank[second.id]

        assignments[first.id] = lane
        assignments[second.id] = lane
        remaining = [m for m in remaining if m.id not in (first.id, second.id)]

    return team_a, team_b, assignments

def has_privilege(session, interaction):
    if (any("game head" in role.name.lower() for role in interaction.user.roles) or interaction.user.id == session.owner.id):
        return True
    return False

async def refresh_admin_panels(session):
    still_open = {}
    for user_id, msg in session.admin_panels.items():
        try:
            await msg.edit(embed=generate_embed(session), view=AdminView(session))
            still_open[user_id] = msg
        except (discord.NotFound, discord.HTTPException):
            pass
    session.admin_panels = still_open

def swap_slots(session, id_a, id_b):
    member_a = next((m for m in session.team_a + session.team_b if m.id == id_a), None)
    member_b = next((m for m in session.team_a + session.team_b if m.id == id_b), None)
    if member_a is None or member_b is None:
        return False
    
    a_on_team_a = member_a in session.team_a
    b_on_team_a = member_b in session.team_a

    if a_on_team_a != b_on_team_a:
        if a_on_team_a:
            session.team_a.remove(member_a)
            session.team_b.remove(member_b)
            session.team_b.append(member_a)
            session.team_a.append(member_b)
        else:
            session.team_b.remove(member_a)
            session.team_a.remove(member_b)
            session.team_a.append(member_a)
            session.team_b.append(member_b)
    
    lane_a = session.role_assignments.get(member_a.id)
    lane_b = session.role_assignments.get(member_b.id)
    session.role_assignments[member_a.id] = lane_b
    session.role_assignments[member_b.id] = lane_a

    return True

class MatchmakingSession:
    def __init__(self, game):
        self.game = game
        self.joined: list[discord.Member] = []
        self.tags: dict[int, str] = {} #member.id to tag
        self.team_a: list[discord.Member] = []
        self.team_b: list[discord.Member] = []
        self.team_names: tuple[(str, str)] = random.choice(TEAM_NAMES)
        self.role_assignments: dict[int, str] = {} #member.id to role
        self.message: discord.Message | None = None
        self.admin_panels: dict[discord.Member, discord.InteractionMessage] = {}
        self.owner: discord.Member | None = None

class Matchmaking(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active_sessions: dict[tuple[int, str], MatchmakingSession] = {}

    matchmaking_group = discord.SlashCommandGroup("matchmaking", "matchmaking tools")

    @matchmaking_group.command(name="start", guild_ids=[GUILD_ID])
    async def start(
        self,
        ctx,
        game: discord.Option(
            str,
            description="Game to matchmake for",
            choices=GAME_CHOICES
        ),
        teamOne: discord.Option(
            str,
            name="team_one",
            description="Team one's name",
            default=None
        ),
        teamTwo: discord.Option(
            str,
            name="team_two",
            description="Team two's name",
            default=None
        ),
    ):
        await ctx.defer()

        key = (ctx.channel.id, game)

        if key in self.active_sessions:
            session = self.active_sessions[key]
            if session.message is not None:
                try:
                    await session.message.delete()
                except discord.NotFound:
                    pass
        else:
            session = MatchmakingSession(game)
            self.active_sessions[key] = session

        if teamOne:
            session.team_names = (teamOne, session.team_names[1])
        if teamTwo:
            session.team_names = (session.team_names[0], teamTwo)

        view = LobbyView(session)
        embed = generate_embed(session)
        message = await ctx.followup.send(embed=embed, view=view)
        session.message = message
        if session.owner is None:
            session.owner = ctx.author 

class LobbyView(discord.ui.View):
    def __init__(self, session):
        super().__init__(timeout=None)
        self.session = session

    @discord.ui.button(label="Join", style=discord.ButtonStyle.success)
    async def join(self, button, interaction):
        if any(m.id == interaction.user.id for m in self.session.joined):
            await interaction.response.send_message("You've already joined!", ephemeral=True)
            return
        if len(self.session.joined) >= 10:
            await interaction.response.send_message("Lobby already full... :/", ephemeral=True)
            return
        
        row = await db.fetch_one("SELECT tag FROM profiles WHERE discordid = %s;", (interaction.user.id,))
        self.session.tags[interaction.user.id] = row[0] if row and row[0] else DEFAULT_TAG

        self.session.joined.append(interaction.user)
        self.session.team_a = []
        self.session.team_b = []
        self.session.role_assignments = {}
        await interaction.response.edit_message(embed=generate_embed(self.session), view=self)
        await refresh_admin_panels(self.session)


    @discord.ui.button(label="Leave", style=discord.ButtonStyle.danger)
    async def leave(self, button, interaction):
        if not any(m.id == interaction.user.id for m in self.session.joined):
            await interaction.response.send_message("You haven't joined this lobby!", ephemeral=True)
            return

        self.session.joined = [m for m in self.session.joined if m.id != interaction.user.id]
        self.session.tags.pop(interaction.user.id, None)
        self.session.team_a = []
        self.session.team_b = []
        self.session.role_assignments = {}
        await interaction.response.edit_message(embed=generate_embed(self.session), view=self)
        await refresh_admin_panels(self.session)

    @discord.ui.button(label="Settings", style=discord.ButtonStyle.primary)
    async def settings(self, button, interaction):

        if not has_privilege(self.session, interaction):
            await interaction.response.send_message("You're not a game head! Feel free to apply though...", ephemeral=True)
            return
        
        old_panel = self.session.admin_panels.get(interaction.user.id)
        if old_panel is not None:
            try:
                await old_panel.delete()
            except (discord.NotFound, discord.HTTPException):
                pass

        await interaction.response.send_message(embed=generate_embed(self.session), view=AdminView(self.session), ephemeral=True)
        panel_message = await interaction.original_response()
        self.session.admin_panels[interaction.user.id] = panel_message

class SwapSelectView(discord.ui.View):
    def __init__(self, session):
        super().__init__(timeout=180)
        self.session = session

        options = []
        for member in session.team_a + session.team_b:
            lane = session.role_assignments.get(member.id, "?")
            team = session.team_names[0] if member in session.team_a else session.team_names[1]
            options.append(discord.SelectOption(label=f"{member.display_name} ({lane})", description=team, value=str(member.id)))

        self.select = discord.ui.Select(placeholder="Pick two players to swap.", min_values=2, max_values=2, options=options)
        self.select.callback = self.on_select
        self.add_item(self.select)

    async def on_select(self, interaction):
        id_a, id_b = [int(v) for v in self.select.values]
        swap_slots(self.session, id_a, id_b)

        await self.session.message.edit(embed=generate_embed(self.session), view=LobbyView(self.session))
        await interaction.response.edit_message(embed=generate_embed(self.session), view=AdminView(self.session))
        await refresh_admin_panels(self.session)

class WinnerSelectView(discord.ui.View):
    def __init__(self, session):
        super().__init__(timeout=180)
        self.session = session

    @discord.ui.button(label="Team One", style=discord.ButtonStyle.primary)
    async def team_one(self, button, interaction):
        if not has_privilege(self.session, interaction):
            await interaction.response.send_message("You're not a game head! Feel free to apply though...", ephemeral=True)
            return
        return NotImplementedError
    
    @discord.ui.button(label="Team Two", style=discord.ButtonStyle.primary)
    async def team_two(self, button, interaction):
        if not has_privilege(self.session, interaction):
            await interaction.response.send_message("You're not a game head! Feel free to apply though...", ephemeral=True)
            return
        return NotImplementedError
    
    @discord.ui.button(label="Back", style=discord.ButtonStyle.success)
    async def back(self, button, interaction):
        if not has_privilege(self.session, interaction):
            await interaction.response.send_message("You're not a game head! Feel free to apply though...", ephemeral=True)
            return
        await interaction.response.edit_message(embed=generate_embed(self.session), view=AdminView(self.session))

class AdminView(discord.ui.View):
    def __init__(self, session):
        super().__init__(timeout=180)
        self.session = session

    @discord.ui.button(label="Shuffle", style=discord.ButtonStyle.primary)
    async def shuffle(self, button, interaction):
        if (len(self.session.joined) % 2) != 0:
            await interaction.response.send_message("You need an even amount of players to shuffle!", ephemeral=True)
            return

        if not has_privilege(self.session, interaction):
            await interaction.response.send_message("You're not a game head! Feel free to apply though...", ephemeral=True)
            return

        if self.session.game == "league":
            rank_by_id, roles_by_id = await get_league_shuffle_data(self.session.joined)
            team_a, team_b, assignments = balance_league_teams(self.session.joined, rank_by_id, roles_by_id)
            self.session.team_a = team_a
            self.session.team_b = team_b
            self.session.role_assignments = assignments
            await self.session.message.edit(embed=generate_embed(self.session), view=LobbyView(self.session))
            await interaction.response.edit_message(embed=generate_embed(self.session), view=self)
            await refresh_admin_panels(self.session)
        else:
            await interaction.response.send_message("Val TBD", ephemeral=True)

    @discord.ui.button(label="Swap", style=discord.ButtonStyle.secondary)
    async def swap(self, button, interaction):
        if not has_privilege(self.session, interaction):
            await interaction.response.send_message("You're not a game head! Feel free to apply though...", ephemeral=True)
            return
        if not self.session.role_assignments:
            await interaction.response.send_message("Shuffle first before trying to swap!", ephemeral=True)
            return
        
        await interaction.response.edit_message(embed=generate_embed(self.session), view=SwapSelectView(self.session))
    
    @discord.ui.button(label="Winner", style=discord.ButtonStyle.success)
    async def winner(self, button, interaction):
        if not has_privilege(self.session, interaction):
            await interaction.response.send_message("Youre not a game head! Feel free to apply though...", ephemeral=True)
            return
        if not self.session.role_assignments:
            await interaction.response.send_message("Shuffle first before deciding a winner!", ephemeral=True)
            return
        
        await interaction.response.edit_message(embed=generate_embed(self.session), view=WinnerSelectView(self.session))

def setup(bot):
    bot.add_cog(Matchmaking(bot))