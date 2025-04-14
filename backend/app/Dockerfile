# Use an official Python runtime as a parent image
FROM python:3.10-slim

# Set environment variables to prevent Python from writing pyc files and buffering stdout/stderr
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Set the working directory in the container
WORKDIR /app

# Install system dependencies if needed (e.g., ffmpeg for video processing)
# Example: RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*

# Upgrade pip and install dependencies from requirements.txt
# Copy requirements from the parent directory relative to the build context (backend/app)
COPY ../requirements.txt .
RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code from the current directory (the build context 'backend/app') into the container's WORKDIR '/app'
COPY . /app

# Expose the port the app runs on (Uvicorn default for FastAPI is 8000)
EXPOSE 8000

# Command to run the application when the container starts
# Looks for the FastAPI instance named 'app' inside the file 'main.py' (now directly in WORKDIR /app)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"] 