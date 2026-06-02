FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends gdal-bin libgdal-dev gcc g++ && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY . /app/
RUN pip install --no-cache-dir flask>=3.0 geopandas>=0.14 shapely>=2.0 scipy>=1.10 numpy>=1.24 pyproj>=3.4 requests>=2.28 pyyaml>=6.0 click>=8.1 mapbox-earcut>=1.0
RUN pip install --no-cache-dir -e .
RUN mkdir -p /app/viewer/jobs /app/viewer/uploads
EXPOSE 7860
ENV PORT=7860
ENV PYTHONUNBUFFERED=1
CMD ["python", "app.py"]
