FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY config/ config/
COPY prompts/ prompts/
COPY src/ src/
COPY run_daily.py .

RUN mkdir -p data reports

ENTRYPOINT ["python"]

# Default: run Telegram bot; Cloud Run Jobs can override args to run_daily.py --run-type=...
CMD ["-m", "src.shared.telegram_bot"]
