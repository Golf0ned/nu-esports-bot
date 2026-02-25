import asyncio
import io
import os
import random
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import aiohttp
import discord
from PIL import Image, ImageDraw, ImageFont
from discord.ext import commands

from utils import config


GUILD_ID = config.secrets["discord"]["guild_id"]


@dataclass
class Group:
    title: str
    words: set[str]
    display_words: list[str]


@dataclass
class CachedPuzzle:
    date: str
    groups: list[Group]
    word_bank: list[str]
    positions: dict[str, int]
    display_map: dict[str, str]


@dataclass
class GameSession:
    date: str
    shuffled_words: list[str]
    solved_group_indexes: set[int]
    remaining_words: set[str]
    mistakes: int
    completed: bool
    failed: bool


def _normalize_word(word: str) -> str:
    return " ".join(word.strip().upper().split())


class Connections(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.puzzle_cache: dict[str, CachedPuzzle] = {}
        self.user_sessions: dict[tuple[int, str], GameSession] = {}
        self.fetch_locks: dict[str, asyncio.Lock] = {}

    @discord.slash_command(
        name="connections",
        description="Play NYT Connections for a given date",
        guild_ids=[GUILD_ID],
    )
    async def connections(
        self,
        ctx,
        date_str: discord.Option(
            str,
            name="date",
            description="Date in YYYY-MM-DD format (defaults to today)",
            required=False,
            default=None,
        ),
    ):
        requested_date = self._parse_date_or_none(date_str)
        if date_str and not requested_date:
            await ctx.respond(
                "Invalid date. Use format `YYYY-MM-DD` (example: `2026-02-25`).",
                ephemeral=True,
            )
            return

        requested_date = requested_date or date.today().isoformat()
        await ctx.defer(ephemeral=True)

        try:
            puzzle = await self.get_or_fetch_puzzle(requested_date)
        except ValueError as e:
            await ctx.followup.send(
                f"Could not load Connections puzzle: {str(e)}", ephemeral=True
            )
            return
        except Exception:
            await ctx.followup.send(
                "Could not load Connections puzzle due to an unexpected error.",
                ephemeral=True,
            )
            return

        # Keep sessions daily per user: when a new date is played, old date sessions are dropped.
        self._prune_user_sessions(ctx.user.id, requested_date)
        session_key = (ctx.user.id, requested_date)
        if session_key not in self.user_sessions:
            shuffled_words = list(puzzle.word_bank)
            random.shuffle(shuffled_words)
            self.user_sessions[session_key] = GameSession(
                date=requested_date,
                shuffled_words=shuffled_words,
                solved_group_indexes=set(),
                remaining_words=set(puzzle.word_bank),
                mistakes=0,
                completed=False,
                failed=False,
            )

        embed, file = self.build_embed_and_file(ctx.user.id, requested_date)
        view = ConnectionsView(self, ctx.user.id, requested_date)
        await ctx.followup.send(embed=embed, file=file, view=view, ephemeral=True)

    def _prune_user_sessions(self, user_id: int, keep_date: str):
        stale_keys = [
            key
            for key in self.user_sessions
            if key[0] == user_id and key[1] != keep_date
        ]
        for key in stale_keys:
            self.user_sessions.pop(key, None)

    def _parse_date_or_none(self, raw_date: str | None) -> str | None:
        if not raw_date:
            return None
        try:
            return datetime.strptime(raw_date, "%Y-%m-%d").date().isoformat()
        except ValueError:
            return None

    def _get_apify_key(self) -> str | None:
        env_value = os.getenv("APIFY_KEY")
        if env_value:
            return env_value.strip()

        env_path = Path(".env")
        if not env_path.exists():
            return None

        for line in env_path.read_text().splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            if key.strip() == "APIFY_KEY":
                return value.strip()
        return None

    async def get_or_fetch_puzzle(self, requested_date: str) -> CachedPuzzle:
        if requested_date in self.puzzle_cache:
            return self.puzzle_cache[requested_date]

        lock = self.fetch_locks.setdefault(requested_date, asyncio.Lock())
        async with lock:
            if requested_date in self.puzzle_cache:
                return self.puzzle_cache[requested_date]

            apify_key = self._get_apify_key()
            if not apify_key:
                raise ValueError("`APIFY_KEY` is missing from environment and `.env`.")

            url = (
                "https://jindrich-bar--nyt-games-api.apify.actor/"
                f"connections/{requested_date}?token={apify_key}"
            )

            timeout = aiohttp.ClientTimeout(total=12)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as response:
                    if response.status != 200:
                        raise ValueError(
                            f"Apify returned status {response.status} for {requested_date}."
                        )
                    payload = await response.json()

            puzzle = self._normalize_payload(payload, requested_date)
            self.puzzle_cache[requested_date] = puzzle
            return puzzle

    def _normalize_payload(self, payload: dict, requested_date: str) -> CachedPuzzle:
        if payload.get("status") != "OK":
            raise ValueError("API did not return status OK.")

        api_date = payload.get("print_date")
        if not isinstance(api_date, str) or not api_date:
            raise ValueError("Missing `print_date` in response.")

        categories = payload.get("categories")
        if not isinstance(categories, list) or len(categories) != 4:
            raise ValueError("Expected exactly 4 categories.")

        groups: list[Group] = []
        all_words: list[str] = []
        positions: dict[str, int] = {}
        display_map: dict[str, str] = {}
        seen_positions = set()

        for category in categories:
            if not isinstance(category, dict):
                raise ValueError("Invalid category format.")
            title = category.get("title")
            cards = category.get("cards")
            if not isinstance(title, str) or not title:
                raise ValueError("Category title missing.")
            if not isinstance(cards, list) or len(cards) != 4:
                raise ValueError("Each category must contain 4 cards.")

            display_words: list[str] = []
            normalized_words: set[str] = set()
            for card in cards:
                if not isinstance(card, dict):
                    raise ValueError("Invalid card format.")
                content = card.get("content")
                position = card.get("position")
                if not isinstance(content, str) or not content.strip():
                    raise ValueError("Card content missing.")
                if not isinstance(position, int) or position < 0 or position > 15:
                    raise ValueError("Card position must be an int between 0 and 15.")
                if position in seen_positions:
                    raise ValueError("Duplicate card positions in response.")

                normalized = _normalize_word(content)
                if normalized in positions:
                    raise ValueError("Duplicate card words in response.")

                seen_positions.add(position)
                positions[normalized] = position
                display_map[normalized] = content.strip()
                display_words.append(content.strip())
                normalized_words.add(normalized)
                all_words.append(normalized)

            if len(normalized_words) != 4:
                raise ValueError("Category has duplicate words.")

            groups.append(
                Group(
                    title=title.strip(),
                    words=normalized_words,
                    display_words=display_words,
                )
            )

        if len(set(all_words)) != 16:
            raise ValueError("Puzzle must have exactly 16 unique words.")
        if seen_positions != set(range(16)):
            raise ValueError("Puzzle positions must contain all values 0..15.")

        return CachedPuzzle(
            date=api_date or requested_date,
            groups=groups,
            word_bank=all_words,
            positions=positions,
            display_map=display_map,
        )

    def build_embed_and_file(
        self, user_id: int, requested_date: str
    ) -> tuple[discord.Embed, discord.File]:
        session = self.user_sessions[(user_id, requested_date)]
        puzzle = self.puzzle_cache[requested_date]
        solved_lines = [
            f"• **{puzzle.groups[idx].title}**"
            for idx in sorted(session.solved_group_indexes)
        ]
        buffer = self.build_board_image(user_id, requested_date)
        file = discord.File(buffer, filename="connections.png")

        embed = discord.Embed(
            title=f"Connections - {requested_date}",
            color=discord.Color.from_rgb(78, 42, 132),
        )
        embed.set_image(url="attachment://connections.png")
        embed.add_field(name="Mistakes", value=str(session.mistakes), inline=True)
        embed.add_field(
            name="Groups Solved",
            value=str(len(session.solved_group_indexes)),
            inline=True,
        )
        embed.add_field(
            name="Solved Categories",
            value="\n".join(solved_lines) if solved_lines else "None yet",
            inline=False,
        )
        if session.failed:
            answer_lines = [
                f"• **{group.title}**: {', '.join(group.display_words)}"
                for group in puzzle.groups
            ]
            embed.add_field(
                name="Correct Categories",
                value="\n".join(answer_lines),
                inline=False,
            )
            embed.set_footer(text="Game over: 4 mistakes reached.")
        elif session.completed:
            embed.set_footer(text="Puzzle complete.")
        else:
            embed.set_footer(
                text=f"Use dropdowns to submit guesses. Mistakes: {session.mistakes}/4"
            )
        return embed, file

    def _wrap_text(
        self,
        draw: ImageDraw.ImageDraw,
        text: str,
        font: ImageFont.ImageFont,
        width: int,
    ) -> list[str]:
        words = text.split()
        if not words:
            return [""]
        lines = []
        current = words[0]
        for word in words[1:]:
            trial = f"{current} {word}"
            box = draw.textbbox((0, 0), trial, font=font)
            if box[2] - box[0] <= width:
                current = trial
            else:
                lines.append(current)
                current = word
        lines.append(current)
        return lines

    def _default_font(self, size: int) -> ImageFont.ImageFont:
        try:
            return ImageFont.load_default(size=size)
        except TypeError:
            return ImageFont.load_default()

    def build_board_image(self, user_id: int, requested_date: str) -> io.BytesIO:
        session = self.user_sessions[(user_id, requested_date)]
        puzzle = self.puzzle_cache[requested_date]

        margin = 24
        grid_gap = 14

        bg_color = (47, 49, 54)
        text_color = (240, 240, 240)
        unsolved_color = (72, 75, 82)
        cell_outline = (88, 91, 98)
        group_colors = [
            (88, 166, 255),  # blue
            (174, 123, 255),  # purple
            (246, 211, 101),  # yellow
            (161, 229, 180),  # green
        ]

        fixed_font = self._default_font(30)
        line_height = draw_line_height = 34
        try:
            line_height = ImageDraw.Draw(Image.new("RGB", (1, 1))).textbbox(
                (0, 0), "Ag", font=fixed_font
            )[3]
        except Exception:
            line_height = draw_line_height

        display_words = [
            puzzle.display_map.get(word, word) for word in session.shuffled_words
        ]
        max_text_width = 0
        for display_word in display_words:
            try:
                word_width = ImageDraw.Draw(Image.new("RGB", (1, 1))).textbbox(
                    (0, 0), display_word, font=fixed_font
                )[2]
            except Exception:
                word_width = 220
            if word_width > max_text_width:
                max_text_width = word_width

        cell_w = max(160, max_text_width + 28)
        usable_width = cell_w - 20
        max_lines = 1
        measure_draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        for display_word in display_words:
            wrapped = self._wrap_text(
                measure_draw, display_word, fixed_font, usable_width
            )
            if len(wrapped) > max_lines:
                max_lines = len(wrapped)
        cell_h = max(84, (max_lines * line_height) + ((max_lines - 1) * 4) + 16)

        width = (margin * 5) + (cell_w * 4)
        height = (margin * 2) + (cell_h * 4) + (grid_gap * 3)

        img = Image.new("RGB", (width, height), bg_color)
        draw = ImageDraw.Draw(img)
        board_top = margin

        word_to_group: dict[str, int] = {}
        for idx, group in enumerate(puzzle.groups):
            for word in group.words:
                word_to_group[word] = idx

        for idx, word in enumerate(session.shuffled_words):
            row = idx // 4
            col = idx % 4
            x1 = margin + col * (cell_w + margin)
            y1 = board_top + row * (cell_h + grid_gap)
            x2 = x1 + cell_w
            y2 = y1 + cell_h

            if word in session.remaining_words:
                fill = unsolved_color
                word_fill = text_color
            else:
                group_idx = word_to_group[word]
                fill = group_colors[group_idx]
                word_fill = (20, 20, 20)

            draw.rounded_rectangle(
                [x1, y1, x2, y2], radius=10, fill=fill, outline=cell_outline, width=2
            )

            display_word = puzzle.display_map.get(word, word)
            chosen_font = fixed_font
            chosen_lines = self._wrap_text(
                draw, display_word, chosen_font, usable_width
            )

            line_height = draw.textbbox((0, 0), "Ag", font=chosen_font)[3]
            total_h = len(chosen_lines) * line_height + (len(chosen_lines) - 1) * 4
            y_text = y1 + (cell_h - total_h) // 2
            for line in chosen_lines:
                bbox = draw.textbbox((0, 0), line, font=chosen_font)
                text_w = bbox[2] - bbox[0]
                draw.text(
                    (x1 + (cell_w - text_w) // 2, y_text),
                    line,
                    fill=word_fill,
                    font=chosen_font,
                )
                y_text += line_height + 4

        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        buffer.seek(0)
        return buffer

    async def apply_guess(
        self, user_id: int, requested_date: str, guess_text: str
    ) -> tuple[bool, str]:
        session_key = (user_id, requested_date)
        if session_key not in self.user_sessions:
            return False, "No active session. Run `/connections` again."

        session = self.user_sessions[session_key]
        if session.completed:
            if session.failed:
                return False, "This game is over (4 mistakes reached)."
            return False, "This puzzle is already complete."

        parts = [
            _normalize_word(part)
            for chunk in guess_text.splitlines()
            for part in chunk.split(",")
            if part.strip()
        ]
        if len(parts) != 4:
            return False, "Enter exactly 4 words (comma-separated or one per line)."
        if len(set(parts)) != 4:
            return False, "All 4 guessed words must be unique."

        for word in parts:
            if word not in session.remaining_words:
                return (
                    False,
                    f"`{word}` is not available in the current word bank.",
                )

        puzzle = self.puzzle_cache[requested_date]
        guessed = set(parts)
        for idx, group in enumerate(puzzle.groups):
            if idx in session.solved_group_indexes:
                continue
            if guessed == group.words:
                session.solved_group_indexes.add(idx)
                session.remaining_words -= group.words
                if len(session.solved_group_indexes) == 4:
                    session.completed = True
                    return True, f"Correct: **{group.title}**. Puzzle complete."
                return True, f"Correct: **{group.title}**."

        one_away = False
        for idx, group in enumerate(puzzle.groups):
            if idx in session.solved_group_indexes:
                continue
            if len(guessed.intersection(group.words)) == 3:
                one_away = True
                break

        session.mistakes += 1
        if session.mistakes >= 4:
            session.failed = True
            session.completed = True
            session.solved_group_indexes = set(range(len(puzzle.groups)))
            session.remaining_words.clear()
            answers = "\n".join(
                f"• **{group.title}**: {', '.join(group.display_words)}"
                for group in puzzle.groups
            )
            return (
                False,
                "Incorrect. You reached 4 mistakes and lost.\nCorrect categories:\n"
                + answers,
            )
        if one_away:
            return False, f"One Away! Mistakes {session.mistakes}/4"
        return False, f"Not a group. Mistakes {session.mistakes}/4"


class GuessWordSelect(discord.ui.Select):
    def __init__(self, view: "ConnectionsView", slot_index: int):
        self.parent_view = view
        self.slot_index = slot_index
        placeholder = f"Select Word {slot_index + 1}"
        options = view.build_options_for_slot(slot_index)
        super().__init__(
            placeholder=placeholder,
            min_values=1,
            max_values=1,
            options=options,
            row=slot_index,
        )

    async def callback(self, interaction: discord.Interaction):
        if not await self.parent_view.ensure_owner(interaction):
            return
        self.parent_view.selected_words[self.slot_index] = self.values[0]
        self.parent_view.rebuild_components()
        await interaction.response.edit_message(view=self.parent_view)


class ConnectionsView(discord.ui.View):
    def __init__(
        self,
        cog: Connections,
        user_id: int,
        requested_date: str,
        selected_words: list[str | None] | None = None,
    ):
        super().__init__(timeout=1800)
        self.cog = cog
        self.user_id = user_id
        self.requested_date = requested_date
        self.selected_words = selected_words or [None, None, None, None]
        self.rebuild_components()
        self._sync_disabled_state()

    def _get_session(self) -> GameSession | None:
        return self.cog.user_sessions.get((self.user_id, self.requested_date))

    def _available_words_in_order(self) -> list[str]:
        session = self._get_session()
        if not session:
            return []
        return [w for w in session.shuffled_words if w in session.remaining_words]

    def build_options_for_slot(self, slot_index: int) -> list[discord.SelectOption]:
        puzzle = self.cog.puzzle_cache[self.requested_date]
        session = self._get_session()
        if not session:
            return [discord.SelectOption(label="No active session", value="__none__")]

        current = self.selected_words[slot_index]
        selected_elsewhere = {
            word
            for idx, word in enumerate(self.selected_words)
            if idx != slot_index and word is not None
        }
        options = []
        for word in self._available_words_in_order():
            if word in selected_elsewhere:
                continue
            label = puzzle.display_map.get(word, word)
            options.append(
                discord.SelectOption(
                    label=label[:100],
                    value=word,
                    default=(word == current),
                )
            )
        if not options:
            options.append(
                discord.SelectOption(label="No words available", value="__none__")
            )
        return options

    def rebuild_components(self):
        self.clear_items()
        for slot_idx in range(4):
            self.add_item(GuessWordSelect(self, slot_idx))

        submit_button = discord.ui.Button(
            label="Submit Guess", style=discord.ButtonStyle.primary, row=4
        )

        async def submit_callback(interaction: discord.Interaction):
            await self.submit_guess(interaction)

        submit_button.callback = submit_callback
        self.add_item(submit_button)

    def _sync_disabled_state(self):
        session = self._get_session()
        if not session or session.completed:
            for item in self.children:
                item.disabled = True

    async def ensure_owner(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "This game session belongs to someone else. Run `/connections` to start yours.",
                ephemeral=True,
            )
            return False
        return True

    async def submit_guess(self, interaction: discord.Interaction):
        if not await self.ensure_owner(interaction):
            return
        if any(word is None for word in self.selected_words):
            await interaction.response.edit_message(
                content="Select all 4 words before submitting.",
                view=self,
            )
            return

        guess_text = "\n".join(word for word in self.selected_words if word is not None)
        is_correct, message = await self.cog.apply_guess(
            self.user_id, self.requested_date, guess_text
        )

        updated_embed, file = self.cog.build_embed_and_file(
            self.user_id, self.requested_date
        )
        updated_view = ConnectionsView(self.cog, self.user_id, self.requested_date)

        prefix = "Correct guess. " if is_correct else ""
        await interaction.response.edit_message(
            content=f"{prefix}{message}",
            embed=updated_embed,
            view=updated_view,
            file=file,
            attachments=[],
        )


def setup(bot):
    bot.add_cog(Connections(bot))
