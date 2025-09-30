import asyncio
from datetime import datetime, timedelta
from typing import Dict, Tuple, List

import aiohttp
import discord
from discord.ext import commands

from utils import config


GUILD_ID = config.secrets["discord"]["guild_id"]


PCS_ENDPOINT = config.config["apis"]["uptime"]
RESERVATIONS_ENDPOINT = config.config["apis"]["reservations"]


STATE_TO_EMOJI = {
    "ReadyForUser": ":green_square:",
    "UserLoggedIn": ":red_square:",
    "AdminMode": ":red_square:",
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
    async def pc(self, ctx, pcid: discord.Option(str, name="pcid", description="e.g., Desk 009", required=True)):
        await ctx.defer()
        try:
            data = await self.fetch_pcs()
        except Exception as e:
            await ctx.followup.send("Failed to fetch PC data. Please try again later.", ephemeral=True)
            return

        # Attempt exact and case-insensitive matches
        target = None
        norm = self.normalize_key(pcid)
        for key, value in data.items():
            if self.normalize_key(key) == norm:
                target = (key, value)
                break
        if target is None:
            # Fallback: if user provides just digits, try to match "Desk XXX"
            digits = "".join(ch for ch in pcid if ch.isdigit())
            if digits:
                desired = f"desk {int(digits):03d}"
                for key, value in data.items():
                    if self.normalize_key(key).startswith(desired):
                        target = (key, value)
                        break

        if target is None:
            await ctx.followup.send(f"PC `{pcid}` not found.", ephemeral=True)
            return

        name, info = target
        state = info.get("state", "Unknown")
        uptime = info.get("uptime", {})
        hours = uptime.get("hours", 0)
        minutes = uptime.get("minutes", 0)

        emoji = STATE_TO_EMOJI.get(state, ":white_large_square:")
        embed = discord.Embed(
            title=name,
            description=f"{emoji} {state}",
            color=discord.Color.from_rgb(78, 42, 132),
        )
        embed.add_field(name=":clock1: Uptime", value=f"{hours}h {minutes}m", inline=True)
        embed.set_footer(text="Source: ggleap")

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
        
        # Build timeline view
        timeline = self.build_reservation_timeline(reservations, target_date)
        
        embed = discord.Embed(
            title=f"Reservations for {target_date.strftime('%A, %B %d, %Y')}",
            color=discord.Color.from_rgb(78, 42, 132),
        )
        
        # Add timeline as field
        if timeline:
            embed.description = timeline
        
        await ctx.followup.send(embed=embed)

    async def fetch_reservations(self, date_str: str) -> Dict:
        timeout = aiohttp.ClientTimeout(total=10)
        url = f"{RESERVATIONS_ENDPOINT}/{date_str}"
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                resp.raise_for_status()
                return await resp.json()

    @staticmethod
    def build_reservation_timeline(reservations: List[Dict], target_date: datetime) -> str:
        """Build a timeline view similar to the booking interface"""
        # Group reservations by machine
        machine_reservations = {}
        all_machines = set()
        
        for res in reservations:
            machines = res.get("machines", [])
            all_machines.update(machines)
            for machine in machines:
                if machine not in machine_reservations:
                    machine_reservations[machine] = []
                machine_reservations[machine].append({
                    "name": res.get("name", "Unknown"),
                    "start": datetime.fromisoformat(res.get("start_time")),
                    "end": datetime.fromisoformat(res.get("end_time")),
                })
        
        # Sort machines
        sorted_machines = sorted(all_machines, key=lambda m: PCs.extract_sort_key(m))
        
        # Build timeline rows
        lines = []
        lines.append("```")
        
        for machine in sorted_machines:
            # Format machine name
            short_name = machine
            if machine.lower().startswith("desk "):
                remainder = machine[5:].strip()
                digits = "".join(ch for ch in remainder if ch.isdigit())
                if digits:
                    if int(digits) == 0:
                        short_name = "Streaming"
                    else:
                        short_name = f"Desk {digits.zfill(3)}"
            
            # Get reservations for this machine
            res_list = machine_reservations.get(machine, [])
            if res_list:
                for res in res_list:
                    start_time = res["start"].strftime("%I:%M %p").lstrip("0")
                    end_time = res["end"].strftime("%I:%M %p").lstrip("0")
                    name = res["name"][:30]  # Truncate long names
                    lines.append(f"{short_name:15} | {start_time:8} - {end_time:8} | {name}")
        
        lines.append("```")
        return "\n".join(lines)


def setup(bot):
    bot.add_cog(PCs(bot))