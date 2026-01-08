FROM python:3.9-slim

# Install system dependencies
# libgl1 is needed for opencv-python (even headless versions sometimes need runtime libs)
# tesseract-ocr is needed for pytesseract
RUN apt-get update && apt-get install -y \
    libgl1 \
    libglib2.0-0 \
    tesseract-ocr \
    tesseract-ocr-chi-tra \
    tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Be sure to expose the port (Cloud Run sets PORT env var)
ENV PORT=8080

CMD exec gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 0 main:app
