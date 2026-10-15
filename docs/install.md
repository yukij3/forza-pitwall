# Installing Pitwall

Pitwall is a single process that receives the game's telemetry over UDP and
serves a web UI over HTTP. The usual way to run it is the Docker image; running
it directly with Python is also supported.

- [What you need](#what-you-need)
- [Docker Compose](#docker-compose)
- [docker run](#docker-run)
- [Home server or NAS](#home-server-or-nas)
- [Without Docker](#without-docker)
- [Configuration](#configuration)
- [File permissions](#file-permissions)
- [Firewall and network](#firewall-and-network)
- [Troubleshooting: no packets](#troubleshooting-no-packets)
- [Updating and backups](#updating-and-backups)

## What you need

- Forza Motorsport (2023) with Data Out set up as described in the
  [README](../README.md#set-up-data-out-in-the-game).
- A machine on the same local network as the device running the game, with
  Docker (Compose v2 for the Compose setup). It can be the gaming PC itself, a
  home server, a NAS or a Raspberry Pi-class board with a 64-bit OS: release
  images are built for `linux/amd64` and `linux/arm64`.
- Two ports on that machine: **5300/udp** for telemetry and **5301/tcp** for
  the web UI.

## Docker Compose

The repository contains an example [`compose.yaml`](../compose.yaml) that builds
the image from source:

```bash
git clone https://github.com/yukij3/forza-pitwall.git
cd forza-pitwall
mkdir -p data
# edit compose.yaml: set PITWALL_PUBLIC_HOST to this machine's LAN IP
docker compose up -d --build
```

Create `data/` yourself before the first start. If Docker creates it, it is
owned by root and the container (which does not run as root) cannot write to
it. See [File permissions](#file-permissions).

To use a published release image instead of building, replace `build: .` in
`compose.yaml` with `image: ghcr.io/yukij3/forza-pitwall:latest`, then run
`docker compose up -d`.

## docker run

The same setup without Compose:

```bash
mkdir -p data
docker run -d --name pitwall --restart unless-stopped \
  -p 5300:5300/udp \
  -p 5301:5301 \
  -v "$PWD/data:/data" \
  -e PITWALL_PUBLIC_HOST=192.168.1.20 \
  ghcr.io/yukij3/forza-pitwall:latest
```

Replace `192.168.1.20` with the LAN IP of the machine running the container.
Note the `/udp` on the first port: without it Docker publishes TCP only and the
game's packets never arrive.

Release images are tagged with the version (`0.1.0`), the minor series (`0.1`)
and `latest`.

## Home server or NAS

Container UIs on NAS systems (Unraid templates, Synology Container Manager,
QNAP Container Station, Portainer and similar) ask for the same few things.
With an Unraid-style template:

| Field | Value |
|---|---|
| Repository | `ghcr.io/yukij3/forza-pitwall:latest` |
| Network type | Bridge |
| Port | container `5300`, host `5300`, connection type **UDP** |
| Port | container `5301`, host `5301`, connection type TCP |
| Path | container `/data`, host a persistent folder such as `/mnt/user/appdata/pitwall` |
| Variable | `PITWALL_PUBLIC_HOST` = the server's LAN IP |

Things that commonly go wrong:

- **The UDP port is added as TCP.** Many UIs default new ports to TCP. The
  telemetry port must be UDP.
- **The data folder is not writable.** The image runs as UID:GID 1000:1000.
  Unraid's appdata shares usually belong to `nobody:users` (99:100). Either add
  `--user 99:100` to the template's extra parameters, or give the folder to
  UID 1000 with `chown -R 1000:1000 /mnt/user/appdata/pitwall`.
- **The UI is reachable but no telemetry arrives.** Make sure the game sends to
  the server's IP, not to the container's internal address (`172.x.x.x` on the
  default bridge network).

Host networking also works on Linux (`network_mode: host` in Compose,
`--network host` with `docker run`). Port mappings are then ignored and Pitwall
listens directly on the ports set by `PITWALL_UDP_PORT` and `PITWALL_HTTP_PORT`.

Pitwall has no authentication. Keep it on the local network; do not forward its
ports on your router or expose it through a reverse proxy to the internet.

## Without Docker

You need Python 3.12 and [uv](https://docs.astral.sh/uv/):

```bash
git clone https://github.com/yukij3/forza-pitwall.git
cd forza-pitwall
uv sync
PITWALL_PUBLIC_HOST=192.168.1.20 uv run python -m pitwall serve
```

On Windows PowerShell, set the variable with
`$env:PITWALL_PUBLIC_HOST = "192.168.1.20"` before the `uv run` line. Data goes
to `./data` unless `PITWALL_DATA_DIR` says otherwise.

## Configuration

All settings are environment variables.

| Variable | Default | Meaning |
|---|---|---|
| `PITWALL_UDP_PORT` | `5300` | UDP port to receive Data Out telemetry on |
| `PITWALL_HTTP_PORT` | `5301` | TCP port for the web UI and API |
| `PITWALL_BIND` | `0.0.0.0` | Address to listen on, for both ports. Leave it as is inside a container; the health check connects to `127.0.0.1` |
| `PITWALL_DATA_DIR` | `./data` (`/data` in the image) | Where the SQLite database and raw packet files go |
| `PITWALL_PUBLIC_HOST` | empty | The IP or host name the game should send to. Only used to show the right address in the UI's setup hint |
| `PITWALL_LIVE_HZ` | `20` | Update rate of the live view, in messages per second |
| `PITWALL_WEB_DIR` | `web/` in the repository (`/app/web` in the image) | Directory of the static web UI |

### Changing ports

With Docker's default bridge network, the simplest way is to change only the
host side of the mapping and leave the container ports alone. For example, to
receive telemetry on 5400 and serve the UI on 8080:

```yaml
    ports:
      - "5400:5300/udp"
      - "8080:5301"
```

Then set the game's Data Out IP Port to `5400`. With host networking, or
without Docker, set `PITWALL_UDP_PORT` and `PITWALL_HTTP_PORT` instead.

## File permissions

The container runs as an unprivileged user, UID 1000 and GID 1000, and needs
write access to `/data`.

- **Docker Desktop (Windows, macOS):** bind mounts work without extra steps.
- **Linux:** create the data folder as your user before the first start
  (`mkdir -p data`). The first user account on most distributions is UID 1000,
  so that is enough. If your UID differs (check with `id -u`), either run the
  container as your user (`user: "1001:1001"` in Compose, `--user 1001:1001`
  with `docker run`) or `chown 1000:1000` the folder.
- **Named volumes** (`-v pitwall-data:/data`) need no setup; Docker creates them
  with the right owner.

## Firewall and network

Data Out is one-way UDP from the game to Pitwall. Nothing connects back to the
game.

**The PC running the game** only sends. Windows Firewall allows outbound
traffic by default, so there is nothing to change there unless you have set up
rules that block outbound traffic.

**The machine running Pitwall** must accept inbound UDP on 5300 and TCP on
5301 from your local network:

- **Linux with ufw:** `sudo ufw allow 5300/udp` and `sudo ufw allow 5301/tcp`.
  Ports published by Docker usually bypass ufw because Docker manages its own
  iptables rules, so in a container they are often reachable already. Without
  Docker you need these rules.
- **Linux with firewalld:**
  `sudo firewall-cmd --permanent --add-port=5300/udp --add-port=5301/tcp`
  followed by `sudo firewall-cmd --reload`.
- **Windows** (Pitwall on a Windows machine, with Docker Desktop or directly
  with Python): Windows Firewall blocks unsolicited inbound traffic. If it asks
  whether to allow Python or Docker on the network, allow it for private
  networks. To add rules by hand, in an administrator PowerShell:

  ```powershell
  New-NetFirewallRule -DisplayName "Pitwall telemetry" -Direction Inbound -Protocol UDP -LocalPort 5300 -Action Allow -Profile Private
  New-NetFirewallRule -DisplayName "Pitwall web UI" -Direction Inbound -Protocol TCP -LocalPort 5301 -Action Allow -Profile Private
  ```

  These rules apply to networks Windows treats as Private. If your home network
  is set to Public, change it to Private in the network settings.
- **macOS:** if the application firewall is on, allow incoming connections for
  Python or Docker when asked.

If the game and Pitwall run on the same PC and the game sends to `127.0.0.1`,
the traffic never leaves the machine and firewalls are not involved.

On the network side, the game and Pitwall need to reach each other directly.
Guest Wi-Fi networks, "client isolation" or "AP isolation" on a router, separate
VLANs and VPN clients on the gaming PC can all stop the packets. No port
forwarding is needed or wanted.

## Troubleshooting: no packets

Work through these in order while you are on track in the game.

1. **Check what Pitwall sees.** The UI shows the receiver status, and so does
   the API: `curl http://<host>:5301/api/status`. While you are driving,
   `receiver.packets_per_sec` should be about 60 on console or 120 to 160 on
   PC, and `last_packet_age_s` should stay small.
2. **Be on track.** The game starts sending once you are on track. In menus and
   while paused it reports that no race is running, and Pitwall does not record
   those frames.
3. **Check the game's Data Out settings.** Data Out is On; the IP address is
   the LAN IP of the machine running Pitwall (not the container's `172.x.x.x`
   address, not the router); the port matches the host side of the UDP mapping;
   the packet format is **Car Dash**. The Sled format lacks lap times, inputs
   and tire temperatures, so Pitwall cannot use it; `/api/status` then shows
   `ignored_packets` rising and `last_ignored_size` 232. If the server gets its IP
   from DHCP, give it a fixed address (a DHCP reservation in the router) so the
   game's setting stays correct.
4. **Check that the port is published as UDP.** `docker ps` should show
   `0.0.0.0:5300->5300/udp`. If it shows `5300/tcp`, fix the mapping.
5. **See whether packets reach the machine.** On a Linux host:
   `sudo tcpdump -ni any udp port 5300`. On Windows, Wireshark does the same.
   - Packets show up there but not in Pitwall: the problem is the port mapping
     or the container. Check `docker ps` and the logs.
   - Nothing shows up: the problem is between the game and the machine: the
     game's settings, the firewall on the receiving machine, or network
     isolation (see [Firewall and network](#firewall-and-network)).
6. **Check for another program on the port.** Data Out goes to a single IP and
   port. If another telemetry app (a dash app, motion rig software) also
   listens on 5300 on the same machine, only one of them gets the packets. Use
   a different port for one of them, or chain them if one of the apps can
   forward packets.
7. **Read the logs.** `docker compose logs -f pitwall` (or `docker logs -f
   pitwall`) shows startup errors such as a port that is already in use.

The container's health status (`docker ps`) only tells you whether the web
server answers. A healthy container can still be receiving no telemetry.

## Updating and backups

- **Built from source:** `git pull`, then `docker compose up -d --build`.
- **Published image:** `docker compose pull`, then `docker compose up -d`.

If the release notes say that lap splitting or the analysis changed, rebuild
the laps of existing recordings from their raw packets, then restart:

```bash
docker compose exec pitwall python -m pitwall reindex
docker compose restart pitwall
```

Without Docker, run `uv run python -m pitwall reindex`. Cached analysis results
are recomputed automatically when the analysis version changes; `reindex` is
only needed for the laps. See [storage.md](storage.md#rebuilding-laps-reindex).

Everything Pitwall stores is in the data folder, which survives updates. To
back it up, stop the container and copy the folder; copying the SQLite database
while Pitwall is writing to it can produce an inconsistent copy.
