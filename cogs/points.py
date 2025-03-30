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
        result = await db.fetch_one(sql, data)

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

    @points_prediction.command(name="close", description="Close prediction and prevent new users from joining", guild_ids=[GUILD_ID])
    async def close_prediction(self, ctx):
        # TODO
        await ctx.respond("TODO")

    @points_prediction.command(name="complete", description="Complete prediction and reward users", guild_ids=[GUILD_ID])
    async def complete_prediction(self, ctx, winner):
        # TODO: figure out parameters
        # TODO
        await ctx.respond("TODO")

    @points_prediction.command(name="cancel", description="Cancel prediction and refund users", guild_ids=[GUILD_ID])
    async def cancel_prediction(self, ctx):
        prediction = self.predictions.get(ctx.user.id, None)
        if not prediction:
            await ctx.respond("You don't have a prediction open.", ephemeral=True)
            return
        
        await prediction.cancel_prediction()
        del self.predictions[ctx.user.id]

        await ctx.respond("Prediction refunded.", ephemeral=True)


    @tasks.loop(seconds=60)
    async def update_points(self):
        if not self.points_buffer:
            return

        sql = """INSERT INTO users (discordid, points)
            VALUES (%s, %s)
            ON CONFLICT (discordid)
            DO UPDATE SET points = users.points + EXCLUDED.points;
        """
        data = [(user_id, points) for user_id, points in self.points_buffer.items()]
        await db.perform_many(sql, data)

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
        self.view = PredictionView(self.option_a, self.option_b, embed)
        self.message = await self.thread.send("", embed=self.view.update_embed(), view=self.view)

    async def cancel_prediction(self):
        sql = "UPDATE users SET points = points + %s WHERE discordid = %s;"
        data = [(points, user_id) for user_id, points in self.view.option_a_points.items()] + \
               [(points, user_id) for user_id, points in self.view.option_b_points.items()]
        print(sql)
        print(data)
        await db.perform_many(sql, data)
        await self.message.reply("Prediction cancelled. Points refunded.")

class PredictionView(discord.ui.View):
    def __init__(self, option_a, option_b, embed):
        super().__init__(timeout=1200)

        self.option_a = option_a
        self.option_a_points = {}
        self.option_b = option_b
        self.option_b_points = {}

        self.message = None
        self.embed = embed

        def create_button(label):
            async def button_callback(interaction):
                if any([
                    label == self.option_a and interaction.user.id in self.option_b_points,
                    label == self.option_b and interaction.user.id in self.option_a_points,
                ]):
                    await interaction.response.send_message(f"{interaction.user.mention} tried to change sides...")
                    return
                await interaction.response.send_modal(PredictionModal(self.modal_callback, label))

            button = discord.ui.Button(label=label)
            button.callback = button_callback
            return button

        self.add_item(create_button(self.option_a))
        self.add_item(create_button(self.option_b))

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

    async def on_timeout(self):
        self.disable_all_items()
        await self.message.edit(view=self)

    async def modal_callback(self, user, points, option):
        if option == self.option_a:
            prev = self.option_a_points.pop(user.id, 0)
            self.option_a_points[user.id] = prev + points
        else:
            prev = self.option_b_points.pop(user.id, 0)
            self.option_b_points[user.id] = prev + points

        await self.message.edit(embed=self.update_embed())

        format = "{} bet {} points on **{}**"
        format_prev = "\n(up from {})"
        message = format.format(user.mention, prev + points, option)
        if prev > 0:
            message += format_prev.format(prev)

        sql = "UPDATE users SET points = points - %s WHERE discordid = %s"
        data = [points, user.id]
        await db.perform_one(sql, data)

        await self.message.reply(message)


class PredictionModal(discord.ui.Modal):
    def __init__(self, callback, option):
        super().__init__(title="Prediction")
        self.view_callback = callback
        self.option = option

        self.add_item(discord.ui.InputText(
            label="How many points do you want to wager?",
            required=True,
            min_length=1,
            placeholder="Enter a number greater than 0",
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

        sql = "SELECT points FROM users WHERE discordid = %s"
        data = [interaction.user.id]
        result = await db.fetch_one(sql, data)

        if result is None or result[0] < points:
            await interaction.response.send_message("You don't have enough points!", ephemeral=True)
            return

        await interaction.response.defer()
        await self.view_callback(interaction.user, points, self.option)
