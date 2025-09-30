import asyncio
import io
from datetime import datetime, timedelta, timezone
from typing import Dict, Tuple, List

import aiohttp
import discord
from discord.ext import commands
from PIL import Image, ImageDraw, ImageFont

from utils import config


GUILD_ID = config.secrets["discord"]["guild_id"]


GGLEAP_BASE_URL = config.config["apis"]["ggleap"]
PCS_ENDPOINT = f"{GGLEAP_BASE_URL}/machines/uptime"
RESERVATIONS_ENDPOINT = f"{GGLEAP_BASE_URL}/reservations"


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
    def build_grid(data: Dict, columns: int = 5) -> Tuple[str, Dict[str, str]]:
        # Returns (grid_text, id_to_state)
        # Filter out SAIT TEST machine
        filtered_data = {k: v for k, v in data.items() if not k.startswith("SAIT TEST")}
        items = sorted(filtered_data.items(), key=lambda kv: PCs.extract_sort_key(kv[0]))

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
            
            cells.append(f"{emoji} `{short}` {hours}h {minutes}m")

        # Build rows
        rows = []
        for i in range(0, len(cells), columns):
            rows.append("\n".join(cells[i:i+columns]))

        return ("\n".join(rows) if rows else "No PCs found.", id_to_state)

    @commands.slash_command(name="pcs", description="Show PC statuses as a color grid", guild_ids=[GUILD_ID])
    async def pcs(self, ctx):
        await ctx.defer()
        try:
            data = await self.fetch_pcs()
        except Exception as e:
            print(e)
            await ctx.followup.send("Failed to fetch PC statuses. Please try again later.", ephemeral=True)
            return

        grid, id_to_state = self.build_grid(data)

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

        await ctx.followup.send(embed=embed)

    @commands.slash_command(name="pc", description="Get a single PC's state and uptime", guild_ids=[GUILD_ID])
    async def pc(self, ctx, pc_number: discord.Option(str, name="pc_number", description="PC number (e.g., 1 for Desk 1, 15 for Desk 15)", required=True)):
        await ctx.defer()
        try:
            data = await self.fetch_pcs()
        except Exception as e:
            await ctx.followup.send("Failed to fetch PC data. Please try again later.", ephemeral=True)
            return

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

        emoji = STATE_TO_EMOJI.get(state, ":white_large_square:")
        display_state = STATE_TO_NAME.get(state, state)  # Map to friendly name
        
        embed = discord.Embed(
            title=name,
            description=f"{emoji} {display_state}",
            color=discord.Color.from_rgb(78, 42, 132),
        )
        embed.add_field(name=":clock1: Uptime", value=f"{hours}h {minutes}m", inline=True)

        await ctx.followup.send(embed=embed)

    @commands.slash_command(name="reservations", description="Show PC reservations for a date", guild_ids=[GUILD_ID])
    async def reservations(
        self,
        ctx,
        date: discord.Option(str, name="date", description="Date in YYYY-MM-DD format (default: today)", required=False)
    ):
        await ctx.defer()
        
        # Parse or default to today
        if date:
            try:
                target_date = datetime.strptime(date, "%Y-%m-%d")
            except ValueError:
                await ctx.followup.send("Invalid date format. Please use YYYY-MM-DD (e.g., 2025-09-30)", ephemeral=True)
                return
        else:
            target_date = datetime.now()
        
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

    @staticmethod
    def build_reservation_image(reservations: List[Dict], target_date: datetime, start_hour: int, end_hour: int, end_minute: int = 0) -> io.BytesIO:
        """Build a 2D grid image with time slots (x-axis) and desks (y-axis)"""
        # CST is UTC-6
        cst_offset = timezone(timedelta(hours=-6))
        
        # Define all desks in order
        all_desks = [f"Desk {i:03d}" for i in range(1, 16)] + ["Desk 000 - Streaming"]
        
        # Build time slots from start_hour to end_hour:end_minute in 30-minute increments
        time_slots = []
        base_date = target_date.replace(hour=start_hour, minute=0, second=0, microsecond=0, tzinfo=cst_offset)
        end_time = target_date.replace(hour=end_hour, minute=end_minute, second=0, microsecond=0, tzinfo=cst_offset)
        
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
            
            # If times are naive, assume UTC
            if start_utc.tzinfo is None:
                start_utc = start_utc.replace(tzinfo=timezone.utc)
            if end_utc.tzinfo is None:
                end_utc = end_utc.replace(tzinfo=timezone.utc)
            
            # Convert to CST
            start_cst = start_utc.astimezone(cst_offset)
            end_cst = end_utc.astimezone(cst_offset)
            
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
            
            await interaction.message.delete()
            await interaction.followup.send(embed=embed, file=file, view=self)
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
            
            await interaction.message.delete()
            await interaction.followup.send(embed=embed, file=file, view=self)
        except Exception as e:
            print(e)
            await interaction.followup.send("Failed to fetch reservations for that date.", ephemeral=True)


def setup(bot):
    bot.add_cog(PCs(bot))