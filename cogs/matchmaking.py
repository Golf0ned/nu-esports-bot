import discord
import random
from discord.ext import commands

from utils import config
from utils import db
from utils import elo


GUILD_ID = config.secrets["discord"]["guild_id"]
GAME_CHOICES = list(config.game_data.keys())
DEFAULT_TAG = {"Lobby": "🖱️", "Winner": "🏆"}
TEAM_NAMES = [tuple(pair) for pair in config.matchmaking_data["team_names"]]
ROLE_REQUIREMENTS = {game: data.get("role_requirements", {}) for game, data in config.game_data.items()}
RANK_JITTER = 200        # half-width of the jitter range for a player exactly at the lobby average
JITTER_PULL_SCALE = 1500 # elo deviation from average that fully saturates the pull toward one side


def generate_embed(session: "MatchmakingSession") -> discord.Embed:
    """Builds the embed for a lobby.
    
    Shows the waiting-room roster (two columns of joined players) if no shuffle has happened yet, 
    or the shuffled team layout if it has
    """
    if session.role_assignments:
        return generate_match_embed(session)
    embed = discord.Embed(
        title=f"{session.game.title()} Lobby",
        description=f"({len(session.joined)}/10)",
        color = discord.Color.from_rgb(78,42,132),
    )
    left_rows = ["-"] * 5
    right_rows = ["-"] * 5
    for i, member in enumerate(session.joined):
        tag = session.tags.get(member.id, DEFAULT_TAG.get("Lobby"))
        entry = f"{tag} {member.display_name}"
        row = i // 2
        if i % 2 == 0:
            left_rows[row] = entry
        else:
            right_rows[row] = entry
    embed.add_field(name=f"{session.team_names[0]}", value="\n".join(left_rows), inline=True)
    embed.add_field(name=f"{session.team_names[1]}", value="\n".join(right_rows), inline=True)
    return embed

def generate_postgame_embed(session: "MatchmakingSession", team: str, players: list[discord.Member]) -> discord.Embed:
    """Build the "X team wins" embed after a winner is declared.

    team: the winning team's display name (not team_a/team_b, the actual name string).
    players: list of players on the winning team.
    """
    embed = discord.Embed(
        title = f"{team} Win!",
        color = discord.Color.from_rgb(78,42,132)
    )
    rows = []
    for i, member in enumerate(players):
        tag = session.tags.get(member.id, DEFAULT_TAG.get("Winner"))
        entry = f"{tag} {member.display_name}"
        rows.append(entry)

    embed.add_field(name="Players", value="\n".join(rows), inline=True)
    return embed

def generate_cancelled_embed(session: "MatchmakingSession") -> discord.Embed:
    """Build the "lobby cancelled" embed shown after an admin cancels a game."""
    return discord.Embed(
        title=f"{session.game.title()} Lobby — Cancelled",
        description="This lobby was cancelled by a game head.",
        color=discord.Color.from_rgb(78, 42, 132),
    )

def generate_match_embed(session: "MatchmakingSession") -> discord.Embed:
    """Build the embed for a lobby that's already been shuffled into teams.
    
    Players are grouped by team and ordered by role (via ROLE_REQUIREMENTS), not join order.
    """
    embed = discord.Embed(
        title=f"{session.game.title()} Lobby — Teams",
        color=discord.Color.from_rgb(78, 42, 132),
    )
    lane_order = {lane: i for i, lane in enumerate(ROLE_REQUIREMENTS[session.game])}
    def team_rows(team):
        ordered = sorted(
            team,
            key=lambda m: lane_order.get(session.role_assignments.get(m.id, ""), 99),
        )
        rows = []
        for member in ordered:
            tag = session.tags.get(member.id, DEFAULT_TAG.get("Lobby"))
            lane = session.role_assignments.get(member.id, "?")
            rows.append(f"**{lane}** — {tag} {member.display_name}")
        return "\n".join(rows) if rows else "-"
    embed.add_field(name=session.team_names[0], value=team_rows(session.team_a), inline=True)
    embed.add_field(name=session.team_names[1], value=team_rows(session.team_b), inline=True)
    return embed


async def get_game_shuffle_data(joined: list[discord.Member], game: str) -> tuple[
                                                                                dict[int, float], 
                                                                                dict[int, list[str]]
                                                                                ]:
    """Fetch each joined player's rank and roles for a game, filling in defaults for missing data.
    
    Players with no rank on file get the average rank of everyone who does (or 0 if nobody is set). Players with no role default to ["Flex"]
    
    Returns (rank_by_id, roles_by_id), both keyed by discord member id.
    """
    elo_by_id = await get_team_elos(game, joined)

    ids = [m.id for m in joined]
    role_rows = await db.fetch_all(
        "SELECT discordid, role FROM profile_roles WHERE discordid = ANY(%s) AND game = %s;",
        (ids, game),
    )
    roles_by_id = {}
    for discordid, role in role_rows:
        roles_by_id.setdefault(discordid, []).append(role)

    for member in joined:
        roles_by_id.setdefault(member.id, ["Flex"])

    return elo_by_id, roles_by_id

def balance_teams(game: str, 
                  joined: list[discord.Member], 
                  elo_by_id: dict[int, float], 
                  roles_by_id: dict[int, list[str]]
                  ) -> tuple[
                            list[discord.Member],
                            list[discord.Member],
                            dict[int, str]
                            ]:
    """Split joined players into two balanced teams
    
    Process each required role (in random order, so repeated shuffles vary) and greedily assign the needed number of players per team,
    preferring players who actually have that role, falling back to "Flex", then anyone left. Within roles, players are handed to teams
    with fewer members (tied broken by lower total rank), which matters because effective_rank can go negative when nobody has a rank set.
    
    A small random "jitter" `RANK_JITTER` is added to each player's rank before comparing, so the lobby doesn't shuffle to the same result every time.
    
    Returns (team_a, team_b, assignments), where assignments maps member id ->  lane/role.
    """
    requirements = list(ROLE_REQUIREMENTS[game].items())
    random.shuffle(requirements)

    slots_per_team= len(joined) // 2
    selected = []
    used = 0
    for role, count in requirements:
        if used + count <= slots_per_team:
            selected.append((role, count))
            used += count

    avg_elo = sum(elo_by_id[m.id] for m in joined) / len(joined)
    effective_elo = {
        m.id: jittered_elo(elo_by_id[m.id], avg_elo)
        for m in joined
    }

    remaining = list(joined)
    team_a, team_b = [], []
    team_a_total, team_b_total = 0, 0
    assignments = {}

    for role, count in selected:
        needed_total = count * 2
        role_pool = [m for m in remaining if role in roles_by_id[m.id]]
        role_pool_ids = {m.id for m in role_pool}
        flex_pool = [m for m in remaining if "Flex" in roles_by_id[m.id] and m.id not in role_pool_ids]

        candidates = role_pool
        if len(candidates) < needed_total:
            candidate_ids = {m.id for m in candidates}
            needed = needed_total - len(candidates)
            candidates += [m for m in flex_pool if m.id not in candidate_ids][:needed]
        if len(candidates) < needed_total:
            candidate_ids = {m.id for m in candidates}
            needed = needed_total - len(candidates)
            candidates += [m for m in remaining if m.id not in candidate_ids][:needed]

        candidates = sorted(candidates, key=lambda m: effective_elo[m.id], reverse=True)[:needed_total]
        
        for m in candidates:
            if len(team_a) < len(team_b) or (len(team_a) == len(team_b) and team_a_total <= team_b_total):
                team_a.append(m)
                team_a_total += effective_elo[m.id]
            else:
                team_b.append(m)
                team_b_total += effective_elo[m.id]
            assignments[m.id] = role

        chosen_ids = {m.id for m in candidates}
        remaining = [m for m in remaining if m.id not in chosen_ids]

    remaining_sorted = sorted(remaining, key=lambda m: effective_elo[m.id], reverse=True)
    for m in remaining_sorted:
        if len(team_a) < len(team_b) or (len(team_a) == len(team_b) and team_a_total <= team_b_total):
            team_a.append(m)
            team_a_total += effective_elo[m.id]

        else:
            team_b.append(m)
            team_b_total += effective_elo[m.id]
        assignments[m.id] = roles_by_id[m.id][0]

    return team_a, team_b, assignments

def has_privilege(session: "MatchmakingSession", interaction: discord.Interaction) -> bool:
    """Check wether whoever clicked a button is allowed to use admin controls.
    
    True if they have a role with "game head" in its name (case-insensitive, substring match), 
    or if they're the person who started the lobby."""
    if (interaction.user.guild_permissions.administrator or
        any("game head" in role.name.lower() for role in interaction.user.roles) 
        or interaction.user.id == session.owner.id):
        return True
    return False

async def refresh_admin_panels(session: "MatchmakingSession") -> None:
    """Re-render every currently-open admin panel so they reflect the latest lobby state.
    
    Panels that have been dismissed/deleted are dropped instead of retried"""
    still_open = {}
    for user_id, msg in session.admin_panels.items():
        try:
            await msg.edit(embed=generate_embed(session), view=AdminView(session))
            still_open[user_id] = msg
        except (discord.NotFound, discord.HTTPException):
            pass
    session.admin_panels = still_open

def swap_slots(session: "MatchmakingSession", id_a: int, id_b: int) -> bool:
    """Swap two players' team+lane slots.

    If they're on different teams, both their team assignment and lane swap.
    If they're on the same team, only their lanes swap (team stays the same).

    Returns False (and does nothing) if either id isn't currently on team_a/team_b
    """
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

def jittered_elo(player_elo: float, avg_elo: float, half_width: float = RANK_JITTER, pull_scale: float = JITTER_PULL_SCALE) -> float:
    """Add a random jitter to a player's elo, biased to pull them toward the lobby average.
    
    The jitter's total width stays constant, but its center slides based on how far below/above
    average the player is: someone well below average gets a jitter that's entirely upside (never
    randomly pushed even lower), someone well above average gets one that's entirely downside, and
    someone right at the average gets the old symmetric +/- jitter, unbiased either way.
    """
    deviation = avg_elo - player_elo
    pull = max(-1.0, min(1.0, deviation / pull_scale))
    center = pull * half_width
    return player_elo + random.uniform(center - half_width, center + half_width)

async def update_record(session: "MatchmakingSession", winners: list[discord.Member], losers: list[discord.Member]) -> None:
    """Record a win for each player in `winners` and a loss for each player in `losers`
    in profile_stats, for the current session's game."""

    sqlWin = '''
            INSERT INTO profile_stats (discordid, game, wins)
            VALUES (%s, %s, 1)
            ON CONFLICT (discordid, game) DO UPDATE SET wins = profile_stats.wins + 1;
        '''
    sqlLose = '''
            INSERT INTO profile_stats (discordid, game, losses)
            VALUES (%s, %s, 1)
            ON CONFLICT (discordid, game) DO UPDATE SET losses = profile_stats.losses + 1;
    '''
    await db.perform_many(sqlWin, [(w.id, session.game) for w in winners],)
    await db.perform_many(sqlLose, [(m.id, session.game) for m in losers],)

async def get_team_elos(game: str, members: list[discord.Member]) -> dict[int, float]:
    """Fetch each player's current elo for a game, seeding+persisting a fresh row
    from their rank if they don't have one yet."""
    ids = [m.id for m in members]
    
    elo_rows = await db.fetch_all(
        "SELECT discordid, elo FROM profile_elo WHERE discordid = ANY(%s) AND game = %s;",
        (ids, game),
    )
    elo_by_id = {discordid: float(value) for discordid, value in elo_rows}
    
    missing = [m.id for m in members if m.id not in elo_by_id]
    if missing:
        rank_rows = await db.fetch_all(
            "SELECT discordid, rank_value FROM profile_stats WHERE discordid = ANY(%s) AND game = %s;",
            (missing, game),
        )
        rank_by_id = {discordid: rank_value for discordid, rank_value in rank_rows}

        seeded = []
        for discordid in missing:
            value = elo.seed_elo(game, rank_by_id.get(discordid))
            elo_by_id[discordid] = value
            seeded.append((discordid, game, value))

        await db.perform_many(
            """
            INSERT INTO profile_elo (discordid, game, elo)
            VALUES (%s, %s, %s)
            ON CONFLICT (discordid, game) DO NOTHING
            """,
            seeded,
        )

    return elo_by_id

async def apply_elo_changes(session: 'MatchmakingSession', team_a_won: bool) -> None:
    """Update profile_elo for every player in the match based on the declared winner."""
    team_a_elo = await get_team_elos(session.game, session.team_a)
    team_b_elo = await get_team_elos(session.game, session.team_b)

    deltas = elo.compute_elo_deltas(team_a_elo, team_b_elo, team_a_won)

    await db.perform_many(
        """
        UPDATE profile_elo
        SET elo = elo + %s, games_played = games_played + 1, updated_at = CURRENT_TIMESTAMP
        WHERE discordid = %s AND game = %s;
        """,
        [(delta, discordid, session.game) for discordid, delta in deltas.items()],
    )

class MatchmakingSession:
    """Tracks the state of one matchmaking lobby for one (channel, game) pair."""

    def __init__(self, game):
        self.game: str = game
        self.joined: list[discord.Member] = []
        self.tags: dict[int, str] = {} #member.id to tag
        self.team_a: list[discord.Member] = []
        self.team_b: list[discord.Member] = []
        self.team_names: tuple[(str, str)] = random.choice(TEAM_NAMES)
        self.role_assignments: dict[int, str] = {} #member.id to role
        self.message: discord.Message | None = None
        self.admin_panels: dict[int, discord.InteractionMessage] = {}
        self.owner: discord.Member | None = None
        self.key: tuple[int, str] | None = None

class Matchmaking(commands.Cog):
    """Cog housing the /matchmaking command group and the active lobby state for all channels."""

    def __init__(self, bot):
        self.bot: discord.Bot = bot
        self.active_sessions: dict[tuple[int, str], MatchmakingSession] = {}

    matchmaking_group = discord.SlashCommandGroup("matchmaking", "matchmaking tools")

    @matchmaking_group.command(name="start", guild_ids=[GUILD_ID])
    async def start(
        self,
        ctx: discord.ApplicationContext,
        game: discord.Option(
            str,
            description="Game to matchmake for",
            choices=GAME_CHOICES
        ),
        team_a: discord.Option(
            str,
            description="Team A's name",
            default=None
        ),
        team_b: discord.Option(
            str,
            description="Team B's name",
            default=None
        ),
    ) -> None:
        """Start a new matchmaking lobby, or bump an existing one in this channel/game.
        
        Bumping doesn't reset the lobby, just moves it to the bottom of the channel.
        """
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

        session.key = key

        if team_a:
            session.team_names = (team_a, session.team_names[1])
        if team_b:
            session.team_names = (session.team_names[0], team_b)

        view = LobbyView(session)
        embed = generate_embed(session)
        message = await ctx.followup.send(embed=embed, view=view)
        session.message = message
        if session.owner is None:
            session.owner = ctx.author 

        await message.edit(embed=embed, view=view)

class LobbyView(discord.ui.View):
    """Shared, persistent view on the public lobby message: Join / Leave / Settings."""

    def __init__(self, session):
        super().__init__(timeout=None)
        self.session = session
        self.join.disabled = len(session.joined) >= 10

    @discord.ui.button(label="Join", style=discord.ButtonStyle.success)
    async def join(self, button: discord.ui.Button, interaction: discord.Interaction) -> None:
        """Add whoever clicked to the lobby, unless they've already joined or it's full."""
        if any(m.id == interaction.user.id for m in self.session.joined):
            await interaction.response.send_message("You've already joined!", ephemeral=True)
            return
        if len(self.session.joined) >= 10:
            await interaction.response.send_message("Lobby already full... :/", ephemeral=True)
            return
        
        row = await db.fetch_one("SELECT tag FROM profiles WHERE discordid = %s;", (interaction.user.id,))
        self.session.tags[interaction.user.id] = row[0] if row and row[0] else DEFAULT_TAG.get("Lobby")

        self.session.joined.append(interaction.user)
        self.session.team_a = []
        self.session.team_b = []
        self.session.role_assignments = {}
        await interaction.response.edit_message(embed=generate_embed(self.session), view=self)
        await refresh_admin_panels(self.session)


    @discord.ui.button(label="Leave", style=discord.ButtonStyle.danger)
    async def leave(self, button: discord.ui.Button, interaction: discord.Interaction) -> None:
        """Remove whoever clicked from the lobby, if they were in it."""
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
    async def settings(self, button: discord.ui.Button, interaction: discord.Interaction) -> None:
        """Open a private admin panel for gameheads/the lobby owner.
        
        Deletes the user's previous panels first, so repeated clicks don't make multiple stale ephemeral messages."""
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

        back_button = discord.ui.Button(label="Back", style=discord.ButtonStyle.success)
        back_button.callback = self.back
        self.add_item(back_button)

    async def on_select(self, interaction: discord.Interaction):
        """Swap the two selected players' team+lane slots and refresh every open view of this lobby."""
        id_a, id_b = [int(v) for v in self.select.values]
        swap_slots(self.session, id_a, id_b)

        await self.session.message.edit(embed=generate_embed(self.session), view=LobbyView(self.session))
        await interaction.response.edit_message(embed=generate_embed(self.session), view=AdminView(self.session))
        await refresh_admin_panels(self.session)

    async def back(self, interaction: discord.Interaction):
        """Return to the admin panel without swapping anyone."""
        if not has_privilege(self.session, interaction):
            await interaction.response.send_message("You're not a game head! Feel free to apply though...", ephemeral=True)
            return
        await interaction.response.edit_message(embed=generate_embed(self.session), view=AdminView(self.session))

class WinnerSelectView(discord.ui.View):
    """Ephemeral team picker for declaring a winner.
    
    Uses manually-constructed buttons so their labels can show the session's actual team names instead of static text."""
    def __init__(self, session):
        super().__init__(timeout=180)
        self.session = session

        team_a_button = discord.ui.Button(label=session.team_names[0], style=discord.ButtonStyle.primary)
        team_a_button.callback = self.team_a
        self.add_item(team_a_button)

        team_b_button = discord.ui.Button(label=session.team_names[1], style=discord.ButtonStyle.primary)
        team_b_button.callback = self.team_b
        self.add_item(team_b_button)

        back_button = discord.ui.Button(label="Back", style=discord.ButtonStyle.success)
        back_button.callback = self.back
        self.add_item(back_button)

    async def team_a(self, interaction: discord.Interaction) -> None:
        """Declare team_a the winner: record wins/losses, post the postgame embed, end the session."""
        if not has_privilege(self.session, interaction):
            await interaction.response.send_message("You're not a game head! Feel free to apply though...", ephemeral=True)
            return
        
        await update_record(self.session, self.session.team_a, self.session.team_b)
        await apply_elo_changes(self.session, team_a_won=True)
        await self.session.message.edit(
            embed=generate_postgame_embed(self.session, self.session.team_names[0], self.session.team_a),
            view=PostgameView(self.session),
        )

        cog = interaction.client.get_cog("Matchmaking")
        cog.active_sessions.pop(self.session.key, None)

        await interaction.response.defer()
        await interaction.delete_original_response()
    
    async def team_b(self, interaction: discord.Interaction) -> None:
        """Declare team_b the winner: record wins/losses, post the postgame embed, end the session."""
        if not has_privilege(self.session, interaction):
            await interaction.response.send_message("You're not a game head! Feel free to apply though...", ephemeral=True)
            return
        
        await update_record(self.session, self.session.team_b, self.session.team_a)
        await apply_elo_changes(self.session, team_a_won=False)
        await self.session.message.edit(
            embed=generate_postgame_embed(self.session, self.session.team_names[1], self.session.team_b),
            view=PostgameView(self.session),
        )

        cog = interaction.client.get_cog("Matchmaking")
        cog.active_sessions.pop(self.session.key, None)

        await interaction.response.defer()
        await interaction.delete_original_response()
    
    async def back(self, interaction: discord.Interaction) -> None:
        """Return to the admin panel without declaring a winner."""
        if not has_privilege(self.session, interaction):
            await interaction.response.send_message("You're not a game head! Feel free to apply though...", ephemeral=True)
            return
        await interaction.response.edit_message(embed=generate_embed(self.session), view=AdminView(self.session))

class PostgameView(discord.ui.View):
    """Post-game view that allows for rematching."""
    def __init__(self, session):
        super().__init__(timeout=180)
        self.session = session

class AdminView(discord.ui.View):
    """Ephemeral admin panel: Shuffle / Swap / Winner. Gated to gameheads and the lobby owner."""
    def __init__(self, session):
        super().__init__(timeout=180)
        self.session = session

    @discord.ui.button(label="Shuffle", style=discord.ButtonStyle.primary)
    async def shuffle(self, button: discord.ui.Button, interaction: discord.Interaction) -> None:
        """Fetch each player's rank/role data and re-balance the lobby into two teams."""
        if (len(self.session.joined) % 2) != 0:
            await interaction.response.send_message("You need an even amount of players to shuffle!", ephemeral=True)
            return

        if not has_privilege(self.session, interaction):
            await interaction.response.send_message("You're not a game head! Feel free to apply though...", ephemeral=True)
            return
        
        elo_by_id, roles_by_id = await get_game_shuffle_data(self.session.joined, self.session.game)
        team_a, team_b, assignments = balance_teams(self.session.game, self.session.joined, elo_by_id, roles_by_id)
        self.session.team_a = team_a
        self.session.team_b = team_b
        self.session.role_assignments = assignments

        await self.session.message.edit(embed=generate_embed(self.session), view=LobbyView(self.session))
        await interaction.response.edit_message(embed=generate_embed(self.session), view=self)
        await refresh_admin_panels(self.session)

    @discord.ui.button(label="Swap", style=discord.ButtonStyle.secondary)
    async def swap(self, button: discord.ui.Button, interaction: discord.Interaction) -> None:
        """Open the two-player swap select menu. Requires a shuffle to have happened first."""
        if not has_privilege(self.session, interaction):
            await interaction.response.send_message("You're not a game head! Feel free to apply though...", ephemeral=True)
            return
        if not self.session.role_assignments:
            await interaction.response.send_message("Shuffle first before trying to swap!", ephemeral=True)
            return
        
        await interaction.response.edit_message(embed=generate_embed(self.session), view=SwapSelectView(self.session))
    
    @discord.ui.button(label="Winner", style=discord.ButtonStyle.success)
    async def winner(self, button: discord.ui.Button, interaction: discord.Interaction) -> None:
        """Open the team picker to declare a winner. Requires a shuffle to have happened first."""
        if not has_privilege(self.session, interaction):
            await interaction.response.send_message("You're not a game head! Feel free to apply though...", ephemeral=True)
            return
        if not self.session.role_assignments:
            await interaction.response.send_message("Shuffle first before deciding a winner!", ephemeral=True)
            return
        
        await interaction.response.edit_message(embed=generate_embed(self.session), view=WinnerSelectView(self.session))

    @discord.ui.button(label="Delete", style=discord.ButtonStyle.danger)
    async def delete(self, button: discord.ui.Button, interaction: discord.Interaction) -> None:
        """Cancel a game."""
        if not has_privilege(self.session, interaction):
            await interaction.response.send_message("You're not a game head! Feel free to apply though...", ephemeral=True)
            return
        
        await interaction.response.edit_message(embed=generate_embed(self.session), view=CancelConfirmView(self.session))

class CancelConfirmView(discord.ui.View):
    """Ephemeral confirmation step before actually cancelling a lobby.

    Uses a dropdown rather than buttons, so a misclick doesn't instantly end the game.
    """
    def __init__(self, session):
        super().__init__(timeout=180)
        self.session = session

        options = [
            discord.SelectOption(label="Yes, cancel this game", value="confirm", emoji="🗑️"),
            discord.SelectOption(label="No, go back", value="back", emoji="↩️"),
        ]
        self.select = discord.ui.Select(placeholder="Are you sure you want to cancel this game?", options=options)
        self.select.callback = self.on_select
        self.add_item(self.select)

    async def on_select(self, interaction: discord.Interaction) -> None:
        """Cancel the lobby if confirmed, otherwise return to the admin panel."""
        if not has_privilege(self.session, interaction):
            await interaction.response.send_message("You're not a game head! Feel free to apply though...", ephemeral=True)
            return

        if self.select.values[0] == "back":
            await interaction.response.edit_message(embed=generate_embed(self.session), view=AdminView(self.session))
            return

        try:
            await self.session.message.edit(embed=generate_cancelled_embed(self.session), view=None)
        except (discord.NotFound, discord.HTTPException):
            pass

        cog = interaction.client.get_cog("Matchmaking")
        cog.active_sessions.pop(self.session.key, None)

        await interaction.response.defer()
        await interaction.delete_original_response()

def setup(bot: discord.Bot) -> None:
    bot.add_cog(Matchmaking(bot))