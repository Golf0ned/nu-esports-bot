import random

import discord
from discord.ext import commands

from utils import config


GUILD_ID = config.secrets["discord"]["guild_id"]


class Fun(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author == self.bot.user:
            return
           
        if (output := chess(self, message)):
            await message.add_reaction(output)
        
        if (output := i_love_osu(message)):
            await message.reply(output)
    
        if (output := oh_lord(message)):
            await message.reply(output)
        
        if (output := special_interactions(message)):
            for emoji in output:
                await message.add_reaction(emoji)
       
    
def chess(self, message):
    if self.bot.user.mentioned_in(message):
        if message.mention_everyone:
            return None
        
        chess_emojis = config.config["fun"]["chess_emojis"]
        emoji, id = random.choice(list(chess_emojis.items()))
        output = f"<:{emoji}:{id}>" # message.add_reaction(output)
        return output
    
def i_love_osu(message):
    lower_content = message.content.lower()
    if "i love osu" in lower_content:
        output = "Osu 😻" # message.reply(output)
        return output
    return None

def oh_lord(message):
    lower_content = message.content.lower()
    if random.randint(1,100) <= 10 and "oh lord" in lower_content:
        output = 'https://www.youtube.com/watch?v=YsoP6bjADic'  # message.reply(output)
        return output
    return None

def special_interactions(message):
    special_users = config.config["fun"]["special_users"]
    if random.randint(1, 100) <= 15 and message.author.id in special_users:
        output = [ random.choice(special_users[message.author.id])]
        return output    
    return None   
        

def setup(bot):
    bot.add_cog(Fun(bot))