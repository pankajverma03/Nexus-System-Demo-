# Python ka base OS
FROM python:3.11-slim

# Working directory set karo
WORKDIR /app

# Dependencies install karo
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code copy karo
COPY app.py .

# Gunicorn is port par sunega
ENV PORT 8080
EXPOSE 8080

# Application ko Gunicorn se start karo (Production web server)
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "app:app"]
