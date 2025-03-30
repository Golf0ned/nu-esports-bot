import random

import discord
from discord.ext import commands, tasks

from utils import config, db


GUILD_ID = config.secrets["discord"]["guild_id"]


class Points(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        self.points_buffer = {}
        self.predictions = {}
        self.update_points.start()

    points = discord.SlashCommandGroup("points", "points :)")
    points_prediction = points.create_subgroup("prediction", "Predictions with points")

    @commands.Cog.listener()
    async def on_message(self, message):
        user = message.author
        if user == self.bot.user or user.bot:
            return

        self.points_buffer[user.id] = random.randint(7, 25)

    @points.command(name="balance", description="Get your points balance or another user's point balance", guild_ids=[GUILD_ID])
    async def balance(self, ctx, user: discord.Option(discord.User, default=None)):
        if user is None:
            user = ctx.author

        sql = "SELECT points FROM users WHERE discordid = %s"
        data = [user.id]
        async with db.cursor() as cur:
            await cur.execute(sql, data)
            result = await cur.fetchone()

        points = result[0] if result else 0
        embed = discord.Embed(
            title=f"{user.display_name}'s points",
            description=f"{points} points",
            color=discord.Color.from_rgb(78, 42, 132),
        )
        await ctx.respond(embed=embed)

    @points_prediction.command(name="create", description="Create a prediction", guild_ids=[GUILD_ID])
    async def create_prediction(self, ctx, title: str, option_a: str, option_b: str):
        if ctx.user.id in self.predictions:
            await ctx.respond("You already have a prediction open.")
            return

        message = await ctx.send(f"PREDICTION: **{title}**")
        thread = await message.create_thread(name=f"{title}")

        prediction = Prediction(title, option_a, option_b, thread)
        await prediction.create_prediction()

        self.predictions[ctx.user.id] = prediction
        await ctx.respond(f"Prediction created! {thread.mention}", ephemeral=True)

    @tasks.loop(seconds=60)
    async def update_points(self):
        if not self.points_buffer:
            return

        sql = """INSERT INTO users (discordid, points)
            VALUES (%s, %s)
            ON CONFLICT (discordid)
            DO UPDATE SET points = users.points + EXCLUDED.points;
        """
        data = [(user_id, message_count) for user_id, message_count in self.points_buffer.items()]
        async with db.cursor() as cur:
            await cur.executemany(sql, data)

        self.points_buffer.clear()


def setup(bot):
    bot.add_cog(Points(bot))


class Prediction:
    def __init__(self, title, option_a, option_b, thread):
        self.title = title
        self.option_a = option_a
        self.option_b = option_b
        self.thread = thread

    async def create_prediction(self):
        embed = discord.Embed(
            title=self.title,
            color=discord.Color.from_rgb(78, 42, 132),
        )
        view = PredictionView(self.option_a, self.option_b, embed)
        await self.thread.send("", embed=view.update_embed(), view=view)


class PredictionView(discord.ui.View):
    def __init__(self, option_a, option_b, embed):
        super().__init__(timeout=1200)

        self.option_a = option_a
        self.option_b = option_b
        self.option_a_points = {}
        self.option_b_points = {}

        self.message = None
        self.embed = embed

        option_a_button = discord.ui.Button(label=option_a)
        async def option_a_callback(interaction):
            await interaction.response.send_modal(PredictionModal(option_a, self.option_a_modal_callback))
        option_a_button.callback = option_a_callback
        self.add_item(option_a_button)

        option_b_button = discord.ui.Button(label=option_b)
        async def option_b_callback(interaction):
            await interaction.response.send_modal(PredictionModal(option_b, self.option_b_modal_callback))
        option_b_button.callback = option_b_callback
        self.add_item(option_b_button)

    def update_embed(self):
        # TODO: add odds
        self.embed.clear_fields()
        format = "{} points\n{} users"
        self.embed.add_field(
            name=self.option_a,
            value=format.format(
                sum(self.option_a_points.values()),
                len(self.option_a_points)
            ),
        )
        self.embed.add_field(
            name=self.option_b,
            value=format.format(
                sum(self.option_b_points.values()),
                len(self.option_b_points),
            ),
        )
        return self.embed

    async def option_a_modal_callback(self, user, points):
        prev_a = self.option_a_points.pop(user.id, None)
        prev_b = self.option_b_points.pop(user.id, None)
        self.option_a_points[user.id] = points
        await self.message.edit(embed=self.update_embed())

        format = "{} bet {} points on **{}**"
        format_prev = "\n(previously: {} on **{}**)"
        message = format.format(user.mention, points, self.option_a)
        if prev_a is not None:
            message += format_prev.format(prev_a, self.option_a)
        elif prev_b is not None:
            message += format_prev.format(prev_b, self.option_b)
        await self.message.reply(message)

    async def option_b_modal_callback(self, user, points):
        prev_a = self.option_a_points.pop(user.id, None)
        prev_b = self.option_b_points.pop(user.id, None)
        self.option_b_points[user.id] = points
        await self.message.edit(embed=self.update_embed())

        format = "{} bet {} points on **{}**"
        format_prev = "\n(previously: {} on **{}**)"
        message = format.format(user.mention, points, self.option_b)
        if prev_a is not None:
            message += format_prev.format(prev_a, self.option_a)
        elif prev_b is not None:
            message += format_prev.format(prev_b, self.option_b)
        await self.message.reply(message)

class PredictionModal(discord.ui.Modal):
    def __init__(self, side, callback):
        super().__init__(title="Prediction")
        self.side = side
        self.view_callback = callback

        self.add_item(discord.ui.InputText(
            label="How many points do you want to wager?"
            # TODO: make prettier
        ))

    async def callback(self, interaction):
        value = self.children[0].value
        if not value.isdigit():
            await interaction.response.send_message("You must wager a numeric amount!", ephemeral=True)
            return

        points = int(value)
        if points <= 0:
            await interaction.response.send_message("You must wager more than 0 points!", ephemeral=True)
            return

        # TODO: check if enough points

        await interaction.response.defer()
        await self.view_callback(interaction.user, points)
