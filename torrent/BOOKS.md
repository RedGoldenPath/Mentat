# BOOKS — acquiring books into the Mentat library

## The easy path: Books inbox (auto-file)
`corpus/books_inbox.py` runs as the LaunchAgent **`com.mentat.booksinbox`** and watches
**`~/Downloads`** and **`~/Books-inbox/`**. Any new book file (`.pdf/.epub/.mobi/.azw3/.djvu/…`)
is filed into the taxonomy by filename heuristics; unmatched ones go to `books/_incoming/`.
The vault watcher then indexes whatever lands under `books/`.

So: **download a book however you like** (your usual Z-Library, a publisher PDF, archive.org),
and it sorts + indexes itself. Log: `corpus/logs/books_inbox.log`.

## Free public sources (scripted, in `corpus/`)
- **Internet Archive** — direct pulls (needs OS access; use the engine's media tools).
- **Marxists Internet Archive** — `mirror.py` + `run_build.py` (the ML canon build).
- **Project Gutenberg** — `gutenberg.py`.

## Torrents (VPN-locked)
`app/torrent/` runs **gluetun (ProtonVPN) + qBittorrent**; qBittorrent has no network except the
VPN. Web UI: **http://127.0.0.1:8080** (admin / mentat-vault); downloads → `~/Everything/mentat-torrents/`.
Manage: `docker compose up -d | down | logs -f gluetun` (in `app/torrent/`).

## Security scope (important)
The Docker VPN protects **only the torrent container**. This shell, the browser, and host-side
scripts use the **normal host connection** unless the **ProtonVPN desktop app** is connected.
A VPN hides the IP; it does not make a chat private from the AI provider.

## Reality note
The copyrighted reading-list titles (Ibn ʿArabī studies, Nasr/perennialist) are **not auto-fetchable
free** here — LibGen/Anna's are blocked, Z-Library's public download is captcha-walled, and Telegram
bot/IRC routes proved unreliable. The practical route is: **grab them yourself** (your Z-Library /
a browser) and drop them in `~/Books-inbox/` — see `books/_catalog/WANTED.md` for the list.
