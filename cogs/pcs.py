import io
from datetime import datetime, timedelta, timezone
from typing import Dict, Tuple, List

import aiohttp
import discord
from discord.ext import commands
from PIL import Image, ImageDraw, ImageFont

from utils import config
from utils import db


GUILD_ID = config.secrets["discord"]["guild_id"]


GGLEAP_BASE_URL = config.config["apis"]["ggleap"]
PCS_ENDPOINT = f"{GGLEAP_BASE_URL}/machines/uptime"
RESERVATIONS_ENDPOINT = f"{GGLEAP_BASE_URL}/reservations"

# Constants
CST_OFFSET = timezone(timedelta(hours=-6))
ADVANCE_BOOKING_DAYS = 2
MAX_MAIN_ROOM_PCS = 5
BACK_ROOM_PCS = [0, 14, 15]  # 0 = Streaming, 14 = Back Room 1, 15 = Back Room 2
MAIN_ROOM_PCS = list(range(1, 11))
PRIME_TIME_WEEKDAY_HOUR = 19  # 7 PM
PRIME_TIME_WEEKEND_HOUR = 18  # 6 PM

STATE_TO_EMOJI = {
    "ReadyForUser": ":green_square:",
    "UserLoggedIn": ":red_square:",
    "AdminMode": ":red_square:",  # Treat admin as in use
    "Off": ":black_large_square:",
}

STATE_TO_NAME = {
    "ReadyForUser": "Available",
    "UserLoggedIn": "In Use",
    "AdminMode": "In Use",
    "Off": "Offline",
}


class PCs(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        # Team to prime time quota mapping
        self.team_prime_time_quota = {
            'Valorant White': 2,
            'Valorant Purple': 1,
            'Overwatch White': 1,
            'Overwatch Purple': 1,
            'League Purple': 1,
            'Apex White': 1,
            'Apex Purple': 1,
        }

    @staticmethod
    def format_pc(pc: int) -> str:
        """Format a PC number for display"""
        return "Streaming" if pc == 0 else f"PC {pc}"

    @staticmethod
    def ensure_timezone(dt: datetime, assume_utc: bool = True) -> datetime:
        """Ensure a datetime has timezone info, converting to CST"""
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc if assume_utc else CST_OFFSET)
        return dt.astimezone(CST_OFFSET)

    async def get_reservations_in_range(self, start_time: datetime, end_time: datetime) -> List[Dict]:
        """Fetch reservations that overlap with the given time range from database"""
        sql = """
            SELECT id, team, pcs, start_time, end_time, manager, is_prime_time
            FROM reservations
            WHERE start_time < %s AND end_time > %s
            ORDER BY start_time
        """
        rows = await db.fetch_all(sql, (end_time, start_time))
        
        reservations = []
        for row in rows:
            reservations.append({
                'id': row[0],
                'team': row[1],
                'pcs': row[2],  
                'start_time': row[3],
                'end_time': row[4],
                'manager': row[5],
                'is_prime_time': row[6],
            })
        return reservations

    async def get_team_prime_time_usage(self, team: str, start_time: datetime) -> int:
        """Get the number of prime time reservations used by a team this week"""
        week_start = self.get_week_start(start_time)
        week_end = week_start + timedelta(days=7)
        
        sql = """
            SELECT COUNT(*)
            FROM reservations
            WHERE team = %s
            AND is_prime_time = TRUE
            AND start_time >= %s
            AND start_time < %s
        """
        result = await db.fetch_one(sql, (team, week_start, week_end))
        return result[0] if result else 0

    async def save_reservation(self, team: str, pcs: List[int], start_time: datetime, 
                               end_time: datetime, manager: str, is_prime_time: bool) -> int:
        """Save a reservation to the database and return its ID"""
        sql = """
            INSERT INTO reservations (team, pcs, start_time, end_time, manager, is_prime_time)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
        """
        result = await db.fetch_one(sql, (team, pcs, start_time, end_time, manager, is_prime_time))
        return result[0] if result else None

    async def cog_command_error(self, ctx, error):
        """Handle errors for commands in this cog"""
        if isinstance(error, commands.CommandOnCooldown):
            minutes, seconds = divmod(int(error.retry_after), 60)
            if minutes > 0:
                time_str = f"{minutes}m {seconds}s"
            else:
                time_str = f"{seconds}s"
            await ctx.respond(
                f"⏰ This command is on cooldown. Please try again in **{time_str}**.",
                ephemeral=True
            )
        else:
            # Re-raise other errors
            raise error 

    def parse_time_range(self, time_str: str) -> Tuple[datetime, datetime]:
        """Parse time range string like '2025-10-10 7:00PM-9:00PM' into datetime objects (CST)"""
        # Split date and time range
        try:
            date_part, time_range = time_str.strip().split(' ', 1)
            start_time_str, end_time_str = time_range.split('-')
            
            # Parse date
            year, month, day = map(int, date_part.split('-'))
            
            # Parse start time
            start_time = datetime.strptime(start_time_str.strip(), '%I:%M%p')
            start_dt = datetime(year, month, day, start_time.hour, start_time.minute, tzinfo=CST_OFFSET)
            
            # Parse end time
            end_time = datetime.strptime(end_time_str.strip(), '%I:%M%p')
            end_dt = datetime(year, month, day, end_time.hour, end_time.minute, tzinfo=CST_OFFSET)
            
            return start_dt, end_dt
        except Exception as e:
            raise ValueError(f"Invalid time format. Expected format: 'YYYY-MM-DD H:MMAM/PM-H:MMAM/PM' (e.g., '2025-10-10 7:00PM-9:00PM')")

    def validate_advance_booking(self, start_time: datetime) -> bool:
        """Check if reservation is at least 2 days in advance"""
        now = datetime.now(CST_OFFSET)
        days_ahead = (start_time.date() - now.date()).days
        return days_ahead >= ADVANCE_BOOKING_DAYS

    def is_prime_time(self, start_time: datetime, end_time: datetime, pcs: List[int]) -> bool:
        """
        Check if reservation qualifies as prime time.
        Prime time: main room PCs (1-10) after 7PM on Sun-Thu, after 6PM on Fri-Sat
        """
        # Only main room PCs count for prime time
        main_room_pcs = [pc for pc in pcs if pc in MAIN_ROOM_PCS]
        if not main_room_pcs:
            return False
        
        # Check if any part of the reservation falls in prime time hours
        weekday = start_time.weekday()  # Monday=0, Sunday=6
        
        # Determine prime time start hour
        if weekday in [4, 5]:  # Friday, Saturday
            prime_start_hour = PRIME_TIME_WEEKEND_HOUR
        else:  # Sunday-Thursday
            prime_start_hour = PRIME_TIME_WEEKDAY_HOUR
        
        # Check if the reservation overlaps with prime time
        prime_start = start_time.replace(hour=prime_start_hour, minute=0, second=0, microsecond=0)
        
        # If reservation ends before prime time starts, not prime time
        if end_time <= prime_start:
            return False
        
        # If reservation starts before prime time but extends into it, or starts during prime time, it's prime time
        return True

    def get_week_start(self, dt: datetime) -> datetime:
        """Get the start of the week (Monday 00:00) for a given datetime"""
        days_since_monday = dt.weekday()
        week_start = dt.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days_since_monday)
        return week_start
    
    def is_within_open_hours(self, start_time: datetime, end_time: datetime) -> bool: 
        """"Check that reservation is within Gameroom hours (ignoring adjusted hours for now)"""
        # Get day of week and pull correct hours
        day_of_week = start_time.weekday()
        hours = config.config["gameroom"]["default_hours"][day_of_week] 
        
        # Convert to proper format to use parse_time_range 
        hours_str = start_time.strftime("%Y-%m-%d") + " " + hours.replace(" ", "")
        gr_start_time, gr_end_time = self.parse_time_range(hours_str)

        # Compare datetimes
        if gr_start_time <= start_time <= gr_end_time and gr_start_time <= end_time <= gr_end_time:
            return True
        else:
            return False

    async def check_prime_time_quota(self, team: str, start_time: datetime) -> Tuple[bool, int]:
        """
        Check if team has prime time slots available.
        Returns (has_quota, used_count)
        """
        used_count = await self.get_team_prime_time_usage(team, start_time)
        quota = self.team_prime_time_quota[team]
        return used_count < quota, used_count

    async def check_conflicts(self, start_time: datetime, end_time: datetime, num_pcs: int) -> Tuple[bool, str, str]:
        """
        Check for conflicts with existing reservations.
        Returns (has_conflict, conflicting_team, conflicting_manager)
        """
        # Get all overlapping reservations from database
        overlapping = await self.get_reservations_in_range(start_time, end_time)
        
        # For each time slot in the requested range, check if we can fit the PCs
        # We need to ensure at most 5 main room PCs are in use at any given time
        
        # Create a timeline of all reservation boundaries
        time_points = set()
        time_points.add(start_time)
        time_points.add(end_time)
        for res in overlapping:
            time_points.add(res['start_time'])
            time_points.add(res['end_time'])
        
        time_points = sorted(time_points)
        
        # Check each interval
        for i in range(len(time_points) - 1):
            interval_start = time_points[i]
            interval_end = time_points[i + 1]
            
            # Skip intervals outside our requested range
            if interval_end <= start_time or interval_start >= end_time:
                continue
            
            # Count how many main room and back room PCs are already reserved in this interval
            main_room_used = 0
            back_room_used = 0
            conflicting_team = None
            conflicting_manager = None
            
            for res in overlapping:
                if res['start_time'] < interval_end and res['end_time'] > interval_start:
                    for pc in res['pcs']:
                        if pc in MAIN_ROOM_PCS:
                            main_room_used += 1
                        elif pc in BACK_ROOM_PCS:
                            back_room_used += 1
                    if conflicting_team is None:
                        conflicting_team = res['team']
                        conflicting_manager = res['manager']
            
            # Check if we can fit the requested PCs
            # We have: back room (14, 15, streaming) = 3 PCs, main room = 10 PCs
            # Max main room at once = 5
            
            # Available back room PCs in this interval
            back_room_available = len(BACK_ROOM_PCS) - back_room_used
            
            # Check Tuesday restriction
            if interval_start.weekday() == 1:  # Tuesday
                back_room_available = 0  # No back room on Tuesday
            
            # Available main room PCs
            main_room_available = MAX_MAIN_ROOM_PCS - main_room_used
            
            # Can we fit num_pcs?
            total_available = back_room_available + main_room_available
            
            if total_available < num_pcs:
                return True, conflicting_team, conflicting_manager
        
        return False, None, None

    async def allocate_pcs(self, start_time: datetime, end_time: datetime, num_pcs: int) -> List[int]:
        """
        Allocate PCs optimally: back room first (14, 15, streaming), then main room (contiguous).
        Returns list of PC numbers, or empty list if can't allocate.
        PC numbers: 1-10 (main room), 14, 15 (back room), 0 (streaming, treated as back room)
        """
        # Get all overlapping reservations from database
        overlapping = await self.get_reservations_in_range(start_time, end_time)
        
        # Check Tuesday restriction
        is_tuesday = start_time.weekday() == 1
        
        # Determine which PCs are available throughout the entire time range
        all_pcs = BACK_ROOM_PCS + MAIN_ROOM_PCS  # Back room first, then main room
        if is_tuesday:
            all_pcs = MAIN_ROOM_PCS  # No back room on Tuesday
        
        available_pcs = []
        for pc in all_pcs:
            is_available = True
            for res in overlapping:
                if pc in res['pcs']:
                    is_available = False
                    break
            if is_available:
                available_pcs.append(pc)
        
        # Check if we have enough PCs
        if len(available_pcs) < num_pcs:
            return []
        
        # Allocate PCs with preference for back room, then contiguous main room
        allocated = []
        
        # First, allocate back room PCs (14, 15, 0/streaming)
        back_room_order = [14, 15, 0]
        for pc in back_room_order:
            if pc in available_pcs and len(allocated) < num_pcs:
                allocated.append(pc)
        
        # Then, allocate main room PCs (prefer contiguous: 1-5, then 6-10)
        if len(allocated) < num_pcs:
            # Try to allocate from 1-5 first
            main_room_group1 = [pc for pc in range(1, 6) if pc in available_pcs]
            main_room_group2 = [pc for pc in range(6, 11) if pc in available_pcs]
            
            # Take from group 1 first
            for pc in main_room_group1:
                if len(allocated) < num_pcs:
                    allocated.append(pc)
            
            # Then from group 2
            for pc in main_room_group2:
                if len(allocated) < num_pcs:
                    allocated.append(pc)
        
        # Verify we don't exceed max main room PCs
        main_room_allocated = [pc for pc in allocated if pc in MAIN_ROOM_PCS]
        if len(main_room_allocated) > MAX_MAIN_ROOM_PCS:
            return []  # Can't allocate
        
        return allocated

    async def fetch_pcs(self) -> Dict:
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(PCS_ENDPOINT) as resp:
                resp.raise_for_status()
                return await resp.json()

    @staticmethod
    def normalize_key(key: str) -> str:
        # Normalize Desk IDs for comparison (e.g., "Desk 009" -> "desk 009")
        return key.strip().lower()

    @staticmethod
    def extract_sort_key(name: str) -> Tuple[int, str]:
        # Attempt to sort by numeric desk id if present; fallback to name
        # Examples: "Desk 009" -> (9, "Desk 009"), "Desk 000 - Streaming" -> (999, name)
        try:
            if name.lower().startswith("desk "):
                remainder = name[5:].strip()
                digits = "".join(ch for ch in remainder if ch.isdigit())
                if digits:
                    desk_num = int(digits)
                    # Put Desk 000 (Streaming) at the end
                    if desk_num == 0:
                        return (999, name)
                    return (desk_num, name)
        except Exception:
            pass
        return (10**9, name)

    @staticmethod
    def build_grid(data: Dict, reservations: List[Dict] = None, columns: int = 5) -> Tuple[str, Dict[str, str]]:
        # Returns (grid_text, id_to_state)
        # Filter out SAIT TEST machine, Desk 14, Desk 15, and Streaming
        def should_include(name: str) -> bool:
            if name.startswith("SAIT TEST"):
                return False
            # Check if it's Desk 14, 15, or Streaming (Desk 000)
            if name.lower().startswith("desk "):
                remainder = name[5:].strip()
                digits = "".join(ch for ch in remainder if ch.isdigit())
                if digits:
                    desk_num = int(digits)
                    if desk_num in [0, 14, 15]:  # 0 is Streaming
                        return False
            return True
        
        filtered_data = {k: v for k, v in data.items() if should_include(k)}
        items = sorted(filtered_data.items(), key=lambda kv: PCs.extract_sort_key(kv[0]))

        # Build upcoming reservations map (desk -> minutes until reservation)
        # and currently reserved desks
        upcoming_reservations = {}
        currently_reserved = set()
        if reservations:
            THRESHOLD_MINUTES = 30
            now = datetime.now(CST_OFFSET)
            
            for res in reservations:
                machines = res.get("machines", [])
                start_time_str = res.get("start_time")
                end_time_str = res.get("end_time")
                if not start_time_str or not end_time_str:
                    continue
                    
                # Parse and convert to CST
                start_utc = datetime.fromisoformat(start_time_str)
                end_utc = datetime.fromisoformat(end_time_str)
                start_cst = PCs.ensure_timezone(start_utc)
                end_cst = PCs.ensure_timezone(end_utc)
                
                # Check if reservation is currently active
                if start_cst <= now <= end_cst:
                    for machine in machines:
                        currently_reserved.add(machine)
                
                # Check if reservation starts soon
                time_diff = (start_cst - now).total_seconds() / 60  # minutes
                if 0 < time_diff <= THRESHOLD_MINUTES:
                    for machine in machines:
                        if machine not in upcoming_reservations or time_diff < upcoming_reservations[machine]:
                            upcoming_reservations[machine] = int(time_diff)

        id_to_state: Dict[str, str] = {}
        cells = []
        for name, info in items:
            state = info.get("state", "Unknown")
            id_to_state[name] = state
            emoji = STATE_TO_EMOJI.get(state, ":white_large_square:")
            
            # Get uptime
            uptime = info.get("uptime", {})
            hours = uptime.get("hours", 0)
            minutes = uptime.get("minutes", 0)
            
            # Show short id for readability; prefer the numeric portion if available
            short = name
            if name.lower().startswith("desk "):
                remainder = name[5:].strip()
                digits = "".join(ch for ch in remainder if ch.isdigit())
                if digits:
                    # Map Desk 000 to "Streaming"
                    if int(digits) == 0:
                        short = "Streaming"
                    else:
                        short = digits.zfill(3)
            
            # Check if this PC should be highlighted (can be kicked off)
            # Criteria: uptime > 2 hours AND not currently in a reserved block
            total_minutes = (hours * 60) + minutes
            should_bold = total_minutes > 120 and name not in currently_reserved and state != "ReadyForUser"
            
            # Build base cell text
            if state == "ReadyForUser":
                cell_text = f"{emoji} `{short}`"
            else:
                uptime_text = f"{hours}h {minutes}m"
                if should_bold:
                    cell_text = f"{emoji} **`{short}` {uptime_text}**"
                else:
                    cell_text = f"{emoji} `{short}` {uptime_text}"
            
            # Add upcoming reservation warning if applicable
            if name in upcoming_reservations:
                minutes_until = upcoming_reservations[name]
                cell_text += f" *Reserved in {minutes_until}m"
            
            cells.append(cell_text)

        # Build rows
        rows = []
        for i in range(0, len(cells), columns):
            rows.append("\n".join(cells[i:i+columns]))

        return ("\n".join(rows) if rows else "No PCs found.", id_to_state)

    @commands.slash_command(name="pcs", description="Show PC statuses as a color grid", guild_ids=[GUILD_ID])
    @commands.cooldown(1, 300, commands.BucketType.user)  
    async def pcs(self, ctx):
        await ctx.defer()
        try:
            data = await self.fetch_pcs()
        except Exception as e:
            print(e)
            await ctx.followup.send("Failed to fetch PC statuses. Please try again later.", ephemeral=True)
            return

        # Fetch reservations for upcoming reservation warnings
        try:
            # Get current time in CST (UTC-6)
            today = datetime.now(CST_OFFSET)
            date_str = today.strftime("%Y-%m-%d")
            reservations_data = await self.fetch_reservations(date_str)
            reservations = reservations_data.get("reservations", [])
        except Exception as e:
            print(f"Failed to fetch reservations: {e}")
            reservations = []

        grid, id_to_state = self.build_grid(data, reservations)

        # Tally counts by state, combining AdminMode into UserLoggedIn
        counts: Dict[str, int] = {}
        for state in id_to_state.values():
            # Map AdminMode to UserLoggedIn for counting
            normalized_state = "UserLoggedIn" if state == "AdminMode" else state
            counts[normalized_state] = counts.get(normalized_state, 0) + 1

        # Build legend with unique display names only
        legend_parts = []
        seen_names = set()
        for state, emoji in STATE_TO_EMOJI.items():
            display_name = STATE_TO_NAME[state]
            if display_name in seen_names:
                continue
            seen_names.add(display_name)
            # Use the normalized count
            normalized_state = "UserLoggedIn" if state == "AdminMode" else state
            legend_parts.append(f"{emoji} {display_name} ({counts.get(normalized_state, 0)})")
        legend = " · ".join(legend_parts)

        embed = discord.Embed(
            title="PC Statuses",
            color=discord.Color.from_rgb(78, 42, 132),
        )
        embed.add_field(name="Legend", value=legend or "No data", inline=False)
        embed.add_field(name="Grid", value=grid, inline=False)
        embed.set_footer(text="Bold text = Can be kicked off (>2hrs, not reserved)")

        await ctx.followup.send(embed=embed)

    @commands.slash_command(name="pc", description="Get a single PC's state and uptime", guild_ids=[GUILD_ID])
    @commands.cooldown(1, 300, commands.BucketType.user)  
    async def pc(self, ctx, pc_number: discord.Option(str, name="pc_number", description="PC number (e.g., 1 for Desk 1, 15 for Desk 15)", required=True)):
        await ctx.defer()
        try:
            data = await self.fetch_pcs()
        except Exception as e:
            await ctx.followup.send("Failed to fetch PC data. Please try again later.", ephemeral=True)
            return

        # Fetch reservations to check if PC is currently reserved
        try:
            today = datetime.now(CST_OFFSET)
            date_str = today.strftime("%Y-%m-%d")
            reservations_data = await self.fetch_reservations(date_str)
            reservations = reservations_data.get("reservations", [])
        except Exception as e:
            print(f"Failed to fetch reservations: {e}")
            reservations = []

        # Attempt exact and case-insensitive matches
        target = None
        norm = self.normalize_key(pc_number)
        for key, value in data.items():
            if self.normalize_key(key) == norm:
                target = (key, value)
                break
        if target is None:
            # Fallback: if user provides just digits, try to match "Desk XXX"
            digits = "".join(ch for ch in pc_number if ch.isdigit())
            if digits:
                desired = f"desk {int(digits):03d}"
                for key, value in data.items():
                    if self.normalize_key(key).startswith(desired):
                        target = (key, value)
                        break

        if target is None:
            await ctx.followup.send(f"PC `{pc_number}` not found.", ephemeral=True)
            return

        name, info = target
        state = info.get("state", "Unknown")
        uptime = info.get("uptime", {})
        hours = uptime.get("hours", 0)
        minutes = uptime.get("minutes", 0)

        # Check if PC is currently in a reserved block
        currently_reserved = False
        now = datetime.now(CST_OFFSET)
        for res in reservations:
            machines = res.get("machines", [])
            if name not in machines:
                continue
            start_time_str = res.get("start_time")
            end_time_str = res.get("end_time")
            if not start_time_str or not end_time_str:
                continue
            
            start_utc = datetime.fromisoformat(start_time_str)
            end_utc = datetime.fromisoformat(end_time_str)
            start_cst = PCs.ensure_timezone(start_utc)
            end_cst = PCs.ensure_timezone(end_utc)
            
            if start_cst <= now <= end_cst:
                currently_reserved = True
                break

        emoji = STATE_TO_EMOJI.get(state, ":white_large_square:")
        display_state = STATE_TO_NAME.get(state, state)  # Map to friendly name
        
        # Check if PC can be kicked off (uptime > 2hrs and not reserved)
        total_minutes = (hours * 60) + minutes
        can_kick = total_minutes > 120 and not currently_reserved and state != "ReadyForUser"
        
        embed = discord.Embed(
            title=name,
            description=f"{emoji} {display_state}",
            color=discord.Color.from_rgb(78, 42, 132),
        )
        
        uptime_value = f"**{hours}h {minutes}m**" if can_kick else f"{hours}h {minutes}m"
        embed.add_field(name=":clock1: Uptime", value=uptime_value, inline=True)
        
        if can_kick:
            embed.add_field(name="⚠️ Status", value="Can be kicked off (>2hrs, not reserved)", inline=False)

        await ctx.followup.send(embed=embed)

    @commands.slash_command(name="reservations", description="Show PC reservations for a date", guild_ids=[GUILD_ID])
    async def reservations(
        self,
        ctx,
        date: discord.Option(str, name="date", description="Date in YYYY-MM-DD format (default: today)", required=False)
    ):
        await ctx.defer()
        
        # Parse or default to today (in CST)
        if date:
            try:
                target_date = datetime.strptime(date, "%Y-%m-%d")
            except ValueError:
                await ctx.followup.send("Invalid date format. Please use YYYY-MM-DD (e.g., 2025-09-30)", ephemeral=True)
                return
        else:
            target_date = datetime.now(CST_OFFSET)
        
        date_str = target_date.strftime("%Y-%m-%d")
        
        # Fetch reservations
        try:
            data = await self.fetch_reservations(date_str)
        except Exception as e:
            print(e)
            await ctx.followup.send("Failed to fetch reservations. Please try again later.", ephemeral=True)
            return
        
        reservations = data.get("reservations", [])
        
        if not reservations:
            embed = discord.Embed(
                title=f"Reservations for {target_date.strftime('%A, %B %d, %Y')}",
                description="No reservations found for this date.",
                color=discord.Color.from_rgb(78, 42, 132),
            )
            await ctx.followup.send(embed=embed)
            return
        
        # Build timeline view with interactive date navigation
        view = ReservationView(reservations, target_date, self)
        embed, file = await view.build_embed_and_file()
        
        await ctx.followup.send(embed=embed, file=file, view=view)

    async def fetch_reservations(self, date_str: str) -> Dict:
        timeout = aiohttp.ClientTimeout(total=10)
        url = f"{RESERVATIONS_ENDPOINT}/{date_str}"
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                resp.raise_for_status()
                return await resp.json()

    @commands.slash_command(name="reserve", description="Reserve PCs for your team", guild_ids=[GUILD_ID])
    async def reserve(
        self,
        ctx,
        team: discord.Option(
            str, 
            name="team", 
            description="Your team", 
            choices=[
                "Valorant White", 
                "Valorant Purple", 
                "Overwatch White", 
                "Overwatch Purple", 
                "League Purple", 
                "Apex White", 
                "Apex Purple"
            ], 
            required=True
        ),
        num_pcs: discord.Option(int, name="num_pcs", description="Number of PCs to reserve (1-8)", min_value=1, max_value=10, required=True),
    ):
        # Check if user has required role
        """allowed_role_ids = config.config["reservations"]["roles"]
        user_role_ids = [role.id for role in ctx.author.roles]
        
        if not any(role_id in allowed_role_ids for role_id in user_role_ids):
            await ctx.respond(
                "❌ You don't have permission to reserve PCs. Contact a team manager.",
                ephemeral=True
            )
            return"""
        
        # Show modal for time input
        modal = ReservationTimeModal(self, team, num_pcs)
        await ctx.send_modal(modal)

    @commands.slash_command(name="show_team_reservations", description="Show all team reservations for a specific date", guild_ids=[GUILD_ID])
    async def show_team_reservations(
        self,
        ctx,
        date: discord.Option(str, name="date", description="Date in YYYY-MM-DD format (default: today)", required=False)
    ):
        # Check if user has required role
        allowed_role_ids = config.config["reservations"]["roles"]
        user_role_ids = [role.id for role in ctx.author.roles]
        
        if not any(role_id in allowed_role_ids for role_id in user_role_ids):
            await ctx.respond(
                "❌ You don't have permission to view team reservations. Contact a team manager.",
                ephemeral=True
            )
            return
        
        await ctx.defer()
        
        # Parse or default to today (in CST)
        if date:
            try:
                target_date = datetime.strptime(date, "%Y-%m-%d")
                target_date = target_date.replace(tzinfo=CST_OFFSET)
            except ValueError:
                await ctx.followup.send("Invalid date format. Please use YYYY-MM-DD (e.g., 2025-10-10)", ephemeral=True)
                return
        else:
            target_date = datetime.now(CST_OFFSET)
        
        # Get start and end of the day
        start_of_day = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = target_date.replace(hour=23, minute=59, second=59, microsecond=999999)
        
        # Query database for reservations on this date
        reservations = await self.get_reservations_in_range(start_of_day, end_of_day)
        
        if not reservations:
            embed = discord.Embed(
                title=f"Team Reservations for {target_date.strftime('%A, %B %d, %Y')}",
                description="No reservations found for this date.",
                color=discord.Color.from_rgb(78, 42, 132),
            )
            await ctx.followup.send(embed=embed)
            return
        
        # Build embed with reservation details
        embed = discord.Embed(
            title=f"Team Reservations for {target_date.strftime('%A, %B %d, %Y')}",
            color=discord.Color.from_rgb(78, 42, 132),
        )
        
        # Sort reservations by start time
        reservations.sort(key=lambda r: r['start_time'])
        
        for idx, res in enumerate(reservations, 1):
            # Format PC list
            pc_list = ", ".join(PCs.format_pc(pc) for pc in sorted(res['pcs'], key=lambda x: (x == 0, x)))
            
            # Format times (convert to CST if needed)
            start_cst = PCs.ensure_timezone(res['start_time'])
            end_cst = PCs.ensure_timezone(res['end_time'])
            
            # Build field value
            time_str = f"{start_cst.strftime('%I:%M %p')} - {end_cst.strftime('%I:%M %p')} CST"
            prime_indicator = " ✨" if res['is_prime_time'] else ""
            
            field_value = (
                f"**Team:** {res['team']}\n"
                f"**PCs:** {pc_list}\n"
                f"**Time:** {time_str}{prime_indicator}\n"
                f"**Manager:** {res['manager']}"
            )
            
            embed.add_field(
                name=f"Reservation #{idx}",
                value=field_value,
                inline=False
            )
        
        embed.set_footer(text="✨ = Prime Time Reservation")
        await ctx.followup.send(embed=embed)

    @staticmethod
    def build_reservation_image(reservations: List[Dict], target_date: datetime, start_hour: int, end_hour: int, end_minute: int = 0) -> io.BytesIO:
        """Build a 2D grid image with time slots (x-axis) and desks (y-axis)"""
        
        # Define desks to show: 1-10, 14, 15, and Streaming
        all_desks = [f"Desk {i:03d}" for i in range(1, 11)] + ["Desk 014", "Desk 015", "Desk 000 - Streaming"]
        
        # Build time slots from start_hour to end_hour:end_minute in 30-minute increments
        time_slots = []
        base_date = target_date.replace(hour=start_hour, minute=0, second=0, microsecond=0, tzinfo=CST_OFFSET)
        end_time = target_date.replace(hour=end_hour, minute=end_minute, second=0, microsecond=0, tzinfo=CST_OFFSET)
        
        current_time = base_date
        while current_time <= end_time:
            time_slots.append(current_time)
            current_time += timedelta(minutes=30)
        
        # Initialize grid: desk -> set of reserved time slot indices
        desk_reservations = {desk: set() for desk in all_desks}
        
        # Process reservations
        for res in reservations:
            machines = res.get("machines", [])
            
            # Parse times and convert to CST
            start_utc = datetime.fromisoformat(res.get("start_time"))
            end_utc = datetime.fromisoformat(res.get("end_time"))
            start_cst = PCs.ensure_timezone(start_utc)
            end_cst = PCs.ensure_timezone(end_utc)
            
            # Mark time slots as reserved for each machine
            for machine in machines:
                if machine not in desk_reservations:
                    continue
                
                # Find which time slots are covered
                for slot_idx, slot_time in enumerate(time_slots):
                    slot_end = slot_time + timedelta(minutes=30)
                    # Check if this slot overlaps with the reservation
                    if start_cst < slot_end and end_cst > slot_time:
                        desk_reservations[machine].add(slot_idx)
        
        # Image dimensions
        cell_size = 30
        label_width = 80
        header_height = 40
        width = label_width + (len(time_slots) * cell_size)
        height = header_height + (len(all_desks) * cell_size)
        
        # Colors (Discord dark theme friendly)
        bg_color = (47, 49, 54)  # Discord dark background
        text_color = (220, 221, 222)  # Light gray text
        grid_color = (60, 63, 68)  # Slightly lighter for grid lines
        available_color = (87, 242, 135)  # Green
        reserved_color = (155, 89, 182)  # Purple
        
        # Create image
        img = Image.new('RGB', (width, height), bg_color)
        draw = ImageDraw.Draw(img)
        
        # Try to load a font, fallback to default if not available
        try:
            font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 14)
            small_font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 12)
        except:
            font = ImageFont.load_default()
            small_font = ImageFont.load_default()
        
        # Draw header row (time labels)
        for idx, slot_time in enumerate(time_slots):
            x = label_width + (idx * cell_size)
            if slot_time.minute == 0:
                time_label = slot_time.strftime("%I%p").lstrip("0").lower()
                draw.text((x + 5, 5), time_label, fill=text_color, font=small_font)
        
        # Draw grid and desk labels
        for desk_idx, desk in enumerate(all_desks):
            y = header_height + (desk_idx * cell_size)
            
            # Format desk name
            short_name = desk
            if desk.lower().startswith("desk "):
                remainder = desk[5:].strip()
                digits = "".join(ch for ch in remainder if ch.isdigit())
                if digits:
                    if int(digits) == 0:
                        short_name = "Stream"
                    else:
                        short_name = f"Desk {int(digits)}"
            
            # Draw desk label
            draw.text((5, y + 8), short_name, fill=text_color, font=font)
            
            # Draw cells for this desk
            reserved_slots = desk_reservations[desk]
            for slot_idx in range(len(time_slots)):
                x = label_width + (slot_idx * cell_size)
                color = reserved_color if slot_idx in reserved_slots else available_color
                
                # Draw filled rectangle
                draw.rectangle([x, y, x + cell_size - 2, y + cell_size - 2], fill=color, outline=grid_color)
        
        # Save to BytesIO
        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        buffer.seek(0)
        return buffer


class ReservationTimeModal(discord.ui.Modal):
    def __init__(self, cog: 'PCs', team: str, num_pcs: int):
        super().__init__(title="Reserve PCs - Set Time")
        self.cog = cog
        self.team = team
        self.num_pcs = num_pcs
        
        self.add_item(discord.ui.InputText(
            label="Date",
            placeholder="YYYY-MM-DD (e.g., 2025-10-15)",
            style=discord.InputTextStyle.short,
            required=True,
        ))
        
        self.add_item(discord.ui.InputText(
            label="Start Time",
            placeholder="H:MMAM/PM (e.g., 7:00PM)",
            style=discord.InputTextStyle.short,
            required=True,
        ))
        
        self.add_item(discord.ui.InputText(
            label="End Time",
            placeholder="H:MMAM/PM (e.g., 9:00PM)",
            style=discord.InputTextStyle.short,
            required=True,
        ))
    
    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        # Get values from modal
        date_str = self.children[0].value.strip()
        start_time_str = self.children[1].value.strip()
        end_time_str = self.children[2].value.strip()
        
        # Combine into the format expected by parse_time_range
        times = f"{date_str} {start_time_str}-{end_time_str}"
        
        # Parse time range
        try:
            start_time, end_time = self.cog.parse_time_range(times)
        except ValueError as e:
            await interaction.followup.send(f"❌ {str(e)}", ephemeral=True)
            return
        
        # Ensure end time is after start time
        if start_time > end_time: 
            await interaction.followup.send(
                "❌ Requested reservation start time is after the requested end time.",
                ephemeral=True
            )
            return
        
        # Validate advance booking (at least 2 days)
        if not self.cog.validate_advance_booking(start_time):
            await interaction.followup.send(
                "❌ Reservations must be made at least 2 days in advance. Please choose a date at least 2 days from today.",
                ephemeral=True
            )
            return
        
        # Check conflicts first
        has_conflict, conflicting_team, conflicting_manager = await self.cog.check_conflicts(start_time, end_time, self.num_pcs)
        if has_conflict:
            await interaction.followup.send(
                f"❌ Conflict with team **{conflicting_team}**. Please contact **{conflicting_manager}** to resolve.",
                ephemeral=True
            )
            return
        
        # Allocate PCs
        allocated_pcs = await self.cog.allocate_pcs(start_time, end_time, self.num_pcs)
        if not allocated_pcs:
            await interaction.followup.send(
                f"❌ Unable to allocate {self.num_pcs} PCs for the requested time slot. Please try a different time or fewer PCs.",
                ephemeral=True
            )
            return
        
        # Check if this is a prime time reservation
        is_prime = self.cog.is_prime_time(start_time, end_time, allocated_pcs)
        
        # If prime time, check quota
        if is_prime:
            has_quota, used_count = await self.cog.check_prime_time_quota(self.team, start_time)
            quota = self.cog.team_prime_time_quota[self.team]
            if not has_quota:
                await interaction.followup.send(
                    f"❌ **{self.team}** has already used all {quota} prime time reservation(s) this week ({used_count}/{quota} used).\n"
                    f"Prime time resets every Monday at 12:00 AM CST.",
                    ephemeral=True
                )
                return
        
        # Save reservation to database
        manager = f"{interaction.user.name}#{interaction.user.discriminator}" if interaction.user.discriminator != "0" else interaction.user.name
        await self.cog.save_reservation(self.team, allocated_pcs, start_time, end_time, manager, is_prime)
        
        # Format PC list for display
        pc_list = ", ".join(PCs.format_pc(pc) for pc in sorted(allocated_pcs, key=lambda x: (x == 0, x)))
        
        # Send confirmation to user
        prime_time_status = "✨ **Prime Time Reservation**" if is_prime else ""
        await interaction.followup.send(
            f"✅ Reservation confirmed!\n\n"
            f"**Team:** {self.team}\n"
            f"**PCs:** {pc_list}\n"
            f"**Time:** {start_time.strftime('%A, %B %d, %Y %I:%M %p')} - {end_time.strftime('%I:%M %p')} CST\n"
            f"**Manager:** {manager}\n"
            f"{prime_time_status}",
            ephemeral=True
        )
        
        # Send notification to nexus-reservations channel
        try:
            # Get the reservations channel from config
            channel_id = config.config["reservations"]["channel"]
            reservations_channel = self.cog.bot.get_channel(channel_id)
            
            if reservations_channel:
                # Determine room type
                back_room_pcs = [pc for pc in allocated_pcs if pc in BACK_ROOM_PCS]
                main_room_pcs = [pc for pc in allocated_pcs if pc in MAIN_ROOM_PCS]
                
                room_info = []
                if back_room_pcs:
                    room_info.append(f"Back Room: {', '.join(PCs.format_pc(pc) for pc in sorted(back_room_pcs))}")
                if main_room_pcs:
                    room_info.append(f"Main Room: {', '.join(PCs.format_pc(pc) for pc in sorted(main_room_pcs))}")
                
                embed = discord.Embed(
                    title="🎮 New PC Reservation",
                    color=discord.Color.from_rgb(78, 42, 132),
                    timestamp=datetime.now(timezone.utc)
                )
                embed.add_field(name="Team", value=self.team, inline=True)
                embed.add_field(name="Manager", value=manager, inline=True)
                embed.add_field(name="Date", value=start_time.strftime('%A, %B %d, %Y'), inline=False)
                embed.add_field(name="Time", value=f"{start_time.strftime('%I:%M %p')} - {end_time.strftime('%I:%M %p')} CST", inline=True)
                embed.add_field(name="PCs", value="\n".join(room_info), inline=False)
                
                if is_prime:
                    embed.add_field(name="Status", value="✨ Prime Time Reservation", inline=False)
                
                await reservations_channel.send(embed=embed)
        except Exception as e:
            print(f"Failed to send notification to nexus-reservations: {e}")


class ReservationView(discord.ui.View):
    def __init__(self, reservations: List[Dict], target_date: datetime, cog: 'PCs'):
        super().__init__(timeout=600)
        self.reservations = reservations
        self.target_date = target_date
        self.cog = cog
        
    def get_hours_for_range(self):
        """Get start/end hours based on day of week"""
        # Friday (4), Saturday (5), Sunday (6) open at noon, else 2pm
        is_weekend = self.target_date.weekday() >= 4
        open_hour = 12 if is_weekend else 14
        return (open_hour, 22, 30)  # Open to close
    
    async def build_embed_and_file(self) -> Tuple[discord.Embed, discord.File]:
        start_hour, end_hour, end_minute = self.get_hours_for_range()
        image_buffer = PCs.build_reservation_image(
            self.reservations,
            self.target_date,
            start_hour,
            end_hour,
            end_minute
        )
        
        embed = discord.Embed(
            title=f"Reservations for {self.target_date.strftime('%A, %B %d, %Y')}",
            color=discord.Color.from_rgb(78, 42, 132),
        )
        embed.set_image(url="attachment://reservations.png")
        embed.set_footer(text="Green = Available · Purple = Reserved")
        
        file = discord.File(image_buffer, filename="reservations.png")
        return embed, file
    
    @discord.ui.button(label="◀ Previous Day", style=discord.ButtonStyle.gray)
    async def previous_day_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        await interaction.response.defer()
        # Go back one day
        new_date = self.target_date - timedelta(days=1)
        date_str = new_date.strftime("%Y-%m-%d")
        
        try:
            data = await self.cog.fetch_reservations(date_str)
            reservations = data.get("reservations", [])
            
            # Update view with new data
            self.target_date = new_date
            self.reservations = reservations
            embed, file = await self.build_embed_and_file()
            
            await interaction.message.edit(embed=embed, file=file, view=self)
        except Exception as e:
            print(e)
            await interaction.followup.send("Failed to fetch reservations for that date.", ephemeral=True)
    
    @discord.ui.button(label="Next Day ▶", style=discord.ButtonStyle.gray)
    async def next_day_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        await interaction.response.defer()
        # Go forward one day
        new_date = self.target_date + timedelta(days=1)
        date_str = new_date.strftime("%Y-%m-%d")
        
        try:
            data = await self.cog.fetch_reservations(date_str)
            reservations = data.get("reservations", [])
            
            # Update view with new data
            self.target_date = new_date
            self.reservations = reservations
            embed, file = await self.build_embed_and_file()
            
            await interaction.message.edit(embed=embed, file=file, view=self)
        except Exception as e:
            print(e)
            await interaction.followup.send("Failed to fetch reservations for that date.", ephemeral=True)


def setup(bot):
    bot.add_cog(PCs(bot))