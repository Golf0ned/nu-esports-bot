from utils import config

ELO_K = 60   # max elo swing for a single game, per player
ELO_D = 1000 # how much a rating gap affects win probability (bigger = flatter)

def decode_rank_value(game: str, rank_value: int | None) -> tuple[str, int | None] | None:
    """Reverse profile.py's compute_rank_value back into (tier, division)

    Returns None if rank_value is None
    Division is None for tiers without divisions"""
    if rank_value is None:
        return None
    tiers = config.game_data[game]["tiers"]
    divisions = config.game_data[game]["divisions"]
    no_division_tiers = config.game_data[game]["no_division_tiers"]

    index, remainder = divmod(rank_value, divisions)
    tier = tiers[index]
    if tier in no_division_tiers:
        return tier, None
    return tier, remainder+1

def compute_rank_points(game: str, tier: str, division: int | None) -> float:
    """Convert a tier+division into a seed elo using the game's rank curve
    
    Interpolates within a tier toward the next tier's base value (division 1 sits
    closest to the next tier, division `divisions` sits at this tier's own base).
    Flat (no-division) tiers return their base value directly."""
    tiers = config.game_data[game]["tiers"]
    divisions = config.game_data[game]["divisions"]
    points = config.game_data[game]["rank_points"]
    ascending = config.game_data[game]["divisions_ascend"]

    base = points[tier]
    if division is None:
        return base
    
    index = tiers.index(tier)
    if index + 1 >= len(tiers):
        return base #highest tier, nothing to interp towards

    next_base = points[tiers[index + 1]]
    gap = next_base - base
    progress = (division - 1) / divisions if ascending else (divisions - division) / divisions
    return base + gap * progress

def seed_elo(game: str, rank_value: int | None) -> float:
    """Pick a starting elo for a player with no elo row yet

    Uses their current rank if they have one, else the game's `default_tier`.
    Has to be deterministic since seeds get saved to profile_elo."""
    decoded = decode_rank_value(game, rank_value)
    if decoded is None:
        tiers = config.game_data[game]["tiers"]
        no_division_tiers = config.game_data[game]["no_division_tiers"]
        ascending = config.game_data[game]["divisions_ascend"]
        tier = config.game_data[game].get("default_tier", tiers[0])
        if tier in no_division_tiers:
            division = None
        else:
            division = 1 if ascending else config.game_data[game]["divisions"]
        return compute_rank_points(game, tier, division)
    tier, division = decoded
    return compute_rank_points(game, tier, division)

def compute_elo_deltas(
    team_a: dict[int, float],
    team_b: dict[int, float],
    a_won: bool,
    K: float = ELO_K,
    D: float = ELO_D
) -> dict[int, float]:
    """Compute each player's individual elo delta for one match.
    
    Computed at team level, then adjusted per player for underdogs/expected winners."""
    avg_a = sum(team_a.values()) / len(team_a)
    avg_b = sum(team_b.values()) / len(team_b)

    e_a = 1 / (1+ 10 ** ((avg_b - avg_a) / D))
    e_b = 1 - e_a
    result_a = 1 if a_won else 0
    result_b = 1 - result_a

    # K is per player, so scale by team size, else 6v6 moves less than 5v5
    scale = (len(team_a) + len(team_b)) / 2

    team_delta_a = K * scale * (result_a - e_a)
    team_delta_b = K * scale * (result_b - e_b)

    deltas: dict[int, float] = {}
    for team, opp_avg, result, team_delta in (
        (team_a, avg_b, result_a, team_delta_a),
        (team_b, avg_a, result_b, team_delta_b)
    ):
        raw = {
            pid: result - (1 / (1 + 10 ** ((opp_avg - elo) / D)))
            for pid, elo in team.items()
        }
        raw_sum = sum(raw.values())
        if abs(raw_sum) < 1e-9:
            share = team_delta / len(team)
            for pid in team:
                deltas[pid] = share
        else:
            for pid, r in raw.items():
                deltas[pid] = team_delta * (r / raw_sum)

    return deltas