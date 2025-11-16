# Use a lightweight Python image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . .

# Create a volume for Telethon session files
VOLUME ["/app/sessions"]

# Command to run the bot
CMD ["python", "bot.py"]
