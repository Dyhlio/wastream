# <img src="https://raw.githubusercontent.com/Dydhzo/wastream/refs/heads/main/wastream/public/wastream-logo.jpg" width="30"/> WAStream

Addon Stremio qui cherche sur Wawacity, convertit en liens directs via AllDebrid et permet la lecture des fichiers. Toutes les qualités, langues et tailles disponibles sont retournées comme sources Stremio distinctes.

<img src="https://i.imgur.com/UNz4i6r.jpeg">

## 🗒️ Prérequis

- Une clé API AllDebrid (⚠️ nécessité d'un compte **payant**): https://alldebrid.com/apikeys
- Un jeton d'accès API TMDB (**compte obligatoire**): https://www.themoviedb.org/settings/api

## 🚀 Installation et lancement

## Option 1: Docker (recommandé)

### Étape 1: Créer un fichier docker-compose.yml

```yaml
services:
  wastream:
    image: dydhzo/wastream:latest
    container_name: wastream
    ports:
      - "7000:7000"
    volumes:
      - ./data:/app/data
    environment:
      - WAWACITY_URL=https://example.com # OBLIGATOIRE
      - PORT=7000
      - DATABASE_TYPE=sqlite
      - DATABASE_PATH=/app/data/wastream.db
    restart: unless-stopped
```

### Étape 2: Démarrer le conteneur

```bash
docker-compose up -d
```

### Étape 3: Vérifiez les logs

```bash
docker-compose logs -f
```

### Étape 4: Configuration

- Accédez à `http://localhost:7000` dans votre navigateur
- Renseignez votre clé API AllDebrid et votre jeton d'accès API TMDB
- **Si problème d'accès à Wawacity :** [Changez vos paramètres DNS](https://one.one.one.one/fr-FR/dns/) ou modifiez `WAWACITY_URL` dans le docker-compose.yml

---

## Option 2: Installation manuelle

### Étape 1: Télécharger le code

Téléchargez la dernière version depuis GitHub : [**Download ZIP**](https://github.com/Dydhzo/wastream/archive/refs/heads/main.zip)

Extraire le fichier ZIP et ouvrir le dossier dans un terminal

### Étape 2: Installer les dépendances

```bash
pip install -r requirements.txt
```

### Étape 3: Lancer l'addon

```bash
python -m wastream.main
```

### Étape 4: Configuration

- Accédez à `http://localhost:7000` dans votre navigateur  
- Renseignez votre clé API AllDebrid et votre jeton d'accès API TMDB
- **Personnalisation :** Éditez le fichier `.env` pour modifier l'URL Wawacity ou le port si nécessaire


## 🛠️ Comment ça marche

- Stremio appelle `/{b64config}/stream/{type}/{imdb_id}.json`.
	- `b64config`: clé API AllDebrid & TMDB
	- `type`: movie ou series
	- `imdb_id`: identifiant IMDB
- L'addon récupère le `title` et `year` via TMDB et `imdb_id`.
- L'addon utilise le système de scrapers avec cache intelligent et verrous distribués.
- `movie.py` scrape Wawacity pour les films, `series.py` pour les séries, `anime.py` pour les animes, supportent 1fichier, Turbobit et Rapidgator et retournent un JSON comme celui ci:

```json
{
  "title": "Mission: Impossible - The Final Reckoning",
  "year": "2025",
  "results": [
    {
      "label": "WEB-DL 4K - MULTI (TRUEFRENCH)",
      "language": "MULTI (TRUEFRENCH)",
      "quality": "WEB-DL 4K",
      "size": "31.1 Go",
      "dl_protect": "https://dl-protect.link/...",
      "display_name": "Mission : Impossible – The Final Reckoning [WEB-DL 4K] - MULTI (TRUEFRENCH)"
    },
    {
      "label": "WEBRIP 720p - TRUEFRENCH",
      "language": "TRUEFRENCH",
      "quality": "WEBRIP 720p",
      "size": "4.5 Go",
      "dl_protect": "https://dl-protect.link/...",
      "display_name": "Mission : Impossible – The Final Reckoning [WEBRIP 720p] - TRUEFRENCH"
    },
    ...
  ]
}
```

- Pour chaque résultat, l'addon crée une source Stremio
- Si une source est choisie, Stremio appelle `/resolve?link={DL_PROTECT_LINK}&b64config={BASE64_CONFIG}` qui retourne un lien direct AllDebrid streamable dans l'application.

## 🐛 Debug
- Test recherche: `http://localhost:7000/debug/test-search?title={TITLE}&year={YEAR}`
- Test AllDebrid: `http://localhost:7000/debug/test-alldebrid?link={DL_PROTECT_LINK}&apikey={ALLDEBRID_API_KEY}`
- Health check: `http://localhost:7000/health`

## ⚠️ Disclaimer

Cet addon fait simplement l'intermédiaire entre un site web (Wawacity) et l'utilisateur via Stremio. Il ne stocke ni ne distribue aucun contenu. Le développeur n'approuve ni ne promeut l'accès à des contenus protégés par des droits d'auteur. Les utilisateurs sont seuls responsables du respect de toutes les lois applicables.
