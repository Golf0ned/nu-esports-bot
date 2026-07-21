from utils import config

ELO_K = 40  # max elo swing for a single game
ELO_D = 500 # how much a rating gap affects win probability (bigger = flatter)

def decode_rank_value(game: str, rank_value: int | None) -> tuple[str, int | None] | None:
    """Reverse profile.py's compute_rank_value back into (tier, division)

    Returns None if rank_value is None
    Division is None for tiers without divisions"""
    return NotImplementedError

def compute_rank_points(game: str, tier: str, division: int | None) -> float:
    """Convert a tier+division into a seed elo using the game's rank curve
    
    Interpolates within a tier toward the next tier's base value (division 1 sits
    closest to the next tier, division `divisions` sits at this tier's own base).
    Flat (no-division) tiers return their base value directly."""
    return NotImplementedError

def seed_elo(game: str, rank_value: int | None) -> float:
    """Pick a starting elo for a player with no elo row yet

    Uses their current rank if they have one; falls back to this game's lowest
    tier if they've never set a rank (safest assumption: unproven, not average)."""
    return NotImplementedError

def compute_elo_deltas(
    team_a: dict[int, float],
    team_b: dict[int, float],
    a_won: bool,
    K: float = ELO_K,
    D: float = ELO_D
) -> dict[int, float]:
    """Compute each player's individual elo delta for one match.
    
    Computed at team level, then adjusted per player for underdogs/expected winners."""
    return NotImplementedError

