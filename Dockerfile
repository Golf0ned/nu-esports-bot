FROM ghcr.io/astral-sh/uv:python3.10-alpine
WORKDIR /bot
COPY . /bot

# Install dependencies using uv
RUN uv sync --frozen

CMD ["uv", "run", "bot.py"]
