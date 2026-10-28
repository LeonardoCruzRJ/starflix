<div align="center">

<img src="web/static/img/starflix-logo.svg" alt="StarFlix" width="360">

### Your video server. Your home. Your rules.

Your own **local, cloud-free** media server, with a modern look and feel of its own,<br>
apps for **phone** and **Android TV**, all on a single port (default **32000**, configurable).

<br>

![Version](https://img.shields.io/badge/version-1.0.697-e5a00d?style=for-the-badge)
![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge\&logo=python\&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-3.x-000000?style=for-the-badge\&logo=flask\&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-WAL-003B57?style=for-the-badge\&logo=sqlite\&logoColor=white)
![FFmpeg](https://img.shields.io/badge/FFmpeg-HLS%20%7C%20DASH-007808?style=for-the-badge\&logo=ffmpeg\&logoColor=white)
![Android](https://img.shields.io/badge/Android-Phone%20%2B%20TV-3DDC84?style=for-the-badge\&logo=android\&logoColor=white)
![Kotlin](https://img.shields.io/badge/Kotlin-Compose%20for%20TV-7F52FF?style=for-the-badge\&logo=kotlin\&logoColor=white)
![License](https://img.shields.io/badge/license-MIT-e5a00d?style=for-the-badge)

[Features](#-features) •
[Screenshots](#-screenshots) •
[Installation](#-installation) •
[Android apps](#-android-apps) •
[Configuration](#-configuration) •
[Languages](#-languages) •
[Structure](#-project-structure) •
[Wiki](https://github.com/LeonardoCruzRJ/starflix/wiki/EN-Home)

Versão em português: [README.md](README.pt.md)

</div>

\---

## ✨ Why StarFlix?

|||
|-|-|
|🏠 **100% local**|No relay, no Tailscale, no Headscale, no third-party service account. Default port **32000**, configurable in **Settings → Server**.|
|🎬 **Its own look**|Dark theme, gold accent `#e5a00d`, dynamic sidebar, customizable Home and a full details page.|
|📱 **Native apps**|A single APK for **phone** (WebView + native player) and **Android TV** (Compose for TV, D-pad control).|
|🔍 **Automatic connection**|The apps find the server on their own on the network (mDNS) or pair with a **QR code**.|
|🪶 **Lightweight**|Flask + SQLite + FFmpeg. No Docker, no venv, no external database.|
|🌍 **10 languages**|Site, server and apps with several language options, switched instantly in **Settings**. Default pt-BR. Metadata (TMDB, TheTVDB, SubDL) follows the chosen language.|

\---

## 🎯 Features

### 📚 Libraries and metadata

* **Movies**, **Series** and **Other Videos** libraries, with several folders per library.
* Automatic scanner: extracts `Title (Year)` and `SxxExx` from the file name, with a configurable periodic scan.
* `ffprobe` records duration, codecs, audio tracks and subtitles.
* Metadata from **TMDB** and **TheTVDB**, **IMDb / Rotten Tomatoes** ratings through OMDb (optional).
* Manual match correction, cover editing, tags and information.
* **Duplicate** detection, manual and automatic **collections**, **playlists** and smart lists.
* **Actor and director** pages and a dedicated **episode** page.

### ▶️ Playback

* **Direct play** with Range support, **remux** or **transcode**, chosen automatically.
* **HLS** and **DASH** through FFmpeg, with quality, audio track and subtitle selection.
* External (`.srt` → `.vtt`) and embedded **subtitles**, with **automatic search on SubDL** and per-profile style.
* **Skip intro and credits** with automatic marker detection and manual marking.
* **Seek bar thumbnails** (trickplay).
* **HDR → SDR** with CPU tone mapping.
* **Optimized versions** to reduce CPU usage.
* Control of simultaneous transcodes, minimum free space and automatic session cleanup.
* Synced progress, **Continue Watching**, automatic next episode and watched marking.

### 👥 Users and access

* First admin created on first run; passwords are hashed.
* **Profiles** per user (name + avatar), with language, audio and subtitle preferences.
* Per-library access set by the administrator.
* **Device** management, sessions and revocation.

### 🛠️ Administrator panel

* Full management of libraries, users and access.
* **Dashboard** with server activity, devices and a scan indicator.
* **Automatic database backup** (every N days, configurable) and a restore script.
* API keys configured right in the interface (**Settings → Agents**); the agents' language is the user's, with no per-agent or per-library option.
* Branding customization.

### 🏡 Dynamic Home

* Configurable Home rows, with full-screen **Highlights**.
* TMDB lists by region, Continue Watching, recently added and recent use.
* Dynamic sidebar: libraries on regular pages and administration menus on the top bar icons.

\---

## 📸 Screenshots

<div align="center">

<img src="imagens/1.png" alt="Screenshot 1" width="49%"> <img src="imagens/2.png" alt="Screenshot 2" width="49%">
<img src="imagens/3.png" alt="Screenshot 3" width="49%"> <img src="imagens/4.png" alt="Screenshot 4" width="49%">
<img src="imagens/5.png" alt="Screenshot 5" width="49%"> <img src="imagens/6.png" alt="Screenshot 6" width="49%">

</div>

## 📱 Android apps

A single Android APK with two experiences:

|📱 Phone|📺 Android TV / Google TV|
|-|-|
|Connection screen → WebView + native player (ExoPlayer)|Native interface in **Compose for TV**|
|Automatic discovery (mDNS), **QR code**, `starflix://connect` link or manual address|Automatic discovery, **QR pairing** or 6-character code at `/tv`|
|PiP, landscape orientation, floating bottom bar|Full **D-pad** control, **Play Next** row on the launcher|

### Build the APK

Requires **JDK 17** and the **Android SDK**.

```bash
./scripts/build\_apk.sh      # generates ./starflix.apk (signed)
```

> The script creates `android/starflix.jks` and `android/keystore.properties` on the first run. \*\*Keep both\*\*: without them you cannot update the installed app.

### Install on the TV

```bash
adb connect IP-DA-TV:5555
adb install -r starflix.apk
```

Usage details, remote control and launcher in [`android/README.md`](android/README.md).

\---

## 🚀 Installation

A single command downloads the project, installs the dependencies, creates the systemd service and starts the server.

```bash
curl -fsSL https://raw.githubusercontent.com/LeonardoCruzRJ/starflix/main/install.sh | sudo bash
```

When it finishes, open **`http://SERVER-IP:32000`** (or the port you chose in **Settings → Server**), create the administrator user and add your libraries in **Settings**.

**The installer:**

1. installs the Starflix server;
2. uses the **`/data/starflix`** folder as the project default;
3. installs the Python dependencies (`requirements.txt`);
4. creates the `data/` folders and installs `starflix.service` with the correct path;
5. enables the service at boot, starts it and checks `/health`.

**Options** (environment variables before the command):

|Variable|Default|Description|
|-|-|-|
|`STARFLIX\_DIR`|`/data/starflix`|Installation folder|
|`STARFLIX\_BRANCH`|`main`|Branch to install|
|`STARFLIX\_REPO`|official repository|Repository URL (fork)|

```bash
# example: install in another folder
curl -fsSL https://raw.githubusercontent.com/LeonardoCruzRJ/starflix/main/install.sh | sudo STARFLIX\_DIR=/opt/starflix bash
```

### Update

Run the same command, paying attention if you changed the default folder: the installer updates the dependencies and restarts the service. `data/` (database, covers, backups) and `scripts/.env` are preserved.

### Useful commands

```bash
systemctl status starflix        # status
journalctl -u starflix -f        # logs
sudo systemctl restart starflix  # restart
python3 /data/starflix/scripts/smoke\_test.py   # smoke test
```

<details>
<summary><b>Manual installation</b></summary>

Requirements: Linux, Python 3.10+, `ffmpeg` and `ffprobe` in the `PATH`.

```bash
sudo apt install -y git python3 python3-pip ffmpeg
sudo git clone https://github.com/LeonardoCruzRJ/starflix.git /data/starflix
cd /data/starflix
sudo pip3 install --break-system-packages -r requirements.txt
python3 run.py            # quick test; Ctrl+C to exit

# systemd service
sudo sed "s|@DIR@|$(pwd)|g" scripts/starflix.service | sudo tee /etc/systemd/system/starflix.service >/dev/null
sudo systemctl daemon-reload \&\& sudo systemctl enable --now starflix
```

</details>

\---

## ⚙️ Configuration

Environment variables (optional), read from `scripts/.env` by the systemd service:

|Variable|Default|Description|
|-|-|-|
|`STARFLIX\_DATA`|`./data`|Data folder (database, covers, transcode, subtitles, backups)|
|`STARFLIX\_SECRET`|generated in `data/secret.key`|Session key|
|`STARFLIX\_MAX\_TRANSCODES`|`3`|Simultaneous FFmpeg transcodes (`0` = no limit)|
|`STARFLIX\_MIN\_FREE\_GB`|`5`|Minimum free space in `data/transcode`|
|`STARFLIX\_THREADS`|`64`|Server threads|
|`STARFLIX\_SCAN\_INTERVAL`|`3600`|Seconds between automatic scans (`0` disables)|
|`STARFLIX\_TRANSCODE\_TTL`|`600`|Seconds without activity until a transcode session is deleted|
|`STARFLIX\_TRANSCODE\_CLEAN\_INTERVAL`|`60`|Session cleanup interval|
|`TMDB\_IMG\_SIZE`|`w500`|Size of the covers downloaded from TMDB|

### API keys for the Metadata Agents

The keys live **inside the settings**. Set them in **Settings → Agents**:

|Service|Use|Required|
|-|-|-|
|[TMDB](https://www.themoviedb.org/settings/api)|Movies, series, covers, Home lists|Recommended|
|[TheTVDB](https://thetvdb.com/api-information)|Episode titles and synopses|Optional|
|[OMDb](https://www.omdbapi.com/apikey.aspx)|IMDb / Rotten Tomatoes ratings|Optional|
|[SubDL](https://subdl.com)|Automatic subtitle download|Optional|

\---

## 🌍 Languages

|Code|Language|Code|Language|
|-|-|-|-|
|`pt-BR`|Português (Brasil), source|`de-DE`|Deutsch|
|`en-US`|English|`it-IT`|Italiano|
|`es-ES`|Español|`ja-JP`|日本語|
|`ru-RU`|Русский|`zh-CN`|简体中文|
|`fr-FR`|Français|`tr-TR`|Türkçe|

* **Site and server:** the language is the one the user picks in **Personal Settings → Settings → Language** (profile or account); with no choice, the `sf\_lang` cookie applies, then the browser (`Accept-Language`) and finally pt-BR. There is no server default language. The switch is instant, without reloading the page.
* **Android apps (phone and TV):** follow the device language; a language outside the list falls back to the default pt-BR. The metadata language (TMDB/TheTVDB/SubDL) follows the language chosen by the user; there is no per-agent or per-library option.
* **Metadata:** when you switch the language (while signed in), all movie and series libraries are updated in the new language (title, synopsis, genres, cover, cast, seasons and episodes); fields edited by hand (locked) do not change. Data from languages already used is kept and comes back without a new lookup; only what was never fetched in the new language is queried. TMDB lists on Home and SubDL subtitles follow the language. People's biographies are rebuilt when you open the person.
* The translations were made by AI and may need review by native speakers: corrections are welcome.

### Add a new language

1. Copy `i18n/en-US.json` to `i18n/<code>.json` (e.g. `pl-PL.json`) and translate the values, keeping the keys, the `{n}` variables and the plural forms (`.one`, `.few`, `.many`, `.other`) the language uses.
2. Register `("<code>", "<name in its own language>")` in `LANGS` in `server/i18n.py` and the plural rules in `plural\_category()`, if they differ from the existing ones.
3. Register the code in `FOLDERS` in `scripts/i18n\_build.py` (e.g. `"pl-PL": "pl"`) and run `python3 scripts/i18n\_build.py` to generate the Android `strings.xml` files.
4. Adjust the dates and separators (`fmt.\*`) in the JSON itself and check with `python3 scripts/i18n\_check.py` (it must finish with no pending items).

\---

## 🗂️ Project structure

```
starflix/
├── install.sh             # single installer (downloads, installs and creates the service)
├── imagens/               # README screenshots (1.png, 2.png...); GitHub only, the installer does not download it
├── run.py                 # starts the server (waitress) on the saved port (default 32000)
├── config.py              # default port, paths and environment variables
├── requirements.txt
├── server/                # Flask backend (blueprints)
│   ├── schema.sql         # SQLite schema
│   ├── auth · users · profiles · account · library\_access
│   ├── libraries · scanner · probe · metadata · images · dedupe
│   ├── stream · playback · subtitles · subdl · trickplay · markers · optimize
│   ├── browse · search · collections · playlists · smart · mylist · people
│   ├── home\_rows · home\_library · home\_tmdb · home\_usage · tmdb\_lists
│   ├── tv\_auth · tv\_api · phone\_auth · discovery · devices
│   └── admin\_\* · backup · activity · branding · agents
├── web/
│   ├── templates/         # Jinja pages
│   └── static/            # css, js (hls.js included), fonts, images
├── android/               # Kotlin app (phone + Android TV)
├── scripts/
│   ├── starflix.service   # systemd unit
│   ├── build\_apk.sh       # builds the signed APK
│   ├── restore\_backup.py  # restores a database backup
│   └── smoke\_test.py      # smoke tests
└── data/                  # database, covers, transcode, subtitles, backups (not versioned)
```

### Stack

|Layer|Technology|
|-|-|
|Server|Python 3, Flask 3, Waitress|
|Database|SQLite (WAL mode)|
|Video|FFmpeg / ffprobe, HLS, DASH, hls.js|
|Discovery|zeroconf (mDNS), segno (QR code)|
|Web|Plain JavaScript, no framework|
|Android|Kotlin, WebView, ExoPlayer, Compose for TV|

\---

## 🔌 Network

* **Port:** `32000` by default; change it in **Settings → Server** (1024–65535). The server restarts by itself on the new port, the mDNS announcement and `/api/server-info` already use it, and the apps (phone and TV) find the server again on the network by the same identifier. An external address (domain, router forwarding) does not change by itself: adjust it if you use the port.
* **Discovery:** mDNS on the local network; the apps find the server on their own.
* **Pairing:** QR code or single-use link (`starflix://connect`) with confirmation before connecting.
* **Health check:** `GET /health`
* **Server information:** `GET /api/server-info` (includes the version)

\---

## 🔒 Privacy

Nothing leaves your network. StarFlix only accesses the internet to fetch metadata and subtitles from the services **you** configure (TMDB, TheTVDB, OMDb, SubDL). Database, covers, API keys and the session key stay in `data/`.

\---

## 🤝 Contributing

Suggestions and fixes are welcome: open an *issue* describing the problem or the idea, or send a *pull request*.

\---
## 📄 License

Distributed under the **MIT** license. See the [`LICENSE`](LICENSE) file.
<div align="center">
\---
  
Made with lots of ☕ and many late nights by [**Leonardo Cruz**](https://github.com/LeonardoCruzRJ)

⭐ If StarFlix is useful to you, leave a star on the repository!

</div>

