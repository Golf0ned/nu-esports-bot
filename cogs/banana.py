import os

import discord
from discord.ext import commands
import dotenv

dotenv.load_dotenv()
GUILD_ID = os.getenv('GUILD_ID')

class Banana(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

    banana = discord.SlashCommandGroup('banana', 'banana.')

    @banana.command(name= 'jump4joy', description= 'yeah, we jumpin', guild_ids=[GUILD_ID])
    async def jump4joy(self, ctx):
        embed = discord.Embed(
            title = 'jump4joy',
            color=discord.Color.from_rgb(78, 42, 132),
        )
        counter = 0

        embed.set_image("https://gifdb.com/images/high/banana-cat-meme-crying-in-sadness-8n6s9vqzg5ede4u1.webp")
        embed.add_field(name= 'how many times has banana jumped?: ', value= counter, inline=True)

        await ctx.respond(embed=embed, view=CounterUpdate(embed))


def setup(bot):
    bot.add_cog(Banana(bot))

class CounterUpdate(discord.ui.View):
    
    def __init__(self, embed):
        super().__init__(timeout=1200)
        self.embed = embed
    
    counter = 0

    def update_counter(self):
        counter += 1

        self.embed.remove_field(0)
        self.embed.add_field(name= 'how many times has banana jumped?: ', value= counter, inline=True)

    @discord.ui.button(Label= ':banana: Jumpin?', style=discord.ButtonStyle.yellow)
    async def counting_up(self, button, interaction):
        self.update_counter()
        await interaction.response.edit_message(embed=self.embed)

