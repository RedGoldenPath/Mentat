# Mentat Torrent Box (gluetun + qBittorrent)

VPN-locked torrent client for pulling copyrighted books into the private library.
qBittorrent has **no network except through the Proton VPN** (gluetun's firewall kill switch).

## What's here
- `docker-compose.yml` — `gluetun` (ProtonVPN WireGuard) + `qbittorrent` sharing its network.
- `.env` — the WireGuard private key + address (mode 600, do not commit/share).

## Use it
```
cd ~/Everything/mentat/app/torrent
docker compose up -d      # start
docker compose down       # stop
docker compose logs -f gluetun
```
- Web UI: **http://127.0.0.1:8080**  (localhost only)
- Login: **admin / mentat-vault**  (change in WebUI → Options if you like)
- Downloads land in `~/Everything/mentat-torrents/` (`/downloads`), incomplete in `.../incomplete`.
  Move finished books into the right `~/Everything/mentat/books/...` folder — the watcher then indexes them.

## Safety facts (verified)
- Exit IP is Proton (e.g. `146.70.217.104`), never the home IP.
- **Kill switch tested:** with gluetun stopped, the torrent container has **no internet**.

## Optional upgrades
- **Port forwarding** (faster torrents): set `VPN_PORT_FORWARDING=on` in `.env`, then read the
  assigned port and set it in qBittorrent (Connection → Port). 
- Change server/country: edit `SERVER_COUNTRIES` in `docker-compose.yml`.
