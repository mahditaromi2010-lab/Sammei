FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8000 \
    DATABASE_URL=sqlite:////data/sammiie.db MEDIA_ROOT=/data/media
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN useradd -m -u 10001 shop && mkdir -p /data && chown -R shop /data /app && chmod +x docker-entrypoint.sh
USER shop
VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD python -c "import urllib.request,os;urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8000')+'/robots.txt')"
ENTRYPOINT ["./docker-entrypoint.sh"]
