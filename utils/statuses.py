import yaml
import discord

TYPE_MAP = {
    "listening": discord.ActivityType.listening,
    "watching": discord.ActivityType.watching,
    "playing": discord.ActivityType.playing,
    "competing": discord.ActivityType.competing,
}

def load_statuses():
    with open("statuses.yaml", "r") as file:
        statuses = yaml.safe_load(file)
    return [
        discord.Activity(type=TYPE_MAP[status["type"]], name=status["name"])
        for status in statuses["statuses"]
    ]