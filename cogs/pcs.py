import asyncio
from typing import Dict, Tuple

import aiohttp
import discord
from discord.ext import commands

from utils import config


GUILD_ID = config.secrets["discord"]["guild_id"]


PCS_ENDPOINT = config.secrets["apis"]["pcs"]


STATE_TO_EMOJI = {
    "ReadyForUser": ":green_square:",
    "UserLoggedIn": ":red_square:",
    "AdminMode": ":yellow_square:",
    "Off": ":black_large_square:",
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
        # Examples: "Desk 009" -> (9, "Desk 009"), "Desk 000 - Streaming" -> (0, name)
        try:
            if name.lower().startswith("desk "):
                remainder = name[5:].strip()
                digits = "".join(ch for ch in remainder if ch.isdigit())
                if digits:
                    return (int(digits), name)
        except Exception:
            pass
        return (10**9, name)

    @staticmethod
    def build_grid(data: Dict, columns: int = 5) -> Tuple[str, Dict[str, str]]:
        # Returns (grid_text, id_to_state)
        items = sorted(data.items(), key=lambda kv: PCs.extract_sort_key(kv[0]))

        id_to_state: Dict[str, str] = {}
        cells = []
        for name, info in items:
            state = info.get("state", "Unknown")
            id_to_state[name] = state
            emoji = STATE_TO_EMOJI.get(state, ":white_large_square:")
            # Show short id for readability; prefer the numeric portion if available
            short = name
            if name.lower().startswith("desk "):
                remainder = name[5:].strip()
                digits = "".join(ch for ch in remainder if ch.isdigit())
                if digits:
                    short = digits.zfill(3)
            cells.append(f"{emoji} `{short}`")

        # Build rows
        rows = []
        for i in range(0, len(cells), columns):
            rows.append(" ".join(cells[i:i+columns]))

        return ("\n".join(rows) if rows else "No PCs found.", id_to_state)

    @commands.slash_command(name="pcs", description="Show PC statuses as a color grid", guild_ids=[GUILD_ID])
    async def pcs(self, ctx):
        await ctx.defer()
        try:
            data = await self.fetch_pcs()
        except Exception as e:
            await ctx.followup.send("Failed to fetch PC statuses. Please try again later.", ephemeral=True)
            return

        grid, id_to_state = self.build_grid(data)

        # Tally counts by state
        counts: Dict[str, int] = {}
        for state in id_to_state.values():
            counts[state] = counts.get(state, 0) + 1

        legend_parts = []
        for state, emoji in STATE_TO_EMOJI.items():
            legend_parts.append(f"{emoji} {state} ({counts.get(state, 0)})")
        legend = " · ".join(legend_parts)

        embed = discord.Embed(
            title="PC Statuses",
            color=discord.Color.from_rgb(78, 42, 132),
        )
        embed.add_field(name="Legend", value=legend or "No data", inline=False)
        embed.add_field(name="Grid", value=grid, inline=False)
        embed.set_footer(text="Source: ggleap")

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


def setup(bot):
    bot.add_cog(PCs(bot))




