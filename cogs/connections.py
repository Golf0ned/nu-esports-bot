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
    display_map: dict[str, str]


@dataclass
class GameSession:
    date: str
    shuffled_words: list[str]
    solved_group_indexes: set[int]
    solved_group_order: list[int]
    guesses: list[set[str]]
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
                solved_group_order=[],
                guesses=[],
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
        key = config.secrets["apify"]["key"]
        if key:
            return key
        return None

    async def get_or_fetch_puzzle(self, requested_date: str) -> CachedPuzzle:
        if requested_date in self.puzzle_cache:
            return self.puzzle_cache[requested_date]

        lock = self.fetch_locks.setdefault(requested_date, asyncio.Lock())
        async with lock:
            try:
                if requested_date in self.puzzle_cache:
                    return self.puzzle_cache[requested_date]

                apify_key = self._get_apify_key()
                if not apify_key:
                    raise ValueError(
                        "`apify:key` is missing from `secrets.yaml`."
                    )

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
            finally:
                # Prevent unbounded growth for one-off date keys in long-lived bot processes.
                self.fetch_locks.pop(requested_date, None)

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
                if normalized in display_map:
                    raise ValueError("Duplicate card words in response.")

                seen_positions.add(position)
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
            display_map=display_map,
        )

    def build_embed_and_file(
        self, user_id: int, requested_date: str
    ) -> tuple[discord.Embed, discord.File]:
        session = self.user_sessions[(user_id, requested_date)]
        puzzle = self.puzzle_cache[requested_date]
        buffer = self.build_board_image(user_id, requested_date)
        file = discord.File(buffer, filename="connections.png")

        embed = discord.Embed(
            title=f"Connections - {requested_date}",
            color=discord.Color.from_rgb(78, 42, 132),
        )
        embed.set_image(url="attachment://connections.png")
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
            embed.set_footer(text="Game over.")
        return embed, file

    def _wrap_text(
        self,
        draw: ImageDraw.ImageDraw,
        text: str,
        font: ImageFont.ImageFont,
        width: int,
    ) -> list[str]:
        if not text.strip():
            return [""]

        tokens: list[str] = []
        for word in text.split():
            candidate_width = draw.textbbox((0, 0), word, font=font)[2]
            if candidate_width <= width:
                tokens.append(word)
                continue

            # Hard-wrap single long tokens character-by-character.
            piece = ""
            for ch in word:
                trial = piece + ch
                trial_width = draw.textbbox((0, 0), trial, font=font)[2]
                if trial_width <= width:
                    piece = trial
                else:
                    if piece:
                        tokens.append(piece)
                    piece = ch
            if piece:
                tokens.append(piece)

        lines: list[str] = []
        current = ""
        for token in tokens:
            trial = f"{current} {token}".strip()
            trial_width = draw.textbbox((0, 0), trial, font=font)[2]
            if trial_width <= width:
                current = trial
            else:
                if current:
                    lines.append(current)
                current = token
        if current:
            lines.append(current)

        if not lines:
            lines.append(text)
        return lines

    def _default_font(self, size: int, bold=False) -> ImageFont.ImageFont:
        font_dir = Path(__file__).resolve().parent.parent / "assets" / "fonts"
        font_file = (
            font_dir / "LibreFranklin-Bold.ttf"
            if bold
            else font_dir / "LibreFranklin-Regular.ttf"
        )
        try:
            return ImageFont.truetype(str(font_file), size=size)
        except (OSError, TypeError):
            try:
                return ImageFont.load_default(size=size)
            except TypeError:
                return ImageFont.load_default()

    def build_board_image(self, user_id: int, requested_date: str) -> io.BytesIO:
        session = self.user_sessions[(user_id, requested_date)]
        puzzle = self.puzzle_cache[requested_date]

        margin = 24
        grid_gap = 14
        tile_gap = 24

        bg_color = (47, 49, 54)
        text_color = (240, 240, 240)
        dark_text = (20, 20, 20)
        unsolved_color = (72, 75, 82)
        cell_outline = (88, 91, 98)
        group_colors = [
            (249, 223, 109),  # yellow (group 1)
            (160, 195, 90),  # green (group 2)
            (176, 196, 239),  # blue (group 3)
            (186, 129, 197),  # purple (group 4)
        ]

        word_font = self._default_font(30, bold=True)
        solved_title_font = self._default_font(30, bold=True)
        solved_words_font = self._default_font(30)
        measure_draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))

        # Solve-order grouped rows at top, remaining words in compact grid below.
        solved_order = [
            idx
            for idx in session.solved_group_order
            if idx in session.solved_group_indexes
        ]
        unsolved_words = [
            w for w in session.shuffled_words if w in session.remaining_words
        ]

        # Compute tile sizing from current unsolved words (fallback to all words when solved out).
        measurement_words = (
            unsolved_words if unsolved_words else list(session.shuffled_words)
        )
        display_words = [
            puzzle.display_map.get(word, word) for word in measurement_words
        ]
        max_text_width = 0
        for display_word in display_words:
            word_width = measure_draw.textbbox((0, 0), display_word, font=word_font)[2]
            if word_width > max_text_width:
                max_text_width = word_width

        cell_w = min(340, max(200, max_text_width + 28))
        tile_text_width = cell_w - 20

        word_line_height = measure_draw.textbbox((0, 0), "Ag", font=word_font)[3]
        max_word_lines = 1
        for display_word in display_words:
            wrapped = self._wrap_text(
                measure_draw, display_word, word_font, tile_text_width
            )
            if len(wrapped) > max_word_lines:
                max_word_lines = len(wrapped)
        cell_h = max(
            84, (max_word_lines * word_line_height) + ((max_word_lines - 1) * 4) + 16
        )

        board_w = (cell_w * 4) + (tile_gap * 3)
        solved_row_width = board_w
        solved_text_width = solved_row_width - 24
        solved_title_line_height = measure_draw.textbbox(
            (0, 0), "Ag", font=solved_title_font
        )[3]
        solved_words_line_height = measure_draw.textbbox(
            (0, 0), "Ag", font=solved_words_font
        )[3]

        solved_rows_layout: list[tuple[int, list[str], list[str]]] = []
        for group_idx in solved_order:
            group = puzzle.groups[group_idx]
            title_lines = self._wrap_text(
                measure_draw,
                group.title,
                solved_title_font,
                solved_text_width,
            )
            words_text = ", ".join(group.display_words)
            words_lines = self._wrap_text(
                measure_draw,
                words_text,
                solved_words_font,
                solved_text_width,
            )
            row_h = (
                14
                + (len(title_lines) * solved_title_line_height)
                + 6
                + (len(words_lines) * solved_words_line_height)
                + 14
            )
            solved_rows_layout.append((row_h, title_lines, words_lines))

        solved_block_h = sum(row_h for row_h, _, _ in solved_rows_layout)
        if len(solved_rows_layout) > 1:
            solved_block_h += grid_gap * (len(solved_rows_layout) - 1)

        unsolved_rows = (len(unsolved_words) + 3) // 4
        unsolved_block_h = 0
        if unsolved_rows > 0:
            unsolved_block_h = (unsolved_rows * cell_h) + (
                (unsolved_rows - 1) * grid_gap
            )

        sections_gap = grid_gap if solved_rows_layout and unsolved_rows > 0 else 0
        width = (margin * 2) + board_w
        height = (margin * 2) + solved_block_h + sections_gap + unsolved_block_h
        height = max(height, margin * 2 + cell_h)

        img = Image.new("RGB", (width, height), bg_color)
        draw = ImageDraw.Draw(img)

        current_y = margin

        # Draw solved groups as full-width rows.
        for group_idx, (row_h, title_lines, words_lines) in zip(
            solved_order, solved_rows_layout
        ):
            x1 = margin
            y1 = current_y
            x2 = x1 + solved_row_width
            y2 = y1 + row_h
            draw.rounded_rectangle(
                [x1, y1, x2, y2],
                radius=12,
                fill=group_colors[group_idx],
                outline=cell_outline,
                width=2,
            )

            y_text = y1 + 14
            for line in title_lines:
                text_w = draw.textbbox((0, 0), line, font=solved_title_font)[2]
                draw.text(
                    (x1 + (solved_row_width - text_w) // 2, y_text),
                    line,
                    fill=dark_text,
                    font=solved_title_font,
                )
                y_text += solved_title_line_height

            y_text += 6
            for line in words_lines:
                text_w = draw.textbbox((0, 0), line, font=solved_words_font)[2]
                draw.text(
                    (x1 + (solved_row_width - text_w) // 2, y_text),
                    line,
                    fill=dark_text,
                    font=solved_words_font,
                )
                y_text += solved_words_line_height

            current_y = y2 + grid_gap

        # Draw remaining words as compact 4-column grid under solved rows.
        for idx, word in enumerate(unsolved_words):
            row = idx // 4
            col = idx % 4
            x1 = margin + col * (cell_w + tile_gap)
            y1 = current_y + row * (cell_h + grid_gap)
            x2 = x1 + cell_w
            y2 = y1 + cell_h

            draw.rounded_rectangle(
                [x1, y1, x2, y2],
                radius=10,
                fill=unsolved_color,
                outline=cell_outline,
                width=2,
            )

            display_word = puzzle.display_map.get(word, word)
            lines = self._wrap_text(draw, display_word, word_font, tile_text_width)
            total_h = len(lines) * word_line_height + (len(lines) - 1) * 4
            y_text = y1 + (cell_h - total_h) // 2
            for line in lines:
                text_w = draw.textbbox((0, 0), line, font=word_font)[2]
                draw.text(
                    (x1 + (cell_w - text_w) // 2, y_text),
                    line,
                    fill=text_color,
                    font=word_font,
                )
                y_text += word_line_height + 4

        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        buffer.seek(0)
        return buffer

    async def apply_guess(
        self, user_id: int, requested_date: str, guess_words: list[str]
    ) -> tuple[bool, str]:
        session_key = (user_id, requested_date)
        if session_key not in self.user_sessions:
            return False, "No active session. Run `/connections` again."

        session = self.user_sessions[session_key]
        if session.completed:
            if session.failed:
                return False, "This game is over (4 mistakes reached)."
            return False, "This puzzle is already complete."

        parts = [_normalize_word(word) for word in guess_words if word and word.strip()]
        if len(parts) != 4:
            return False, "Select exactly 4 words."
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

        if guessed in session.guesses:
            return False, f"Already guessed. Mistakes {session.mistakes}/4"
        
        session.guesses.append(guessed)

        for idx, group in enumerate(puzzle.groups):
            if idx in session.solved_group_indexes:
                continue
            if guessed == group.words:
                session.solved_group_indexes.add(idx)
                if idx not in session.solved_group_order:
                    session.solved_group_order.append(idx)
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
            for idx in range(len(puzzle.groups)):
                if idx not in session.solved_group_order:
                    session.solved_group_order.append(idx)
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

        guess_words = [word for word in self.selected_words if word is not None]
        is_correct, message = await self.cog.apply_guess(
            self.user_id, self.requested_date, guess_words
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
