import asyncio
import io
from datetime import datetime, timedelta, timezone
from typing import Dict, Tuple, List
from zoneinfo import ZoneInfo

import aiohttp
import discord
from discord.ext import commands, tasks
from PIL import Image, ImageDraw, ImageFont

from utils import config
from utils import db


GUILD_ID = config.secrets["discord"]["guild_id"]


GGLEAP_BASE_URL = config.config["apis"]["ggleap"]
PCS_ENDPOINT = f"{GGLEAP_BASE_URL}/machines/uptime"
RESERVATIONS_ENDPOINT = f"{GGLEAP_BASE_URL}/reservations"

# Constants - Use ZoneInfo for proper DST handling
CENTRAL_TZ = ZoneInfo("America/Chicago")
ADVANCE_BOOKING_DAYS = 2
MAX_MAIN_ROOM_PCS = 5
BACK_ROOM_PCS = [0, 14, 15]  # 0 = Streaming, 14 = Back Room 1, 15 = Back Room 2
MAIN_ROOM_PCS = list(range(1, 11))
PRIME_TIME_WEEKDAY_HOUR = 19  # 7 PM
PRIME_TIME_WEEKEND_HOUR = 18  # 6 PM

GAME_HEAD_EMAILS = config.config["gameheads"]
STAFF_LIST = config.config["gameroom"]["staff"]
BOT_DEV_IDS = config.config["bot_devs"]

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


async def reservation_autocomplete(ctx: discord.AutocompleteContext):
    """Autocomplete for user's future reservations"""
    # Format username to match manager field in database
    user = ctx.interaction.user
    manager = (
        f"{user.name}#{user.discriminator}" if user.discriminator != "0" else user.name
    )

    # Query future reservations for this user
    sql = """
        SELECT id, team, start_time
        FROM reservations
        WHERE manager = %s AND start_time > NOW()
        ORDER BY start_time
    """
    rows = await db.fetch_all(sql, (manager,))

    choices = []
    for row in rows:
        res_id, team, start_time = row
        # Format: "Team - Mon, Jan 01 @ 2:00 PM"
        display = f"{team} - {start_time.strftime('%a, %b %d @ %I:%M %p')}"
        choices.append(discord.OptionChoice(name=display, value=str(res_id)))

    return choices


class PCs(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Team to prime time quota mapping
        self.team_prime_time_quota = {
            "Valorant White": 2,
            "Valorant Purple": 1,
            "Overwatch White": 1,
            "Overwatch Purple": 1,
            "League Purple": 1,
            "Apex White": 1,
            "Apex Purple": 1,
            "Rocket League Purple": 1,
            # External events have unlimited prime time quota since they're staff-managed
            "External": 99,
        }
        # Staff ping index for cycling through gameroom staff
        self.staff_ping_index = 0
        # Track reservation messages pending acknowledgment
        # Format: {message_id: {"staff_id": int, "channel_id": int, "sent_at": datetime, "team": str}}
        self.pending_acknowledgments = {}
        # Start background task
        self.check_pending_acknowledgments.start()

    @commands.Cog.listener()
    async def on_reaction_add(self, reaction, user):
        """Remove reservation from pending when staff reacts to acknowledge"""
        if user.bot:
            return
        if reaction.message.id in self.pending_acknowledgments:
            del self.pending_acknowledgments[reaction.message.id]

    @tasks.loop(hours=1)
    async def check_pending_acknowledgments(self):
        """Re-ping staff for reservations that haven't been acknowledged after 24 hours"""
        now = datetime.now(CENTRAL_TZ)
        reminder_threshold = timedelta(hours=24)

        for msg_id, data in list(self.pending_acknowledgments.items()):
            if now - data["sent_at"] > reminder_threshold:
                channel = self.bot.get_channel(data["channel_id"])
                if channel:
                    await channel.send(
                        f"<@{data['staff_id']}> Reminder to make the reservation for **{data['team']}** (react to the message above)"
                    )
                del self.pending_acknowledgments[msg_id]

    @check_pending_acknowledgments.before_loop
    async def before_check_pending_acknowledgments(self):
        """Wait until bot is ready before starting the loop"""
        await self.bot.wait_until_ready()

    @staticmethod
    def format_pc(pc: int) -> str:
        """Format a PC number for display"""
        return "Streaming" if pc == 0 else f"PC {pc}"

    @staticmethod
    def pc_number_to_desk_name(pc_num: int) -> str:
        """Convert database PC number to GGLeap desk name format"""
        if pc_num == 0:
            return "Desk 000 - Streaming"
        return f"Desk {pc_num:03d}"

    @staticmethod
    def to_central_time(dt: datetime) -> datetime:
        """Convert a datetime to Central Time for display/comparison"""
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(CENTRAL_TZ)

    async def get_reservations_in_range(
        self, start_time: datetime, end_time: datetime
    ) -> List[Dict]:
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
            reservations.append(
                {
                    "id": row[0],
                    "team": row[1],
                    "pcs": row[2],
                    "start_time": self.to_central_time(row[3]),
                    "end_time": self.to_central_time(row[4]),
                    "manager": row[5],
                    "is_prime_time": row[6],
                }
            )
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

    async def save_reservation(
        self,
        team: str,
        pcs: List[int],
        start_time: datetime,
        end_time: datetime,
        manager: str,
        is_prime_time: bool,
    ) -> int:
        """Save a reservation to the database and return its ID"""
        sql = """
            INSERT INTO reservations (team, pcs, start_time, end_time, manager, is_prime_time)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
        """
        result = await db.fetch_one(
            sql, (team, pcs, start_time, end_time, manager, is_prime_time)
        )
        return result[0] if result else None

    async def _send_cancellation_notification(
        self,
        team: str,
        pcs: List[int],
        start_time: datetime,
        end_time: datetime,
        cancelled_by: str,
        is_prime_time: bool,
    ):
        """Send cancellation notification to staff channel"""
        try:
            channel_id = config.config["reservations"]["channel"]
            reservations_channel = self.bot.get_channel(channel_id)

            if not reservations_channel:
                return

            # Determine room type breakdown
            back_room_pcs = [pc for pc in pcs if pc in BACK_ROOM_PCS]
            main_room_pcs = [pc for pc in pcs if pc in MAIN_ROOM_PCS]

            room_info = []
            if back_room_pcs:
                room_info.append(
                    f"Back Room: {', '.join(PCs.format_pc(pc) for pc in sorted(back_room_pcs))}"
                )
            if main_room_pcs:
                room_info.append(
                    f"Main Room: {', '.join(PCs.format_pc(pc) for pc in sorted(main_room_pcs))}"
                )

            embed = discord.Embed(
                title="Reservation Cancelled",
                color=discord.Color.red(),
                timestamp=datetime.now(timezone.utc),
            )
            embed.add_field(name="Team", value=team, inline=False)
            embed.add_field(name="Cancelled By", value=cancelled_by, inline=False)
            embed.add_field(
                name="Date",
                value=start_time.strftime("%A, %B %d, %Y"),
                inline=False,
            )
            embed.add_field(
                name="Time",
                value=f"{start_time.strftime('%I:%M %p')} - {end_time.strftime('%I:%M %p')} CST",
                inline=True,
            )
            embed.add_field(name="PCs", value="\n".join(room_info), inline=False)

            if is_prime_time:
                embed.add_field(
                    name="Note", value="This was a Prime Time reservation", inline=False
                )

            # Ping the next staff member in rotation
            if STAFF_LIST:
                staff_id = STAFF_LIST[self.staff_ping_index % len(STAFF_LIST)]
                await reservations_channel.send(f"<@{staff_id}>", embed=embed)
                self.staff_ping_index = (self.staff_ping_index + 1) % len(STAFF_LIST)
            else:
                await reservations_channel.send(embed=embed)
        except Exception as e:
            print(f"Failed to send cancellation notification: {e}")

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
                ephemeral=True,
            )
        else:
            # Re-raise other errors
            raise error

    def parse_time_range(self, time_str: str) -> Tuple[datetime, datetime]:
        """Parse time range string like '2025-10-10 7:00PM-9:00PM' into datetime objects (CST)"""
        # Split date and time range
        try:
            date_part, time_range = time_str.strip().split(" ", 1)
            start_time_str, end_time_str = time_range.split("-")

            # Parse date
            year, month, day = map(int, date_part.split("-"))

            # Parse start time
            start_time = datetime.strptime(start_time_str.strip(), "%I:%M%p")
            start_dt = datetime(
                year, month, day, start_time.hour, start_time.minute, tzinfo=CENTRAL_TZ
            )

            # Parse end time
            end_time = datetime.strptime(end_time_str.strip(), "%I:%M%p")
            end_dt = datetime(
                year, month, day, end_time.hour, end_time.minute, tzinfo=CENTRAL_TZ
            )

            return start_dt, end_dt
        except Exception:
            raise ValueError(
                "Invalid time format. Expected format: 'YYYY-MM-DD H:MMAM/PM-H:MMAM/PM' (e.g., '2025-10-10 7:00PM-9:00PM')"
            )

    def validate_advance_booking(self, start_time: datetime) -> bool:
        """Check if reservation is at least 2 days in advance"""
        now = datetime.now(CENTRAL_TZ)
        days_ahead = (start_time.date() - now.date()).days
        return days_ahead >= ADVANCE_BOOKING_DAYS

    def is_prime_time(
        self, start_time: datetime, end_time: datetime, pcs: List[int]
    ) -> bool:
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
        prime_start = start_time.replace(
            hour=prime_start_hour, minute=0, second=0, microsecond=0
        )

        # If reservation ends before prime time starts, not prime time
        if end_time <= prime_start:
            return False

        # If reservation starts before prime time but extends into it, or starts during prime time, it's prime time
        return True

    def get_week_start(self, dt: datetime) -> datetime:
        """Get the start of the week (Monday 00:00) for a given datetime"""
        days_since_monday = dt.weekday()
        week_start = dt.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(
            days=days_since_monday
        )
        return week_start

    def is_within_open_hours(self, start_time: datetime, end_time: datetime) -> bool:
        """ "Check that reservation is within Gameroom hours (ignoring adjusted hours for now)"""
        # Get day of week and pull correct hours
        day_of_week = start_time.weekday()
        hours = config.config["gameroom"]["default_hours"][day_of_week]

        # Convert to proper format to use parse_time_range
        hours_str = start_time.strftime("%Y-%m-%d") + " " + hours.replace(" ", "")
        gr_start_time, gr_end_time = self.parse_time_range(hours_str)

        # Compare datetimes
        return (
            gr_start_time <= start_time <= gr_end_time
            and gr_start_time <= end_time <= gr_end_time
        )

    async def check_prime_time_quota(
        self, team: str, start_time: datetime
    ) -> Tuple[bool, int]:
        """
        Check if team has prime time slots available.
        Returns (has_quota, used_count)
        """
        used_count = await self.get_team_prime_time_usage(team, start_time)
        quota = self.team_prime_time_quota[team]
        return used_count < quota, used_count

    async def check_conflicts(
        self, start_time: datetime, end_time: datetime, num_pcs: int
    ) -> Tuple[bool, str, str]:
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
            time_points.add(res["start_time"])
            time_points.add(res["end_time"])

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
                if (
                    res["start_time"] < interval_end
                    and res["end_time"] > interval_start
                ):
                    for pc in res["pcs"]:
                        if pc in MAIN_ROOM_PCS:
                            main_room_used += 1
                        elif pc in BACK_ROOM_PCS:
                            back_room_used += 1
                    if conflicting_team is None:
                        conflicting_team = res["team"]
                        conflicting_manager = res["manager"]

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

    async def allocate_pcs(
        self, start_time: datetime, end_time: datetime, num_pcs: int
    ) -> List[int]:
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
                if pc in res["pcs"]:
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
        return await self.fetch_json_with_retries(PCS_ENDPOINT)

    async def fetch_json_with_retries(self, url: str) -> Dict:
        timeout = aiohttp.ClientTimeout(total=10)
        max_attempts = 4
        retry_delay_seconds = 5

        for attempt in range(max_attempts):
            try:
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(url) as resp:
                        resp.raise_for_status()
                        return await resp.json()
            except Exception:
                if attempt == max_attempts - 1:
                    raise
                await asyncio.sleep(retry_delay_seconds)

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
    def build_grid(
        data: Dict, reservations: List[Dict] = None, columns: int = 5
    ) -> Tuple[str, Dict[str, str]]:
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
        items = sorted(
            filtered_data.items(), key=lambda kv: PCs.extract_sort_key(kv[0])
        )

        # Build upcoming reservations map (desk -> minutes until reservation)
        # and currently reserved desks
        upcoming_reservations = {}
        currently_reserved = set()
        if reservations:
            THRESHOLD_MINUTES = 30
            now = datetime.now(CENTRAL_TZ)

            for res in reservations:
                machines = res.get("machines", [])
                start_time_str = res.get("start_time")
                end_time_str = res.get("end_time")
                if not start_time_str or not end_time_str:
                    continue

                start_time = datetime.fromisoformat(start_time_str)
                end_time = datetime.fromisoformat(end_time_str)

                # Check if reservation is currently active
                if start_time <= now <= end_time:
                    for machine in machines:
                        currently_reserved.add(machine)

                # Check if reservation starts soon
                time_diff = (start_time - now).total_seconds() / 60  # minutes
                if 0 < time_diff <= THRESHOLD_MINUTES:
                    for machine in machines:
                        if (
                            machine not in upcoming_reservations
                            or time_diff < upcoming_reservations[machine]
                        ):
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
            should_bold = (
                total_minutes > 120
                and name not in currently_reserved
                and state != "ReadyForUser"
            )

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
            rows.append("\n".join(cells[i : i + columns]))

        return ("\n".join(rows) if rows else "No PCs found.", id_to_state)

    @commands.slash_command(
        name="pcs", description="Show PC statuses as a color grid", guild_ids=[GUILD_ID]
    )
    @commands.cooldown(1, 300, commands.BucketType.user)
    async def pcs(self, ctx):
        await ctx.defer()
        try:
            data = await self.fetch_pcs()
        except Exception as e:
            print(e)
            # Reset cooldown so user can retry
            self.pcs.reset_cooldown(ctx)
            await ctx.followup.send(
                "Failed to fetch PC statuses. Please try again later.", ephemeral=True
            )
            return

        # Fetch reservations for upcoming reservation warnings
        try:
            # Get current time in Central Time
            today = datetime.now(CENTRAL_TZ)
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
            legend_parts.append(
                f"{emoji} {display_name} ({counts.get(normalized_state, 0)})"
            )
        legend = " · ".join(legend_parts)

        embed = discord.Embed(
            title="PC Statuses",
            color=discord.Color.from_rgb(78, 42, 132),
        )
        embed.add_field(name="Legend", value=legend or "No data", inline=False)
        embed.add_field(name="Grid", value=grid, inline=False)
        embed.set_footer(text="Bold text = Can be kicked off (>2hrs, not reserved)")

        await ctx.followup.send(embed=embed)

    @commands.slash_command(
        name="pc",
        description="Get a single PC's state and uptime",
        guild_ids=[GUILD_ID],
    )
    @commands.cooldown(1, 300, commands.BucketType.user)
    async def pc(
        self,
        ctx,
        pc_number: discord.Option(
            str,
            name="pc_number",
            description="PC number (e.g., 1 for Desk 1, 15 for Desk 15)",
            required=True,
        ),
    ):
        await ctx.defer()
        try:
            data = await self.fetch_pcs()
        except Exception:
            await ctx.followup.send(
                "Failed to fetch PC data. Please try again later.", ephemeral=True
            )
            return

        # Fetch reservations to check if PC is currently reserved
        try:
            today = datetime.now(CENTRAL_TZ)
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
        now = datetime.now(CENTRAL_TZ)
        for res in reservations:
            machines = res.get("machines", [])
            if name not in machines:
                continue
            start_time_str = res.get("start_time")
            end_time_str = res.get("end_time")
            if not start_time_str or not end_time_str:
                continue

            start_time = datetime.fromisoformat(start_time_str)
            end_time = datetime.fromisoformat(end_time_str)

            if start_time <= now <= end_time:
                currently_reserved = True
                break

        emoji = STATE_TO_EMOJI.get(state, ":white_large_square:")
        display_state = STATE_TO_NAME.get(state, state)  # Map to friendly name

        # Check if PC can be kicked off (uptime > 2hrs and not reserved)
        total_minutes = (hours * 60) + minutes
        can_kick = (
            total_minutes > 120 and not currently_reserved and state != "ReadyForUser"
        )

        embed = discord.Embed(
            title=name,
            description=f"{emoji} {display_state}",
            color=discord.Color.from_rgb(78, 42, 132),
        )

        uptime_value = (
            f"**{hours}h {minutes}m**" if can_kick else f"{hours}h {minutes}m"
        )
        embed.add_field(name=":clock1: Uptime", value=uptime_value, inline=True)

        if can_kick:
            embed.add_field(
                name="⚠️ Status",
                value="Can be kicked off (>2hrs, not reserved)",
                inline=False,
            )

        await ctx.followup.send(embed=embed)

    @commands.slash_command(
        name="reservations",
        description="Show PC reservations for a date",
        guild_ids=[GUILD_ID],
    )
    async def reservations(
        self,
        ctx,
        date: discord.Option(
            str,
            name="date",
            description="Date in YYYY-MM-DD format (default: today)",
            required=False,
        ),
    ):
        await ctx.defer()

        # Parse or default to today (in Central Time)
        if date:
            try:
                target_date = datetime.strptime(date, "%Y-%m-%d")
                target_date = target_date.replace(tzinfo=CENTRAL_TZ)
            except ValueError:
                await ctx.followup.send(
                    "Invalid date format. Please use YYYY-MM-DD (e.g., 2025-09-30)",
                    ephemeral=True,
                )
                return
        else:
            target_date = datetime.now(CENTRAL_TZ)

        date_str = target_date.strftime("%Y-%m-%d")

        # Fetch GGLeap reservations
        try:
            data = await self.fetch_reservations(date_str)
        except Exception as e:
            print(e)
            await ctx.followup.send(
                "Failed to fetch reservations. Please try again later.", ephemeral=True
            )
            return

        ggleap_reservations = data.get("reservations", [])

        # Fetch database reservations for the same day
        start_of_day = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = target_date.replace(
            hour=23, minute=59, second=59, microsecond=999999
        )
        db_reservations = await self.get_reservations_in_range(start_of_day, end_of_day)

        # Process database reservations to find external and pending
        external_as_ggleap, pending_reservations = self._process_db_reservations(
            db_reservations, ggleap_reservations
        )

        # Combine GGLeap reservations with external reservations for display
        combined_reservations = ggleap_reservations + external_as_ggleap

        # If no reservations at all (GGLeap, external, or pending)
        if not combined_reservations and not pending_reservations:
            embed = discord.Embed(
                title=f"Reservations for {target_date.strftime('%A, %B %d, %Y')}",
                description="No reservations found for this date.",
                color=discord.Color.from_rgb(78, 42, 132),
            )
            await ctx.followup.send(embed=embed)
            return

        # Build timeline view with interactive date navigation
        view = ReservationView(
            combined_reservations, target_date, self, pending_reservations
        )
        embeds, file = await view.build_embed_and_file()

        await ctx.followup.send(embeds=embeds, file=file, view=view)

    def _find_pending_pcs(
        self, db_res: Dict, ggleap_reservations: List[Dict]
    ) -> List[int]:
        """
        Find which PCs from a database reservation are NOT yet in GGLeap.
        Returns list of PC numbers that are pending (not in GGLeap).
        """
        db_start = self.to_central_time(db_res["start_time"])
        db_end = self.to_central_time(db_res["end_time"])

        # Track which PCs are covered in GGLeap
        covered_pcs = set()

        for gg_res in ggleap_reservations:
            gg_desks = set(gg_res.get("machines", []))
            gg_start = self.to_central_time(
                datetime.fromisoformat(gg_res["start_time"])
            )
            gg_end = self.to_central_time(datetime.fromisoformat(gg_res["end_time"]))

            # Check if times overlap (within 5 minutes tolerance)
            time_tolerance = 300  # 5 minutes in seconds
            if (
                abs((db_start - gg_start).total_seconds()) < time_tolerance
                and abs((db_end - gg_end).total_seconds()) < time_tolerance
            ):
                # Find which DB PCs are in this GGLeap reservation
                for pc in db_res["pcs"]:
                    desk_name = PCs.pc_number_to_desk_name(pc)
                    if desk_name in gg_desks:
                        covered_pcs.add(pc)

        # Return PCs that are NOT covered
        pending_pcs = [pc for pc in db_res["pcs"] if pc not in covered_pcs]
        return pending_pcs

    def _process_db_reservations(
        self, db_reservations: List[Dict], ggleap_reservations: List[Dict]
    ) -> Tuple[List[Dict], List[Dict]]:
        """
        Process database reservations to separate external and pending reservations.

        Args:
            db_reservations: Reservations from the database
            ggleap_reservations: Reservations from GGLeap API

        Returns:
            Tuple of (external_as_ggleap, pending_reservations)
            - external_as_ggleap: External reservations converted to GGLeap format
            - pending_reservations: Team reservations not yet in GGLeap
        """
        pending_reservations = []
        external_as_ggleap = []

        for db_res in db_reservations:
            # External reservations are treated as if they're in GGLeap (all PCs booked)
            if db_res["team"] == "External":
                # Convert external reservation to GGLeap format for display
                all_desk_names = [
                    PCs.pc_number_to_desk_name(pc) for pc in db_res["pcs"]
                ]
                external_as_ggleap.append(
                    {
                        "machines": all_desk_names,
                        "start_time": db_res["start_time"].isoformat(),
                        "end_time": db_res["end_time"].isoformat(),
                    }
                )
                continue

            # Find which PCs from this reservation are not yet in GGLeap
            pending_pcs = self._find_pending_pcs(db_res, ggleap_reservations)
            if pending_pcs:
                # Create a copy with only the pending PCs
                pending_res = db_res.copy()
                pending_res["pcs"] = pending_pcs
                pending_reservations.append(pending_res)

        return external_as_ggleap, pending_reservations

    async def fetch_reservations(self, date_str: str) -> Dict:
        url = f"{RESERVATIONS_ENDPOINT}/{date_str}"
        return await self.fetch_json_with_retries(url)

    @commands.slash_command(
        name="reserve", description="Reserve PCs for your team", guild_ids=[GUILD_ID]
    )
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
                "Apex Purple",
                "Rocket League Purple",
            ],
            required=True,
        ),
        num_pcs: discord.Option(
            int,
            name="num_pcs",
            description="Number of PCs to reserve (1-8)",
            min_value=1,
            max_value=8,
            required=True,
        ),
        res_type: discord.Option(
            str,
            name="type",
            description="Scrim or match",
            choices=["Scrim", "Match"],
            required=True,
        ),
    ):
        # Check if user is a bot dev
        is_bot_dev = ctx.author.id in BOT_DEV_IDS

        # Check if user has required role (skip if bot dev)
        if not is_bot_dev:
            allowed_role_ids = config.config["reservations"]["roles"]
            user_role_ids = [role.id for role in ctx.author.roles]

            if not any(role_id in allowed_role_ids for role_id in user_role_ids):
                await ctx.respond(
                    "❌ You don't have permission to reserve PCs. Contact a team manager.",
                    ephemeral=True,
                )
                return

        # Show modal for time input
        modal = ReservationTimeModal(self, team, num_pcs, res_type, is_bot_dev)
        await ctx.send_modal(modal)

    @commands.slash_command(
        name="reserve-external",
        description="Reserve all PCs for external event (staff only)",
        guild_ids=[GUILD_ID],
    )
    async def reserve_external(self, ctx):
        # Check if user is staff
        if ctx.author.id not in STAFF_LIST:
            await ctx.respond(
                "❌ Only game room staff can make external reservations.",
                ephemeral=True,
            )
            return

        # Show modal for date/time input
        modal = ExternalReservationTimeModal(self)
        await ctx.send_modal(modal)

    @commands.slash_command(
        name="cancel-reservation",
        description="Cancel one of your PC reservations",
        guild_ids=[GUILD_ID],
    )
    async def cancel_reservation(
        self,
        ctx,
        reservation: discord.Option(
            str,
            name="reservation",
            description="Select a reservation to cancel",
            autocomplete=reservation_autocomplete,
            required=True,
        ),
    ):
        # Check if user is a bot dev
        is_bot_dev = ctx.author.id in BOT_DEV_IDS

        # Check if user has required role (skip if bot dev)
        if not is_bot_dev:
            allowed_role_ids = config.config["reservations"]["roles"]
            user_role_ids = [role.id for role in ctx.author.roles]

            if not any(role_id in allowed_role_ids for role_id in user_role_ids):
                await ctx.respond(
                    "You don't have permission to cancel reservations.",
                    ephemeral=True,
                )
                return

        await ctx.defer(ephemeral=True)

        # Parse reservation ID from autocomplete selection
        try:
            reservation_id = int(reservation)
        except ValueError:
            await ctx.followup.send(
                "Invalid reservation selection. Please select from the dropdown.",
                ephemeral=True,
            )
            return

        # Fetch reservation details
        sql = """
            SELECT id, team, pcs, start_time, end_time, manager, is_prime_time
            FROM reservations
            WHERE id = %s
        """
        row = await db.fetch_one(sql, (reservation_id,))

        if not row:
            await ctx.followup.send(
                "Reservation not found. It may have already been cancelled.",
                ephemeral=True,
            )
            return

        res_id, team, pcs, start_time, end_time, manager, is_prime_time = row

        # Format current user's username
        user = ctx.author
        current_user = (
            f"{user.name}#{user.discriminator}"
            if user.discriminator != "0"
            else user.name
        )

        # Verify ownership (skip if bot dev)
        if not is_bot_dev and manager != current_user:
            await ctx.followup.send(
                "You can only cancel your own reservations.",
                ephemeral=True,
            )
            return

        # Verify reservation is in the future
        now = datetime.now(CENTRAL_TZ)
        if start_time <= now:
            await ctx.followup.send(
                "Cannot cancel a reservation that has already started or passed.",
                ephemeral=True,
            )
            return

        # Delete the reservation
        delete_sql = "DELETE FROM reservations WHERE id = %s"
        await db.perform_one(delete_sql, (reservation_id,))

        # Format PC list for confirmation message
        pc_list = ", ".join(
            PCs.format_pc(pc) for pc in sorted(pcs, key=lambda x: (x == 0, x))
        )

        # Build confirmation message
        prime_time_note = (
            "\n\nYour prime time slot has been restored." if is_prime_time else ""
        )
        await ctx.followup.send(
            f"Reservation cancelled successfully.\n\n"
            f"**Team:** {team}\n"
            f"**PCs:** {pc_list}\n"
            f"**Time:** {start_time.strftime('%A, %B %d, %Y %I:%M %p')} - {end_time.strftime('%I:%M %p')} CST"
            f"{prime_time_note}",
            ephemeral=True,
        )

        # Send cancellation notification to staff
        await self._send_cancellation_notification(
            team, pcs, start_time, end_time, current_user, is_prime_time
        )

    @staticmethod
    def build_reservation_image(
        reservations: List[Dict],
        target_date: datetime,
        start_hour: int,
        end_hour: int,
        end_minute: int = 0,
        pending_reservations: List[Dict] = None,
    ) -> io.BytesIO:
        """Build a 2D grid image with time slots (x-axis) and desks (y-axis)

        Args:
            reservations: GGLeap format reservations (confirmed/in system)
            target_date: Date to display
            start_hour: Start hour for grid
            end_hour: End hour for grid
            end_minute: End minute for grid
            pending_reservations: Database format reservations not yet in GGLeap (shown in orange)
        """

        # Define desks to show: 1-10, 14, 15, and Streaming
        all_desks = [f"Desk {i:03d}" for i in range(1, 11)] + [
            "Desk 014",
            "Desk 015",
            "Desk 000 - Streaming",
        ]

        # Build time slots from start_hour to end_hour:end_minute in 30-minute increments
        time_slots = []
        base_date = target_date.replace(
            hour=start_hour, minute=0, second=0, microsecond=0, tzinfo=CENTRAL_TZ
        )
        end_time = target_date.replace(
            hour=end_hour, minute=end_minute, second=0, microsecond=0, tzinfo=CENTRAL_TZ
        )

        current_time = base_date
        while current_time <= end_time:
            time_slots.append(current_time)
            current_time += timedelta(minutes=30)

        # Initialize grid: desk -> dict with 'reserved' and 'pending' sets of time slot indices
        desk_reservations = {
            desk: {"reserved": set(), "pending": set()} for desk in all_desks
        }

        # Process GGLeap reservations (confirmed - purple)
        for res in reservations:
            machines = res.get("machines", [])

            start_time = PCs.to_central_time(
                datetime.fromisoformat(res.get("start_time"))
            )
            end_time = PCs.to_central_time(datetime.fromisoformat(res.get("end_time")))

            # Mark time slots as reserved for each machine
            for machine in machines:
                if machine not in desk_reservations:
                    continue

                # Find which time slots are covered
                for slot_idx, slot_time in enumerate(time_slots):
                    slot_end = slot_time + timedelta(minutes=30)
                    # Check if this slot overlaps with the reservation
                    if start_time < slot_end and end_time > slot_time:
                        desk_reservations[machine]["reserved"].add(slot_idx)

        # Process pending reservations (database format - orange)
        if pending_reservations:
            for res in pending_reservations:
                pcs = res.get("pcs", [])
                start_time = PCs.to_central_time(res.get("start_time"))
                end_time = PCs.to_central_time(res.get("end_time"))

                # Mark time slots as pending for each PC
                for pc_num in pcs:
                    desk_name = PCs.pc_number_to_desk_name(pc_num)
                    if desk_name not in desk_reservations:
                        continue

                    # Find which time slots are covered
                    for slot_idx, slot_time in enumerate(time_slots):
                        slot_end = slot_time + timedelta(minutes=30)
                        # Check if this slot overlaps with the reservation
                        if start_time < slot_end and end_time > slot_time:
                            # Only mark as pending if not already reserved (purple takes precedence)
                            if slot_idx not in desk_reservations[desk_name]["reserved"]:
                                desk_reservations[desk_name]["pending"].add(slot_idx)

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
        pending_color = (255, 165, 0)  # Orange

        # Create image
        img = Image.new("RGB", (width, height), bg_color)
        draw = ImageDraw.Draw(img)

        # Try to load a font, fallback to default if not available
        try:
            font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 14)
            small_font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 12)
        except Exception:
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
            reserved_slots = desk_reservations[desk]["reserved"]
            pending_slots = desk_reservations[desk]["pending"]
            for slot_idx in range(len(time_slots)):
                x = label_width + (slot_idx * cell_size)

                # Determine color: purple (reserved) > orange (pending) > green (available)
                if slot_idx in reserved_slots:
                    color = reserved_color
                elif slot_idx in pending_slots:
                    color = pending_color
                else:
                    color = available_color

                # Draw filled rectangle
                draw.rectangle(
                    [x, y, x + cell_size - 2, y + cell_size - 2],
                    fill=color,
                    outline=grid_color,
                )

        # Save to BytesIO
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        buffer.seek(0)
        return buffer


class ReservationTimeModal(discord.ui.Modal):
    def __init__(
        self,
        cog: "PCs",
        team: str,
        num_pcs: int,
        res_type: str,
        is_bot_dev: bool = False,
    ):
        super().__init__(title="Reserve PCs - Set Time")
        self.cog = cog
        self.team = team
        self.num_pcs = num_pcs
        self.res_type = res_type
        self.is_bot_dev = is_bot_dev

        # Calculate example date as today + 2 days (minimum advance booking)
        example_date = (datetime.now(CENTRAL_TZ) + timedelta(days=2)).strftime(
            "%Y-%m-%d"
        )
        self.add_item(
            discord.ui.InputText(
                label="Date",
                placeholder=f"YYYY-MM-DD (e.g., {example_date})",
                style=discord.InputTextStyle.short,
                required=True,
            )
        )

        self.add_item(
            discord.ui.InputText(
                label="Start Time",
                placeholder="H:MMAM/PM (e.g., 7:00PM)",
                style=discord.InputTextStyle.short,
                required=True,
            )
        )

        self.add_item(
            discord.ui.InputText(
                label="End Time",
                placeholder="H:MMAM/PM (e.g., 9:00PM)",
                style=discord.InputTextStyle.short,
                required=True,
            )
        )

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
                ephemeral=True,
            )
            return

        # Ensure reservation is within Gameroom hours
        if not self.cog.is_within_open_hours(start_time, end_time):
            await interaction.followup.send(
                "❌ Requested reservation is not within Gameroom hours.", ephemeral=True
            )
            return

        # Validate advance booking (at least 2 days)
        if not self.cog.validate_advance_booking(start_time):
            await interaction.followup.send(
                "❌ Reservations must be made at least 2 days in advance. Please choose a date at least 2 days from today.",
                ephemeral=True,
            )
            return

        # Check conflicts first
        (
            has_conflict,
            conflicting_team,
            conflicting_manager,
        ) = await self.cog.check_conflicts(start_time, end_time, self.num_pcs)
        if has_conflict:
            await interaction.followup.send(
                f"❌ Conflict with team **{conflicting_team}**. Please contact **{conflicting_manager}** to resolve.",
                ephemeral=True,
            )
            return

        # Allocate PCs
        allocated_pcs = await self.cog.allocate_pcs(start_time, end_time, self.num_pcs)
        if not allocated_pcs:
            await interaction.followup.send(
                f"❌ Unable to allocate {self.num_pcs} PCs for the requested time slot. Please try a different time or fewer PCs.",
                ephemeral=True,
            )
            return

        # Check if this is a prime time reservation
        is_prime = self.cog.is_prime_time(start_time, end_time, allocated_pcs)

        # Check if reservation is longer than 2 hours
        is_over_2_hours = False
        if end_time > start_time + timedelta(hours=2):
            is_over_2_hours = True

        # If prime time, check quota (skip for bot devs)
        if is_prime and not self.is_bot_dev:
            has_quota, used_count = await self.cog.check_prime_time_quota(
                self.team, start_time
            )
            quota = self.cog.team_prime_time_quota[self.team]
            if not has_quota:
                await interaction.followup.send(
                    f"❌ **{self.team}** has already used all {quota} prime time reservation(s) this week ({used_count}/{quota} used).\n"
                    f"Prime time resets every Monday at 12:00 AM CST.",
                    ephemeral=True,
                )
                return

        # Save reservation to database (skip for bot devs)
        manager = (
            f"{interaction.user.name}#{interaction.user.discriminator}"
            if interaction.user.discriminator != "0"
            else interaction.user.name
        )
        if not self.is_bot_dev:
            await self.cog.save_reservation(
                self.team, allocated_pcs, start_time, end_time, manager, is_prime
            )

        # Format PC list for display
        pc_list = ", ".join(
            PCs.format_pc(pc) for pc in sorted(allocated_pcs, key=lambda x: (x == 0, x))
        )

        # Send confirmation to user
        prime_time_status = "✨ **Prime Time Reservation**" if is_prime else ""
        test_status = (
            "🧪 **Test Reservation** (Not saved to database)" if self.is_bot_dev else ""
        )
        await interaction.followup.send(
            f"✅ Reservation confirmed!\n\n"
            f"**Team:** {self.team}\n"
            f"**PCs:** {pc_list}\n"
            f"**Time:** {start_time.strftime('%A, %B %d, %Y %I:%M %p')} - {end_time.strftime('%I:%M %p')} CST\n"
            f"**Manager:** {manager}\n"
            f"{prime_time_status}\n"
            f"{test_status}",
            ephemeral=True,
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
                    room_info.append(
                        f"Back Room: {', '.join(PCs.format_pc(pc) for pc in sorted(back_room_pcs))}"
                    )
                if main_room_pcs:
                    room_info.append(
                        f"Main Room: {', '.join(PCs.format_pc(pc) for pc in sorted(main_room_pcs))}"
                    )

                embed = discord.Embed(
                    title="🎮 New PC Reservation",
                    color=discord.Color.from_rgb(78, 42, 132),
                    timestamp=datetime.now(timezone.utc),
                )
                embed.add_field(name="Team", value=self.team, inline=False)
                embed.add_field(name="Res Type", value=self.res_type, inline=False)
                embed.add_field(
                    name="Manager Email",
                    value=GAME_HEAD_EMAILS.get(manager, "Email not found"),
                    inline=False,
                )
                embed.add_field(name="Manager", value=manager, inline=False)
                embed.add_field(
                    name="Date",
                    value=start_time.strftime("%A, %B %d, %Y"),
                    inline=False,
                )
                embed.add_field(
                    name="Time",
                    value=f"{start_time.strftime('%I:%M %p')} - {end_time.strftime('%I:%M %p')} CST",
                    inline=True,
                )
                embed.add_field(name="PCs", value="\n".join(room_info), inline=False)

                if is_prime:
                    embed.add_field(
                        name="Status", value="✨ Prime Time Reservation", inline=False
                    )

                if self.is_bot_dev:
                    embed.add_field(
                        name="Status",
                        value="Test Reservation (Not saved to database)",
                        inline=False,
                    )

                if is_prime and is_over_2_hours:
                    embed.add_field(
                        name="Notes",
                        value="‼️ Prime Time Reservation longer than 2 Hours",
                        inline=False,
                    )

                # Ping the next staff member in rotation
                if STAFF_LIST:
                    staff_id = STAFF_LIST[self.cog.staff_ping_index % len(STAFF_LIST)]
                    msg = await reservations_channel.send(f"<@{staff_id}>", embed=embed)
                    # Track for acknowledgment
                    self.cog.pending_acknowledgments[msg.id] = {
                        "staff_id": staff_id,
                        "channel_id": reservations_channel.id,
                        "sent_at": datetime.now(CENTRAL_TZ),
                        "team": self.team,
                    }
                    self.cog.staff_ping_index = (self.cog.staff_ping_index + 1) % len(
                        STAFF_LIST
                    )
                else:
                    await reservations_channel.send(embed=embed)
        except Exception as e:
            print(f"Failed to send notification to nexus-reservations: {e}")


class ExternalReservationTimeModal(discord.ui.Modal):
    def __init__(self, cog: "PCs"):
        super().__init__(title="External Reservation - Set Time")
        self.cog = cog

        # Calculate example date as today (no advance booking requirement for external)
        example_date = datetime.now(CENTRAL_TZ).strftime("%Y-%m-%d")
        self.add_item(
            discord.ui.InputText(
                label="Date",
                placeholder=f"YYYY-MM-DD (e.g., {example_date})",
                style=discord.InputTextStyle.short,
                required=True,
            )
        )

        self.add_item(
            discord.ui.InputText(
                label="Start Time",
                placeholder="H:MMAM/PM (e.g., 7:00PM)",
                style=discord.InputTextStyle.short,
                required=True,
            )
        )

        self.add_item(
            discord.ui.InputText(
                label="End Time",
                placeholder="H:MMAM/PM (e.g., 9:00PM)",
                style=discord.InputTextStyle.short,
                required=True,
            )
        )

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
                ephemeral=True,
            )
            return

        # Skip advance booking requirement for external reservations (staff flexibility)
        # Skip gameroom hours check for external reservations (special events may be outside hours)

        # External reservations reserve ALL PCs
        all_pcs = BACK_ROOM_PCS + MAIN_ROOM_PCS  # 13 total PCs

        # Check for ANY existing reservations in the time slot
        overlapping = await self.cog.get_reservations_in_range(start_time, end_time)
        if overlapping:
            # Build conflict message
            conflict_teams = list(set(res["team"] for res in overlapping))
            await interaction.followup.send(
                f"❌ Cannot reserve all PCs - existing reservations conflict with this time slot.\n"
                f"**Conflicting teams:** {', '.join(conflict_teams)}\n"
                f"Please choose a different time or coordinate with the teams.",
                ephemeral=True,
            )
            return

        # Check if this is a prime time reservation
        is_prime = self.cog.is_prime_time(start_time, end_time, all_pcs)

        # Save reservation to database
        manager = (
            f"{interaction.user.name}#{interaction.user.discriminator}"
            if interaction.user.discriminator != "0"
            else interaction.user.name
        )
        await self.cog.save_reservation(
            "External", all_pcs, start_time, end_time, manager, is_prime
        )

        # Format PC list for display
        pc_list = ", ".join(
            PCs.format_pc(pc) for pc in sorted(all_pcs, key=lambda x: (x == 0, x))
        )

        # Send confirmation to user
        await interaction.followup.send(
            f"✅ External reservation confirmed!\n\n"
            f"**Event Type:** External Event\n"
            f"**PCs:** {pc_list}\n"
            f"**Time:** {start_time.strftime('%A, %B %d, %Y %I:%M %p')} - {end_time.strftime('%I:%M %p')} CST\n"
            f"**Reserved by:** {manager}",
            ephemeral=True,
        )

        # Skip staff notification since staff is already making the reservation


class ReservationView(discord.ui.View):
    def __init__(
        self,
        reservations: List[Dict],
        target_date: datetime,
        cog: "PCs",
        pending_reservations: List[Dict] = None,
    ):
        super().__init__(timeout=600)
        self.reservations = reservations
        self.target_date = target_date
        self.cog = cog
        self.pending_reservations = pending_reservations or []

    def get_hours_for_range(self):
        """Get start/end hours based on day of week"""
        # Friday (4), Saturday (5), Sunday (6) open at noon, else 2pm
        is_weekend = self.target_date.weekday() >= 4
        open_hour = 12 if is_weekend else 14
        return (open_hour, 22, 30)  # Open to close

    async def build_embed_and_file(self) -> Tuple[List[discord.Embed], discord.File]:
        start_hour, end_hour, end_minute = self.get_hours_for_range()
        image_buffer = PCs.build_reservation_image(
            self.reservations,
            self.target_date,
            start_hour,
            end_hour,
            end_minute,
            self.pending_reservations,
        )

        embeds = []

        # Main embed with image
        main_embed = discord.Embed(
            title=f"Reservations for {self.target_date.strftime('%A, %B %d, %Y')}",
            color=discord.Color.from_rgb(78, 42, 132),
        )
        main_embed.set_image(url="attachment://reservations.png")
        main_embed.set_footer(
            text="Green = Available · Purple = Reserved · Orange = Pending (not in GGLeap)"
        )
        embeds.append(main_embed)

        # Add separate embed for pending reservations (appears below the image)
        if self.pending_reservations:
            pending_embed = discord.Embed(
                title="⚠️ Pending Reservations (not yet in GGLeap)",
                color=discord.Color.orange(),
            )
            for res in self.pending_reservations:
                pc_list = ", ".join(
                    PCs.format_pc(pc)
                    for pc in sorted(res["pcs"], key=lambda x: (x == 0, x))
                )
                start_time = PCs.to_central_time(res["start_time"])
                end_time = PCs.to_central_time(res["end_time"])

                field_value = (
                    f"**Team:** {res['team']}\n"
                    f"**PCs:** {pc_list}\n"
                    f"**Time:** {start_time.strftime('%I:%M %p')} - {end_time.strftime('%I:%M %p')} CST\n"
                    f"**Manager:** {res['manager']}"
                )
                pending_embed.add_field(
                    name="\u200b",  # Zero-width space for no field name
                    value=field_value,
                    inline=False,
                )
            embeds.append(pending_embed)

        file = discord.File(image_buffer, filename="reservations.png")
        return embeds, file

    async def _fetch_and_update(self, new_date: datetime):
        """Fetch reservations for a new date and update the view state.

        Raises:
            Exception: If fetching reservations fails
        """
        date_str = new_date.strftime("%Y-%m-%d")

        # Fetch GGLeap reservations (may raise on network/API errors)
        data = await self.cog.fetch_reservations(date_str)
        ggleap_reservations = data.get("reservations", [])

        # Fetch database reservations
        start_of_day = new_date.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = new_date.replace(hour=23, minute=59, second=59, microsecond=999999)
        db_reservations = await self.cog.get_reservations_in_range(
            start_of_day, end_of_day
        )

        # Process database reservations to find external and pending
        external_as_ggleap, pending_reservations = self.cog._process_db_reservations(
            db_reservations, ggleap_reservations
        )

        combined_reservations = ggleap_reservations + external_as_ggleap

        # Update view state
        self.target_date = new_date
        self.reservations = combined_reservations
        self.pending_reservations = pending_reservations

    @discord.ui.button(label="◀ Previous Day", style=discord.ButtonStyle.gray)
    async def previous_day_button(
        self, button: discord.ui.Button, interaction: discord.Interaction
    ):
        await interaction.response.defer()
        new_date = self.target_date - timedelta(days=1)

        try:
            await self._fetch_and_update(new_date)
            embeds, file = await self.build_embed_and_file()
            await interaction.message.edit(embeds=embeds, file=file, view=self)
        except Exception as e:
            print(e)
            await interaction.followup.send(
                "Failed to fetch reservations for that date.", ephemeral=True
            )

    @discord.ui.button(label="Next Day ▶", style=discord.ButtonStyle.gray)
    async def next_day_button(
        self, button: discord.ui.Button, interaction: discord.Interaction
    ):
        await interaction.response.defer()
        new_date = self.target_date + timedelta(days=1)

        try:
            await self._fetch_and_update(new_date)
            embeds, file = await self.build_embed_and_file()
            await interaction.message.edit(embeds=embeds, file=file, view=self)
        except Exception as e:
            print(e)
            await interaction.followup.send(
                "Failed to fetch reservations for that date.", ephemeral=True
            )


def setup(bot):
    bot.add_cog(PCs(bot))
