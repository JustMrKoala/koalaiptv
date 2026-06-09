#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║       ___                                                                    ║
║     {~._.~}   KoalaIPTV v1.5 (PyInstaller onefile + icon)                    ║
║      ( Y )    Zero Bullshit. Just Streams.                                   ║
║     ()~*~()   Live • VOD • Series • yt-dlp Powered                           ║
║     (_)-(_)                                                                  ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import sys
import json
import re
import argparse
import subprocess
import urllib.request
import shutil
import os
import tempfile
import zipfile
from pathlib import Path
from typing import Optional

VERSION = "1.5"

CONFIG_PATH = Path.home() / ".koala_iptv" / "config.json"
M3U_CACHE_PATH = Path.home() / ".koala_iptv" / "playlist.m3u"


def ensure_config_dir():
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)


def load_config() -> dict:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            return json.load(f)
    return {}


def save_config(cfg: dict):
    ensure_config_dir()
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)


def get_executable_path() -> Path:
    """Returns the true path of the running executable or script."""
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve()
    return Path(__file__).resolve()


def setup_system_path(quiet: bool = False):
    """Attempts to add the executable to the system PATH globally as 'koalaiptv'.
    Called on every run (quietly) so that after updates or moving the portable folder,
    the current location is always registered and 'koalaiptv' keeps working.
    """
    exe_path = get_executable_path()
    exe_dir = exe_path.parent
    
    if not quiet:
        print("[*] 🐨 Configuring system PATH settings...")

    # --- WINDOWS PATH CONFIGURATION ---
    if os.name == 'nt':
        import winreg
        try:
            reg_key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment", 0, winreg.KEY_ALL_ACCESS)
            try:
                current_path, _ = winreg.QueryValueEx(reg_key, "Path")
            except FileNotFoundError:
                current_path = ""

            if str(exe_dir) not in current_path:
                new_path = f"{current_path};{exe_dir}" if current_path else str(exe_dir)
                winreg.SetValueEx(reg_key, "Path", 0, winreg.REG_EXPAND_SZ, new_path)
                # Broadcast environment change to system
                import ctypes
                ctypes.windll.user32.SendMessageW(0xFFFF, 0x001A, 0, "Environment")
                print(f"[+] Added {exe_dir} to your Windows User PATH.")
                print("[!] Note: You may need to restart your terminal window for 'koalaiptv' to activate.")
            elif not quiet:
                print("[+] 'koalaiptv' directory is already in your Windows PATH.")
        except Exception as e:
            if not quiet:
                print(f"[-] Could not automatically modify Windows Registry PATH: {e}")

    # --- LINUX / MACOS PATH CONFIGURATION ---
    else:
        local_bin = Path.home() / ".local" / "bin"
        local_bin.mkdir(parents=True, exist_ok=True)
        symlink_path = local_bin / "koalaiptv"

        try:
            if symlink_path.exists() or symlink_path.is_symlink():
                symlink_path.unlink()
            
            symlink_path.symlink_to(exe_path)
            if not quiet:
                print(f"[+] Created system symlink at: {symlink_path}")
            
            # Check if ~/.local/bin is in the active PATH shell environment
            if str(local_bin) not in os.environ.get("PATH", ""):
                if not quiet:
                    print(f"[!] Warning: {local_bin} is not in your system PATH variable.")
                    print("    To fix this, add this line to your ~/.bashrc or ~/.zshrc file:")
                    print(f'    export PATH="$HOME/.local/bin:$PATH"')
        except Exception as e:
            if not quiet:
                print(f"[-] Could not automatically create system symlink: {e}")


def download_file(url: str, dest: Path, show_progress: bool = True) -> bool:
    """Download a file with optional simple progress."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": f"KoalaIPTV-Updater/{VERSION}"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            total = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            block_size = 8192
            dest.parent.mkdir(parents=True, exist_ok=True)
            with open(dest, "wb") as f:
                while True:
                    chunk = resp.read(block_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if show_progress and total > 0:
                        pct = int(downloaded * 100 / total)
                        print(f"\r[*] Downloading update... {pct}% ({downloaded // 1024}KB)", end="", flush=True)
            if show_progress:
                print("\n[+] Download complete.")
        return True
    except Exception as e:
        print(f"\n[-] Download failed: {e}")
        return False


def find_app_root(search_dir: Path) -> Path:
    """Locate the folder inside an extracted archive that contains koalaiptv.exe."""
    direct = search_dir / "koalaiptv.exe"
    if direct.exists():
        return search_dir
    # Check immediate subdirs (common when zipping a versioned folder)
    for child in search_dir.iterdir():
        if child.is_dir():
            if (child / "koalaiptv.exe").exists():
                return child
    # Deep search as last resort
    for p in search_dir.rglob("koalaiptv.exe"):
        return p.parent
    raise FileNotFoundError("koalaiptv.exe not found inside the archive.")


def spawn_windows_updater(target_dir: Path, source_dir: Path):
    """Write and launch a detached batch that applies the update after current process exits."""
    if os.name != "nt":
        print("[-] Safe self-update currently supports Windows only.")
        return False

    bat_path = Path(tempfile.gettempdir()) / "koalaiptv-apply-update.bat"
    new_exe = source_dir / "koalaiptv.exe"

    # Build a robust updater batch. Uses robocopy for reliable folder sync.
    # Simplified header to avoid mysterious ". was unexpected at this time." parser errors
    # that can occur with chcp + EnableDelayedExpansion + UTF-8 .bat files on some setups.
    bat = f'''@echo off
setlocal

set "TARGET={target_dir}"
set "SOURCE={source_dir}"

echo.
echo [*] KoalaIPTV Self-Updater v{VERSION}
echo     Preparing to apply update...
echo     Current install: %TARGET%
echo.

echo     Waiting a moment for the running instance to release file locks...
timeout /t 3 /nobreak >nul 2>&1

echo     Syncing new files...
robocopy "%SOURCE%" "%TARGET%" /E /PURGE /R:5 /W:2 /NFL /NDL /NJH /NJS /NC /NS
if errorlevel 8 (
  echo [-] Robocopy reported serious errors (code %errorlevel%).
  echo     You may need to manually copy files from:
  echo     %SOURCE%
) else (
  echo [+] Update files applied successfully.
)

echo     Removing temporary update files...
rmdir /s /q "%SOURCE%" >nul 2>&1

echo.
echo [+] KoalaIPTV has been updated.
echo     You can now run koalaiptv normally.
echo.
echo Press any key to close this window...
pause >nul
exit /b 0
'''

    try:
        with open(bat_path, "w", encoding="utf-8") as f:
            f.write(bat)
        # Launch in a new visible window so user can see progress / errors.
        # Using a new console makes it survive the parent exit cleanly.
        subprocess.Popen(
            f'cmd /c start "KoalaIPTV Updater" "{bat_path}"',
            shell=True,
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
        return True
    except Exception as e:
        print(f"[-] Failed to launch updater: {e}")
        print(f"    Manual fallback: copy contents of {source_dir} over {target_dir}")
        return False


def cmd_update(args):
    """Self-update the portable Windows build in-place without conflicts."""
    exe_path = get_executable_path()
    if not getattr(sys, "frozen", False):
        print("[-] Update is only supported for the PyInstaller-built .exe distribution.")
        print("    Run from the installed koalaiptv.exe (not from source .py).")
        return

    install_dir = exe_path.parent
    print(f"[*] Current install dir: {install_dir}")
    print(f"[*] Current version marker: {VERSION} (this binary)")

    # Determine source URL
    url = getattr(args, "url", None)
    repo = getattr(args, "repo", None) or load_config().get("update_repo") or "JustMrKoala/koalaiptv"

    if not url and repo:
        print(f"[*] Checking GitHub for latest release in {repo} ...")
        api = f"https://api.github.com/repos/{repo}/releases/latest"
        try:
            req = urllib.request.Request(api, headers={"User-Agent": f"KoalaIPTV-Updater/{VERSION}", "Accept": "application/vnd.github+json"})
            with urllib.request.urlopen(req, timeout=30) as r:
                rel = json.loads(r.read().decode())
            tag = rel.get("tag_name", "unknown")
            print(f"[+] Latest release: {tag}")
            assets = rel.get("assets", [])
            # Prefer assets that look like our portable win build (e.g. koalaiptv1.4win.zip)
            candidates = [a for a in assets if a.get("name", "").lower().endswith(".zip")]
            win_asset = None
            def _score(n: str) -> int:
                n = n.lower()
                s = 0
                if "koalaiptv" in n: s += 10
                if "win" in n or "windows" in n: s += 5
                if "portable" in n: s += 3
                if any(x in n for x in ("src", "source", "linux", "mac", "darwin", "code")): s -= 20
                return s
            if candidates:
                scored = sorted(candidates, key=lambda a: _score(a.get("name", "")), reverse=True)
                win_asset = scored[0]
            if win_asset:
                url = win_asset.get("browser_download_url")
                print(f"[*] Selected asset: {win_asset.get('name')}")
            else:
                print("[-] No suitable .zip asset found in the latest release.")
        except Exception as e:
            print(f"[-] GitHub check failed: {e}")

    if not url:
        print("\n[!] No update URL available.")
        print("    Provide one explicitly:")
        print(f"      koalaiptv update --url https://github.com/JustMrKoala/koalaiptv/releases/download/{VERSION}/koalaiptv{VERSION}win.zip")
        print("    Or it will auto-use the default repo (JustMrKoala/koalaiptv) when you run:")
        print("      koalaiptv update")
        print("    (Or set a different one with: koalaiptv configure --update-repo owner/repo )")
        return

    print(f"[*] Update package: {url}")

    if not getattr(args, "yes", False):
        confirm = input("Download and apply this update now? [y/N]: ").strip().lower()
        if confirm not in ("y", "yes"):
            print("[-] Update cancelled.")
            return

    tmp_zip = Path(tempfile.gettempdir()) / f"koalaiptv_update_{os.getpid()}.zip"
    tmp_extract = Path(tempfile.mkdtemp(prefix="koalaiptv_new_"))

    print("[*] Downloading...")
    if not download_file(url, tmp_zip):
        shutil.rmtree(tmp_extract, ignore_errors=True)
        return

    print("[*] Extracting archive...")
    try:
        with zipfile.ZipFile(tmp_zip) as z:
            z.extractall(tmp_extract)
    except Exception as e:
        print(f"[-] Extract failed: {e}")
        shutil.rmtree(tmp_extract, ignore_errors=True)
        tmp_zip.unlink(missing_ok=True)
        return

    try:
        source_dir = find_app_root(tmp_extract)
        print(f"[*] Update content found at: {source_dir}")
    except Exception as e:
        print(f"[-] {e}")
        shutil.rmtree(tmp_extract, ignore_errors=True)
        tmp_zip.unlink(missing_ok=True)
        return

    # Verify it looks valid
    if not (source_dir / "koalaiptv.exe").exists():
        print("[-] Archive did not contain a valid koalaiptv.exe. Aborting.")
        shutil.rmtree(tmp_extract, ignore_errors=True)
        tmp_zip.unlink(missing_ok=True)
        return

    print("[*] Preparing safe in-place update (will not conflict with running copy)...")
    ok = spawn_windows_updater(install_dir, source_dir)
    if ok:
        print("\n[+] Updater launched in a new window. This process will now exit so files can be replaced.")
        print("    A separate console window is applying the update (wait + robocopy).")
        print("    Watch the new window for progress. It will pause at the end so you can read any messages.")
        print("    After it finishes, run 'koalaiptv' again to use the new version.")
        # Give the Popen a moment, then exit hard so locks are released ASAP
        import time
        time.sleep(0.4)
        os._exit(0)
    else:
        print("[-] Could not start automatic updater.")
        print(f"    New files are here: {source_dir}")
        print(f"    Please close KoalaIPTV completely and copy them manually over {install_dir}")


def fetch_url(url: str) -> dict | list:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        print(f"[-] API Fetch Error: {e}")
        return []


def xtream_to_m3u(host: str, username: str, password: str, output: Optional[Path] = None) -> Path:
    host = host.rstrip("/")
    base = f"{host}/player_api.php?username={username}&password={password}"

    print("[*] 🐨 Fetching live streams...")
    live_cats = fetch_url(f"{base}&action=get_live_categories")
    live_streams = fetch_url(f"{base}&action=get_live_streams")

    print("[*] 🐨 Fetching VOD...")
    vod_cats = fetch_url(f"{base}&action=get_vod_categories")
    vod_streams = fetch_url(f"{base}&action=get_vod_streams")

    print("[*] 🐨 Fetching series...")
    series_cats = fetch_url(f"{base}&action=get_series_categories")
    series_list = fetch_url(f"{base}&action=get_series")

    def cat_name(cats, cid):
        for c in cats:
            if isinstance(c, dict) and str(c.get("category_id")) == str(cid):
                return c.get("category_name", "Uncategorized")
        return "Uncategorized"

    lines = ["#EXTM3U"]

    if isinstance(live_streams, list):
        for s in live_streams:
            name = s.get("name", "Unknown")
            logo = s.get("stream_icon", "")
            cat = cat_name(live_cats, s.get("category_id", ""))
            sid = s.get("stream_id")
            url = f"{host}/live/{username}/{password}/{sid}.ts"
            lines.append(f'#EXTINF:-1 tvg-logo="{logo}" group-title="{cat}",{name}')
            lines.append(url)

    if isinstance(vod_streams, list):
        for s in vod_streams:
            name = s.get("name", "Unknown")
            logo = s.get("stream_icon", "")
            cat = cat_name(vod_cats, s.get("category_id", ""))
            sid = s.get("stream_id")
            ext = s.get("container_extension", "mp4")
            url = f"{host}/movie/{username}/{password}/{sid}.{ext}"
            lines.append(f'#EXTINF:-1 tvg-logo="{logo}" group-title="VOD: {cat}",{name}')
            lines.append(url)

    if isinstance(series_list, list):
        for s in series_list:
            name = s.get("name", "Unknown")
            logo = s.get("cover", "")
            cat = cat_name(series_cats, s.get("category_id", ""))
            sid = s.get("series_id")
            url = f"xtream://series/{sid}"
            lines.append(f'#EXTINF:-1 tvg-logo="{logo}" group-title="Series: {cat}" series-id="{sid}",{name}')
            lines.append(url)

    dest = output or M3U_CACHE_PATH
    ensure_config_dir()
    with open(dest, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    live_count = len(live_streams) if isinstance(live_streams, list) else 0
    vod_count = len(vod_streams) if isinstance(vod_streams, list) else 0
    series_count = len(series_list) if isinstance(series_list, list) else 0

    print(f"[+] Playlist saved to {dest} ({live_count} live, {vod_count} VOD, {series_count} series)")
    return dest


def parse_m3u(path: Path) -> list[dict]:
    entries = []
    current = {}
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if line.startswith("#EXTINF"):
                m_logo = re.search(r'tvg-logo="([^"]*)"', line)
                m_group = re.search(r'group-title="([^"]*)"', line)
                m_name = re.search(r",(.+)$", line)
                m_series = re.search(r'series-id="([^"]*)"', line)
                current = {
                    "name": m_name.group(1).strip() if m_name else "Unknown",
                    "logo": m_logo.group(1) if m_logo else "",
                    "group": m_group.group(1) if m_group else "",
                    "series_id": m_series.group(1) if m_series else None,
                    "url": "",
                }
            elif line and not line.startswith("#") and current:
                current["url"] = line
                entries.append(current)
                current = {}
    return entries


def search_channels(entries: list[dict], query: str, group_filter: Optional[str] = None) -> list[dict]:
    q = query.lower()
    results = []
    for e in entries:
        name_match = q in e["name"].lower()
        group_match = not group_filter or group_filter.lower() in e["group"].lower()
        if name_match and group_match:
            results.append(e)
    return results


def display_results(results: list[dict], page: int = 0, page_size: int = 20):
    total = len(results)
    start = page * page_size
    end = min(start + page_size, total)
    print(f"\n{'='*60}")
    print(f"Results {start+1}-{end} of {total}")
    print(f"{'='*60}")
    for i, e in enumerate(results[start:end], start=start):
        tag = "[Series]" if e.get("series_id") else ""
        group = f"[{e['group']}]" if e["group"] else ""
        print(f" {i+1:>4}. {e['name']} {tag} {group}")
    print(f"{'='*60}\n")


def check_yt_dlp():
    return shutil.which("yt-dlp") is not None


def find_ffmpeg() -> Optional[str]:
    path = shutil.which("ffmpeg")
    if path:
        return path
    
    common = [
        Path("C:/ffmpeg/bin/ffmpeg.exe"),
        Path("C:/Program Files/ffmpeg/bin/ffmpeg.exe"),
        Path.home() / "ffmpeg" / "bin" / "ffmpeg.exe",
        Path("/usr/bin/ffmpeg"),
        Path("/usr/local/bin/ffmpeg"),
    ]
    for p in common:
        if p.exists():
            return str(p)
    return None


def sanitize(name: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "_", str(name)).strip("_ ")


def download_episode(host: str, username: str, password: str, series_name: str, season: str, ep: dict, ep_index: int, output_root: Path, fmt: Optional[str] = None):
    ep_num = ep.get("episode_num") or (ep_index + 1)
    title = ep.get("title", f"Episode {ep_num}")
    stream_id = ep.get("id")
    ext = ep.get("container_extension", "mp4")
    url = f"{host}/series/{username}/{password}/{stream_id}.{ext}"
    out_name = f"{series_name} S{int(season):02d}E{int(ep_num):02d} - {title}"

    try:
        season_num = int(season)
        season_folder = f"Season {season_num:02d}"
    except (ValueError, TypeError):
        season_folder = f"Season {season}"

    safe_show = sanitize(series_name)
    season_dir = output_root / safe_show / season_folder
    download_stream(url, out_name, season_dir, fmt)


def download_stream(url: str, output_name: str, output_dir: Path, format_opts: Optional[str] = None):
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_name = sanitize(output_name)
    out_path = output_dir / f"{safe_name}.mp4"

    ffmpeg = find_ffmpeg()

    cmd = [
        "yt-dlp",
        "--no-playlist",
        "--merge-output-format", "mp4",
        "--output", str(out_path),
        "--socket-timeout", "30",
        "--retries", "20",
        "--fragment-retries", "20",
        "--retry-sleep", "3",
        "--hls-use-mpegts",
        "--user-agent", "VLC/3.0.9 LibVLC/3.0.9"
    ]

    if ffmpeg:
        cmd += ["--ffmpeg-location", ffmpeg]
        cmd += ["-f", format_opts if format_opts else "bestvideo+bestaudio/best"]
    else:
        print("\n[!] ffmpeg not found — downloading best single-file stream.")
        cmd += ["-f", format_opts if format_opts else "best"]

    cmd += ["--", url]

    print(f"[*] 🐨 Downloading: {output_name}")
    print(f"    URL: {url}")
    print(f"    Output: {out_path}\n")

    try:
        subprocess.run(cmd, check=True)
        print(f"\n[+] Saved to: {out_path}")
    except subprocess.CalledProcessError as e:
        print(f"\n[-] Download failed: {e}")


def browse_series(entry: dict, output_dir: Path):
    cfg = load_config()
    host = cfg.get("host", "").rstrip("/")
    username = cfg.get("username", "")
    password = cfg.get("password", "")

    if not all([host, username, password]):
        print("[-] Credentials missing. Run 'koalaiptv configure'.")
        return

    series_id = entry["series_id"]
    print(f"\n[*] Fetching episodes for: {entry['name']}...")

    try:
        data = fetch_url(
            f"{host}/player_api.php?username={username}&password={password}"
            f"&action=get_series_info&series_id={series_id}"
        )
        if not isinstance(data, dict):
            data = {}
    except Exception as e:
        print(f"[-] Could not fetch series info: {e}")
        return

    episodes_by_season: dict[str, list] = {}
    raw_episodes = data.get("episodes", {})
    
    if isinstance(raw_episodes, dict):
        for season_num, eps in raw_episodes.items():
            episodes_by_season[str(season_num)] = eps
    elif isinstance(raw_episodes, list):
        episodes_by_season["1"] = raw_episodes

    if not episodes_by_season:
        print("[-] No episodes found for this series.")
        return

    seasons = sorted(episodes_by_season.keys(), key=lambda x: int(x) if x.isdigit() else 0)

    while True:
        print(f"\n Seasons for: {entry['name']}")
        print(f" {'='*40}")
        for i, s in enumerate(seasons, 1):
            count = len(episodes_by_season[s])
            print(f"  {i}. Season {s} ({count} episodes)")
        print(f" {'='*40}")

        pick = input(" Season number (or [b]ack, or all): ").strip().lower()
        if pick == "b":
            return

        if pick == "all":
            fmt = input(" Format override (leave blank for best): ").strip() or None
            print(f"[*] Downloading ALL episodes for {entry['name']} sequentially (no async)...")
            for season_key in seasons:
                eps = episodes_by_season[season_key]
                print(f"\n--- Season {season_key} ---")
                for idx, ep in enumerate(eps):
                    download_episode(host, username, password, entry["name"], season_key, ep, idx, output_dir, fmt)
            print(f"\n[+] Entire series download complete: {entry['name']}")
            return

        if pick.isdigit():
            idx = int(pick) - 1
            if 0 <= idx < len(seasons):
                season_key = seasons[idx]
                browse_episodes(entry["name"], season_key, episodes_by_season[season_key], host, username, password, output_dir)
            else:
                print(" [-] Invalid season.")


def browse_episodes(series_name: str, season: str, episodes: list, host: str, username: str, password: str, output_dir: Path):
    while True:
        print(f"\n Season {season} episodes:")
        print(f" {'='*40}")
        for i, ep in enumerate(episodes, 1):
            ep_num = ep.get("episode_num", i)
            title = ep.get("title", f"Episode {ep_num}")
            print(f"  {i}. Ep {ep_num}: {title}")
        print(f" {'='*40}")

        pick = input(" Episode number to download (or [b]ack, or all): ").strip().lower()
        if pick == "b":
            return

        if pick == "all":
            fmt = input(" Format override (leave blank for best): ").strip() or None
            print(f"[*] Downloading all {len(episodes)} episodes sequentially (no async)...")
            for idx, ep in enumerate(episodes):
                download_episode(host, username, password, series_name, season, ep, idx, output_dir, fmt)
            print("[+] Season download complete.")
            return

        if pick.isdigit():
            idx = int(pick) - 1
            if 0 <= idx < len(episodes):
                ep = episodes[idx]
                fmt = input(" Format override (leave blank for best): ").strip() or None
                download_episode(host, username, password, series_name, season, ep, idx, output_dir, fmt)
            else:
                print(" [-] Invalid episode.")


def interactive_search(m3u_path: Path, output_dir: Path):
    print(f"[*] Loading M3U from {m3u_path}...")
    entries = parse_m3u(m3u_path)
    print(f"[+] Loaded {len(entries)} entries.\n")
    print(" Just type to search. Commands: groups, quit\n")

    while True:
        raw = input("koalaiptv> ").strip()
        if not raw:
            continue

        if raw.lower() in ("quit", "exit", "q"):
            print("Catch ya later! 🐨")
            break

        if raw.lower() == "groups":
            groups = sorted(set(e["group"] for e in entries if e["group"]))
            for g in groups:
                print(f"  {g}")
            print()
            continue

        query = raw[7:].strip() if raw.lower().startswith("search ") else raw
        group_filter = None

        if " in:" in query:
            parts = query.split(" in:", 1)
            query = parts[0].strip()
            group_filter = parts[1].strip()

        results = search_channels(entries, query, group_filter)

        if not results:
            print("[-] No results found.\n")
            continue

        page = 0
        page_size = 20

        while True:
            display_results(results, page, page_size)
            total_pages = (len(results) - 1) // page_size

            nav = input("Enter number to select, [n]ext, [p]rev, [b]ack: ").strip().lower()

            if nav == "b":
                break
            if nav == "n" and page < total_pages:
                page += 1
                continue
            if nav == "p" and page > 0:
                page -= 1
                continue

            if nav.isdigit():
                idx = int(nav) - 1
                if 0 <= idx < len(results):
                    chosen = results[idx]
                    print(f"\n[*] Selected: {chosen['name']}")
                    print(f"    Group: {chosen['group']}")

                    if chosen.get("series_id"):
                        browse_series(chosen, output_dir)
                    else:
                        print(f"    URL: {chosen['url']}")
                        fmt = input("Format override (leave blank for best): ").strip() or None
                        download_stream(chosen["url"], chosen["name"], output_dir, fmt)
                else:
                    print("[-] Invalid number.")


def prompt(label: str, current: Optional[str] = None, required: bool = True) -> Optional[str]:
    hint = f" [{current}]" if current else ""
    suffix = " (leave blank to keep)" if current else (" (required)" if required else " (optional, press Enter to skip)")
    display = f"{label}{hint}{suffix}: "
    while True:
        value = input(display).strip()
        if value:
            return value
        if current:
            return current
        if not required:
            return None
        print(" This field is required.")


def run_wizard(cfg: dict, fresh: bool = False) -> dict:
    if fresh:
        print("\n" + "=" * 56)
        print(" Welcome to KoalaIPTV -- first-time setup 🐨")
        print("=" * 56 + "\n")
        
        # Setup environment variables so the terminal recognizes 'koalaiptv'
        setup_system_path()
        
        print("\n Please configure your Xtream Codes provider details:")
    else:
        print("\n" + "=" * 56)
        print(" KoalaIPTV -- reconfigure")
        print("=" * 56 + "\n")

    print(" Step 1/4 Provider host")
    print(" The base URL of your Xtream provider, e.g.")
    print(" http://myiptv.com:8080 or https://streams.example.com\n")
    cfg["host"] = prompt(" Host", current=cfg.get("host"))

    print("\n Step 2/4 Username")
    cfg["username"] = prompt(" Username", current=cfg.get("username"))

    print("\n Step 3/4 Password")
    cfg["password"] = prompt(" Password", current=cfg.get("password"))

    print("\n Step 4/4 Download folder")
    print(" Where finished MP4 files will be saved.")
    default_dir = cfg.get("output_dir", str(Path.home() / "Videos" / "KoalaIPTV"))
    cfg["output_dir"] = prompt(" Output dir", current=default_dir)

    save_config(cfg)
    print("\n[+] Configuration saved.")
    print(f"    Config file: {CONFIG_PATH}\n")

    fetch_now = input(" Fetch M3U playlist now? [Y/n]: ").strip().lower()
    if fetch_now in ("", "y", "yes"):
        print()
        xtream_to_m3u(cfg["host"], cfg["username"], cfg["password"])

    print()
    return cfg


def cmd_configure(args):
    cfg = load_config()
    flags = [args.host, args.username, args.password, getattr(args, "output_dir", None), getattr(args, "update_repo", None)]
    if any(flags):
        if args.host:
            cfg["host"] = args.host
        if args.username:
            cfg["username"] = args.username
        if args.password:
            cfg["password"] = args.password
        if getattr(args, "output_dir", None):
            cfg["output_dir"] = args.output_dir
        if getattr(args, "update_repo", None):
            cfg["update_repo"] = args.update_repo
        save_config(cfg)
        print("[+] Configuration saved.")
    else:
        run_wizard(cfg, fresh=not CONFIG_PATH.exists())


def cmd_convert(args):
    cfg = load_config()
    host = args.host or cfg.get("host")
    username = args.username or cfg.get("username")
    password = args.password or cfg.get("password")
    if not all([host, username, password]):
        print("[-] Provide --host, --username, --password or run configure first.")
        sys.exit(1)
    out = Path(args.output) if args.output else None
    xtream_to_m3u(host, username, password, out)


def cmd_search(args):
    cfg = load_config()
    m3u = Path(args.m3u) if args.m3u else M3U_CACHE_PATH
    if not m3u.exists():
        print(f"[-] M3U not found at {m3u}. Run 'convert' first or pass --m3u.")
        sys.exit(1)
    out_dir = Path(args.output_dir) if args.output_dir else Path(cfg.get("output_dir", "./koala_downloads"))
    interactive_search(m3u, out_dir)


def cmd_download(args):
    cfg = load_config()
    m3u = Path(args.m3u) if args.m3u else M3U_CACHE_PATH
    if not m3u.exists():
        print(f"[-] M3U not found at {m3u}. Run 'convert' first or pass --m3u.")
        sys.exit(1)

    entries = parse_m3u(m3u)
    results = search_channels(entries, args.query, args.group)

    if not results:
        print("[-] No matches found.")
        sys.exit(1)

    if len(results) == 1 or args.first:
        chosen = results[0]
    else:
        display_results(results, page_size=50)
        raw = input("Enter number to download: ").strip()
        if not raw.isdigit():
            print("[-] Cancelled.")
            sys.exit(0)
        idx = int(raw) - 1
        if not (0 <= idx < len(results)):
            print("[-] Invalid number.")
            sys.exit(1)
        chosen = results[idx]

    out_dir = Path(args.output_dir) if args.output_dir else Path(cfg.get("output_dir", "./koala_downloads"))

    if chosen.get("series_id"):
        browse_series(chosen, out_dir)
    else:
        download_stream(chosen["url"], chosen["name"], out_dir, args.format)


def get_latest_version(repo: str = "JustMrKoala/koalaiptv") -> Optional[str]:
    """Quick non-fatal check for the latest release tag on GitHub."""
    try:
        api = f"https://api.github.com/repos/{repo}/releases/latest"
        req = urllib.request.Request(
            api,
            headers={"User-Agent": f"KoalaIPTV/{VERSION}", "Accept": "application/vnd.github+json"}
        )
        with urllib.request.urlopen(req, timeout=6) as r:
            data = json.loads(r.read().decode())
            tag = (data.get("tag_name") or "").lstrip("vV")
            return tag or None
    except Exception:
        return None


def _is_newer_version(latest: str, current: str) -> bool:
    """True only if latest from server is strictly greater than our VERSION."""
    def _t(s: str):
        try:
            return tuple(int(x) for x in s.split(".") if x.strip().isdigit())
        except Exception:
            return (0,)
    try:
        return _t(latest) > _t(current)
    except Exception:
        return False  # never auto-claim "newer" on parse problems


def main():
    first_run = not CONFIG_PATH.exists()
    no_args = len(sys.argv) == 1

    # Ensure the directory of this executable/script is on the user's PATH on every launch.
    # This makes updates (and extracting a new build to a different folder) "just work"
    # without the user having to re-run configure or manually fix PATH.
    # Works for both the PyInstaller .exe and when executing the .py directly.
    try:
        setup_system_path(quiet=True)
    except Exception:
        pass  # never let PATH setup block or crash startup

    # Intercept the very first run without flags
    if first_run and no_args:
        print("[!] First run detected. Starting setup wizard...")
        run_wizard({}, fresh=True)
        print(" Run 'koalaiptv search' to start browsing.\n")
        sys.exit(0)

    parser = argparse.ArgumentParser(
        prog="koalaiptv",
        description="KoalaIPTV: CLI client with Xtream-to-M3U conversion and yt-dlp downloading.",
    )
    parser.add_argument("--version", action="version", version=f"KoalaIPTV {VERSION}")
    
    # Notice: Removed 'required=True' so we can handle empty commands gracefully
    sub = parser.add_subparsers(dest="command")

    p_cfg = sub.add_parser("configure", help="Save connection settings")
    p_cfg.add_argument("--host")
    p_cfg.add_argument("--username")
    p_cfg.add_argument("--password")
    p_cfg.add_argument("--output-dir")
    p_cfg.add_argument("--update-repo", help="GitHub owner/repo for automatic update checks (e.g. yourname/iptvcli)")
    p_cfg.set_defaults(func=cmd_configure)

    p_conv = sub.add_parser("convert", help="Convert Xtream credentials to M3U playlist")
    p_conv.add_argument("--host")
    p_conv.add_argument("--username")
    p_conv.add_argument("--password")
    p_conv.add_argument("--output", help="Destination .m3u file (default: ~/.koala_iptv/playlist.m3u)")
    p_conv.set_defaults(func=cmd_convert)

    p_search = sub.add_parser("search", help="Interactive search and download from M3U")
    p_search.add_argument("--m3u", help="Path to .m3u file")
    p_search.add_argument("--output-dir", help="Where to save downloaded files")
    p_search.set_defaults(func=cmd_search)

    p_dl = sub.add_parser("download", help="Non-interactive: search and download by query")
    p_dl.add_argument("query", help="Search term")
    p_dl.add_argument("--m3u", help="Path to .m3u file")
    p_dl.add_argument("--group", help="Filter by group name")
    p_dl.add_argument("--output-dir", help="Where to save downloaded files")
    p_dl.add_argument("--format", help="yt-dlp format string (default: bestvideo+bestaudio/best)")
    p_dl.add_argument("--first", action="store_true", help="Auto-select first result without prompting")
    p_dl.set_defaults(func=cmd_download)

    p_up = sub.add_parser("update", help="Self-update this portable build (auto-updater, runs from inside koalaiptv)")
    p_up.add_argument("--url", help="Direct download URL to a new portable .zip (recommended for control)")
    p_up.add_argument("--repo", help="GitHub repo (owner/repo) to fetch latest release asset from automatically")
    p_up.add_argument("--yes", "-y", action="store_true", help="Apply without interactive confirmation")
    p_up.set_defaults(func=cmd_update)

    # If they run it without flags AFTER the first time, show the help menu
    # Also opportunistically check for updates so that simply running "koalaiptv"
    # acts as a lightweight auto-updater notifier (no network hit on subcommands).
    if no_args:
        repo = load_config().get("update_repo") or "JustMrKoala/koalaiptv"
        latest = get_latest_version(repo)
        if latest and _is_newer_version(latest, VERSION):
            print(f"\n[!] New version available: {latest}  (you are on {VERSION})")
            print("    Run:  koalaiptv update")
            print("    (or let the built-in updater download + apply the portable build)\n")
            # Offer a seamless auto-update experience when user just double-clicks / runs the exe
            try:
                ans = input("Update to the latest version now? [Y/n]: ").strip().lower()
            except EOFError:
                ans = ""
            if ans in ("", "y", "yes"):
                class _UpdArgs:
                    url = None
                    repo = None
                    yes = True
                try:
                    cmd_update(_UpdArgs())
                    # cmd_update may _exit on success path
                    return
                except SystemExit:
                    return
        parser.print_help()
        sys.exit(0)

    args = parser.parse_args()

    # yt-dlp is only required for commands that actually download streams
    needs_yt = getattr(args, "command", None) in ("search", "download")
    if needs_yt and not check_yt_dlp():
        print("[-] yt-dlp is not installed or not in PATH. Install it with: pip install yt-dlp")
        sys.exit(1)

    # Execute the selected subcommand
    if hasattr(args, 'func'):
        args.func(args)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()