FROM python:3.10-alpine
WORKDIR /bot
COPY . /bot

RUN pip install -r requirements.txt

CMD ["python", "-u", "bot.py"]
