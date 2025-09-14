FROM python:3.12-slim

LABEL name="WAStream" \
      description="Accès au contenu de Wawacity via Stremio & AllDebrid (non officiel)" \
      url="https://github.com/Dydhzo/wastream"

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 7000

CMD ["python", "-m", "wastream.main"]
