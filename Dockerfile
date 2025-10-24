FROM python:3.12-slim

LABEL name="WAStream" \
      description="Stremio addon to convert DDL to streams via debrid services" \
      url="https://github.com/Dyhlio/wastream"

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir .

COPY . .

EXPOSE 7000

CMD ["python", "-m", "wastream.main"]
