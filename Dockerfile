FROM python:3.12-slim

# Install system dependencies for GDAL and eccodes
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libgdal-dev \
    libeccodes-dev \
    libeccodes-tools \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Set GDAL environment
ENV CPLUS_INCLUDE_PATH=/usr/include/gdal
ENV C_INCLUDE_PATH=/usr/include/gdal

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN GDAL_VERSION=$(gdal-config --version) && \
    pip install --no-cache-dir GDAL==${GDAL_VERSION} && \
    pip install --no-cache-dir -r requirements.txt

# Copy pipeline code
COPY icon_d2_pipeline/ /app/icon_d2_pipeline/

# Run as non-root user
RUN useradd --create-home appuser
USER appuser

# Entry point
CMD ["python", "-m", "icon_d2_pipeline.run"]
