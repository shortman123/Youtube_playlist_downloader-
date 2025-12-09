import os
import sys
import subprocess
import time
import json
import re
import shutil
import threading
import itertools
import concurrent.futures
from yt_dlp import YoutubeDL
from colorama import init, Fore, Style
import psutil
import argparse
import platform

# Auto-install dependencies if missing
def install_dependencies():
    required = ['yt-dlp', 'colorama', 'psutil']
    missing = []
    for pkg in required:
        try:
            __import__(pkg.replace('-', '_'))
        except ImportError:
            missing.append(pkg)
    if missing:
        print(Fore.YELLOW + f"Installing missing packages: {', '.join(missing)}" + Style.RESET_ALL)
        subprocess.check_call([sys.executable, '-m', 'pip', 'install'] + missing)

# Adjust download path for Windows compatibility
def get_download_path():
    default_path = os.getcwd()
    if os.name == 'nt':  # Windows
        default_path = os.path.expanduser('~\\Downloads')
    return prompt_with_default("Enter download folder", default_path)


# Previously, the script used a JSON DB to track downloaded videos.
# You requested a simpler approach: just check whether the expected output file
# exists on disk before attempting a download. All DB and maintenance functions
# were removed for clarity and simplicity.

def normalize_text(s: str) -> str:
    # Minimal normalization utility (kept for backward compatibility) — not used
    if not s:
        return ''
    s = re.sub(r"\.\w{1,5}$", "", s)
    s = re.sub(r"[^\w\s]", "", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip().lower()

def filename_without_ext(fname: str) -> str:
    return os.path.splitext(os.path.basename(fname))[0]

def strip_index_suffix(s: str) -> str:
    """Remove trailing index-like suffixes from a filename base.
    Examples: 'video_1', 'video-1', 'video (1)' -> 'video'
    """
    if not s:
        return ''
    # Remove a trailing underscore/dash/space and number in parentheses: (1)
    s = re.sub(r"\s*\(\d+\)$", "", s)
    # Remove common trailing _1, -1, 1
    s = re.sub(r"[_\-\s]+\d+$", "", s)
    return s

def normalized_basename(s: str, strip_index=True) -> str:
    # Normalizes base names; optionally preserves trailing index if strip_index=False
    if strip_index:
        s = strip_index_suffix(s)
    s = re.sub(r"\.[^\.]+$", "", s)  # remove extension if present
    s = re.sub(r"[^\w\s-]", "", s)  # remove punctuation
    s = re.sub(r"\s+", " ", s)
    return s.strip().lower()

# Remove complex duplicate logic — the script will simply check whether the
# prepared output filename exists on disk before attempting a download.


def download_video(ydl_opts, url, info, force=False, preserve_index=False):
    """Download a single video with the provided ydl options, only if it isn't
    already downloaded. Returns True if the video was downloaded successfully,
    or False if it was skipped or an error occurred."""
    # We will only check whether the prepared target file already exists.

    opts = ydl_opts.copy() if isinstance(ydl_opts, dict) else {}
    try:
        with YoutubeDL(opts) as ydl:
            # prepare_filename uses the template to produce the expected filename
            prepared = ydl.prepare_filename(info)
            # If the exact prepared file already exists (race condition, etc.) consider it downloaded
            if os.path.exists(prepared) and os.path.getsize(prepared) > 0 and not force:
                print(Fore.YELLOW + f"Found existing file: {prepared}. Skipping." + Style.RESET_ALL)
                return False
            # Additionally, check for another file with the same normalized base name
            # (ignores extension and trailing index suffixes like _1 or (1)).
            prepared_base = filename_without_ext(prepared)
            prepared_norm = normalized_basename(prepared_base, strip_index=not preserve_index)
            for fname in os.listdir(download_path):
                fpath = os.path.join(download_path, fname)
                if not os.path.isfile(fpath):
                    continue
                if os.path.getsize(fpath) == 0:
                    continue
                candidate_base = filename_without_ext(fname)
                # For playlist entries, preserve index in normalized comparison
                candidate_norm = normalized_basename(candidate_base, strip_index=not preserve_index)
                if candidate_norm == prepared_norm:
                    print(Fore.YELLOW + f"Found existing matching file: {fpath}. Skipping." + Style.RESET_ALL)
                    return False

            # Do actual download
            ydl.download([url])
            # No DB is used; we look for disk presence only.
            return True
    except Exception as e:
        print(Fore.RED + f"Download failed: {e}" + Style.RESET_ALL)
        return False

# Improved UI with clear sections and better prompts
def display_banner():
    banner = f"""
{Fore.MAGENTA}{Style.BRIGHT}
  ____   _   _   ____   _   _   ____   _   _   _   _
 |  _ \ | | | | |  _ \ | | | | |  _ \ | | | | | | | |
 | |_) || |_| | | |_) || |_| | | |_) || |_| | | |_| |
 |  __/ |  _  | |  __/ |  _  | |  __/ |  _  | |  _  |
 |_|    |_| |_| |_|    |_| |_| |_|    |_| |_| |_| |_|
{Style.RESET_ALL}"""
    print(banner)
    print(Fore.CYAN + Style.BRIGHT + "Welcome to the Easy YouTube Downloader!" + Style.RESET_ALL)
    print(Fore.YELLOW + "Paste your YouTube video or playlist link below." + Style.RESET_ALL)

def prompt_with_default(prompt, default):
    value = input(f"{Fore.GREEN}{prompt} [{default}]: {Style.RESET_ALL}").strip()
    return value if value else default

# Note: install_dependencies(), display_banner(), and download_path selection
# are done in the __main__ flow to avoid prompting when using --help.

print(Fore.YELLOW + "\nFetching video information... Please wait." + Style.RESET_ALL)

# Initialize progress state at the very beginning of the function
def main():
    progress_state = {
        'total_files': 0,
        'finished_files': 0,
        'current_file': '',
        'start_time': time.time(),
        'last_bytes': 0,
        'last_time': time.time(),
        'internet_speed': 0,
    }

    # ydl_opts will be defined after the progress_hook so the hook variable can be used

    # Improved prompts for user input
    url = prompt_with_default("Enter YouTube URL", "")
    if not url:
        print(Fore.RED + "No URL provided. Exiting." + Style.RESET_ALL)
        return

    print(Fore.YELLOW + "\nGetting video info..." + Style.RESET_ALL)
    # Use flat extraction by default to speed up playlist listing. Users can disable with --no-extract-flat.
    ydl_info_opts = {
        'quiet': True,
        'skip_download': True,
        'noplaylist': False,
        'extract_flat': True if not (args and hasattr(args, 'no_extract_flat') and args.no_extract_flat) else False,
        'no_warnings': True,
        'logger': None,
    }
    # Extract info with timeout and spinner to avoid hanging indefinitely
    def extract_info_with_timeout(url, opts, timeout=60):
        result = {'info': None}
        exc = {'error': None}

        def worker():
            try:
                with YoutubeDL(opts) as ydl:
                    result['info'] = ydl.extract_info(url, download=False)
            except Exception as e:
                exc['error'] = e

        t = threading.Thread(target=worker, daemon=True)
        t.start()

        # Spinner while waiting
        spinner = itertools.cycle(['|', '/', '-', '\\'])
        waited = 0
        interval = 0.5
        while t.is_alive() and waited < timeout:
            sys.stdout.write(Fore.GREEN + f"\rFetching info {next(spinner)} (waited {waited}s)" + Style.RESET_ALL)
            sys.stdout.flush()
            time.sleep(interval)
            waited += interval
        sys.stdout.write('\r' + ' ' * 80 + '\r')
        if t.is_alive():
            return None, 'timeout'
        if exc['error']:
            return None, exc['error']
        return result['info'], None

    timeout_seconds = 60
    if args and hasattr(args, 'info_timeout') and args.info_timeout:
        try:
            timeout_seconds = int(args.info_timeout)
        except Exception:
            timeout_seconds = timeout_seconds

    info, err = extract_info_with_timeout(url, ydl_info_opts, timeout=timeout_seconds)
    if info is None:
        if err == 'timeout':
            retry = prompt_with_default(f"Fetching info is taking longer than {timeout_seconds}s. Continue waiting? (Y/N)", "Y").strip().lower()
            if retry in ('y', 'yes'):
                info, err = extract_info_with_timeout(url, ydl_info_opts, timeout=timeout_seconds * 2)
            if info is None:
                print(Fore.RED + "Failed to fetch video info in time. Try again later or check your network/link." + Style.RESET_ALL)
                return
        else:
            print(Fore.RED + f"Error: Could not fetch video info. Check your link and try again.\nDetails: {err}" + Style.RESET_ALL)
            return

    title = info.get('title', 'Unknown Title')
    print(Fore.CYAN + f"\nTitle: {title}")
    if 'duration' in info and info['duration']:
        mins = int(info['duration']) // 60
        secs = int(info['duration']) % 60
        print(Fore.CYAN + f"Duration: {mins}m {secs}s")

    is_playlist = info.get('_type') == 'playlist' or 'entries' in info
    if is_playlist:
        playlist_type = info.get('playlist_type', 'Unknown')
        print(Fore.MAGENTA + f"\nPlaylist detected: {playlist_type}. All videos will be downloaded in best available quality.")
        progress_state['total_files'] = len(info.get('entries', []))
    else:
        progress_state['total_files'] = 1

    # Ask the user if they want to force re-downloads
    if args and hasattr(args, 'force') and args.force:
        force_flag = True
    else:
        force_input = prompt_with_default("Force re-download of existing files? (y/N)", "N")
        force_flag = force_input.strip().lower() in ("y", "yes")

    # Ask what to download: audio-only or video+audio
    dl_type = None
    if args and hasattr(args, 'audio') and args.audio:
        dl_type = 'audio'
    elif args and hasattr(args, 'video') and args.video:
        dl_type = 'video'
    else:
        dl_choice = prompt_with_default("Download type: (A)udio only, (V)ideo + audio [V]", "V").strip().lower()
        if dl_choice.startswith('a'):
            dl_type = 'audio'
        else:
            dl_type = 'video'

    # Quality choices for video
    quality_choice = None
    qmap = {
        'best': 'best',
        '1080': 'bestvideo[height<=1080]+bestaudio/best',
        '720': 'bestvideo[height<=720]+bestaudio/best',
        '480': 'bestvideo[height<=480]+bestaudio/best',
        '360': 'bestvideo[height<=360]+bestaudio/best',
        'low': 'worst'
    }
    if args and hasattr(args, 'quality') and args.quality:
        quality_choice = args.quality
    else:
        if dl_type == 'video':
            q_prompt = "Preferred quality: (best/1080/720/480/360/low) [best]"
            quality_choice = prompt_with_default(q_prompt, "best").strip().lower()
            if quality_choice not in qmap:
                quality_choice = 'best'

    # If audio-only, allow optional MP3 conversion
    convert_mp3 = False
    if dl_type == 'audio':
        if args and hasattr(args, 'convert_mp3') and args.convert_mp3:
            convert_mp3 = True
        else:
            convert_input = prompt_with_default("Convert audio to mp3? (y/N)", "N").strip().lower()
            convert_mp3 = convert_input in ("y", "yes")
    # Subtitles options (available for both audio and video downloads)
    include_subtitles = False
    auto_subtitles = False
    sub_lang = None
    embed_subtitles = False
    if args and hasattr(args, 'subtitles') and args.subtitles:
        include_subtitles = True
    if args and hasattr(args, 'autosub') and args.autosub:
        auto_subtitles = True
    if args and hasattr(args, 'sub_lang') and args.sub_lang:
        sub_lang = args.sub_lang
    if args and hasattr(args, 'embed_subtitles') and args.embed_subtitles:
        embed_subtitles = True
    # If not provided via CLI, prompt interactively
    if not include_subtitles and not auto_subtitles:
        sub_choice = prompt_with_default("Download subtitles? (Y/N) [N]", "N").strip().lower()
        if sub_choice.startswith('y'):
            include_subtitles = True
            auto_choice = prompt_with_default("Use automatic subtitles (generated) if official ones not available? (Y/N) [Y]", "Y").strip().lower()
            auto_subtitles = auto_choice in ("y", "yes")
            sub_lang = prompt_with_default("Subtitle language (comma-separated, e.g., en,es) [en]", "en")
    # If embedding was chosen but download type is audio-only, warn and disable embedding
    if embed_subtitles and dl_type == 'audio':
        print(Fore.YELLOW + "Embedding subtitles requires video output. Subtitles will be downloaded as separate files." + Style.RESET_ALL)
        embed_subtitles = False
    # If embed_subtitles not set via CLI, prompt interactively when relevant
    if include_subtitles and dl_type == 'video' and not embed_subtitles and not (args and getattr(args, 'embed_subtitles', False)):
        emb_choice = prompt_with_default("Embed subtitles in the video file? (Y/N) [N]", "N").strip().lower()
        embed_subtitles = emb_choice.startswith('y')

    # Normalize sub_lang to a list
    sub_langs = None
    if sub_lang:
        sub_langs = [s.strip() for s in sub_lang.split(',') if s.strip()]

    # Lock to protect progress_state when running concurrent downloads
    progress_lock = threading.Lock()

    def progress_hook(d):
        if d['status'] == 'downloading':
            downloaded = d.get('downloaded_bytes', 0)
            total = d.get('total_bytes', d.get('total_bytes_estimate', 0))
            percent = (downloaded / total * 100) if total else 0
            speed = d.get('speed', 0) / 1024 if d.get('speed', 0) else 0
            eta = d.get('eta', 'N/A')
            downloaded_mb = downloaded / (1024 * 1024)
            total_mb = total / (1024 * 1024) if total else 0
            now = time.time()
            # Calculate internet speed (MB/s)
            with progress_lock:
                bytes_diff = downloaded - progress_state['last_bytes']
                time_diff = now - progress_state['last_time']
                if time_diff > 0:
                    progress_state['internet_speed'] = bytes_diff / time_diff / (1024 * 1024)
                progress_state['last_bytes'] = downloaded
                progress_state['last_time'] = now
            bar_length = 40
            filled_length = int(bar_length * percent // 100)
            bar = '█' * filled_length + '-' * (bar_length - filled_length)
            files_left = progress_state['total_files'] - progress_state['finished_files']
            elapsed = now - progress_state['start_time']
            stats = f"Speed: {speed:.2f}KB/s | Net: {progress_state['internet_speed']:.2f}MB/s | ETA: {eta}s | Elapsed: {elapsed:.1f}s | Left: {files_left} | Downloaded: {progress_state['finished_files']}/{progress_state['total_files']}"
            if progress_state['total_files'] > 1:
                current_title = progress_state.get('current_file','')
                sys.stdout.write(Fore.GREEN + f"\r[{bar}] {percent:6.2f}% | {downloaded_mb:6.2f}MB / {total_mb:6.2f}MB | File {progress_state['finished_files']+1}/{progress_state['total_files']} ({current_title}) | {stats}" + Style.RESET_ALL)
            else:
                sys.stdout.write(Fore.GREEN + f"\r[{bar}] {percent:6.2f}% | {downloaded_mb:6.2f}MB / {total_mb:6.2f}MB | {stats}" + Style.RESET_ALL)
            sys.stdout.flush()
        elif d['status'] == 'finished':
            with progress_lock:
                progress_state['finished_files'] += 1
            print(Fore.CYAN + f"\nDownload finished: {d.get('filename', '')}" + Style.RESET_ALL)
            if os.path.exists(d.get('filename', '')):
                size = os.path.getsize(d.get('filename', '')) / (1024 * 1024)
                print(Fore.YELLOW + f"Saved: {d.get('filename', '')} ({size:.2f} MB)" + Style.RESET_ALL)

    # Adjust playlist handling to ensure all videos are checked
    # Ensure ydl options have access to the progress hook (defined above)
    ydl_opts = {
        'outtmpl': os.path.join(download_path, '%(title)s.%(ext)s'),
        'format': 'best',
        'progress_hooks': [progress_hook],
        'noplaylist': False,
        'quiet': True,
        'no_warnings': True,
        'logger': None,
        'writesubtitles': False,
        'writeautomaticsub': False,
        'writethumbnail': False,
        'postprocessors': [],
    }

    # Apply the user's choices to ydl options
    if dl_type == 'audio':
        ydl_opts['format'] = 'bestaudio/best'
        if convert_mp3:
            # Ensure ffmpeg exists
            if shutil.which('ffmpeg'):
                ydl_opts['postprocessors'] = [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }]
            else:
                print(Fore.YELLOW + "FFmpeg not found — audio will not be converted to MP3; original format will be saved." + Style.RESET_ALL)
    else:
        # Video + audio
        if quality_choice in qmap:
            ydl_opts['format'] = qmap[quality_choice]
        else:
            ydl_opts['format'] = qmap['best']
        # Subtitles handling
        if include_subtitles:
            ydl_opts['writesubtitles'] = True
            if sub_langs:
                ydl_opts['subtitleslangs'] = sub_langs
            if auto_subtitles:
                ydl_opts['writeautomaticsub'] = True
        if embed_subtitles:
            if shutil.which('ffmpeg'):
                ydl_opts['embedsubtitles'] = True
                ydl_opts['subtitlesformat'] = 'srt'
            else:
                print(Fore.YELLOW + "FFmpeg not found — cannot embed subtitles; subtitles will be downloaded as separate files." + Style.RESET_ALL)
    if is_playlist:
        entries = [e for e in info.get('entries', []) if e]
        # Build a list of (idx, entry, url)
        prepared_entries = []
        for idx, entry in enumerate(entries, start=1):
            entry_url = entry.get('webpage_url') or entry.get('url') or (f"https://www.youtube.com/watch?v={entry.get('id')}" if entry.get('id') else None)
            if entry.get('id') and not entry.get('webpage_url') and not entry.get('url'):
                print(Fore.YELLOW + f"Using constructed URL for entry id {entry.get('id')}: {entry_url}" + Style.RESET_ALL)
            if not entry_url:
                print(Fore.RED + f"\nSkipping video {idx}: URL not found." + Style.RESET_ALL)
                with progress_lock:
                    progress_state['finished_files'] += 1
                continue
            prepared_entries.append((idx, entry, entry_url))

        # Determine concurrency
        concurrency = 1
        try:
            if args and hasattr(args, 'concurrency') and args.concurrency:
                concurrency = max(1, int(args.concurrency))
        except Exception:
            concurrency = 1

        def download_worker(item):
            idx, entry, entry_url = item
            title = entry.get('title', f'Video {idx}')
            print(Fore.CYAN + f"\nProcessing video {idx}/{len(prepared_entries)}: {title}" + Style.RESET_ALL)
            # Ensure we have full info for prepare_filename; flat entries may lack metadata
            full_info = entry
            try:
                # If the entry seems "flat" (missing title or id), try to fetch full info for that entry
                if not full_info.get('title') or not full_info.get('id') or full_info.get('_type') == 'url':
                    with YoutubeDL({'quiet': True, 'no_warnings': True}) as ydl_inner:
                        full_info = ydl_inner.extract_info(entry_url, download=False)
            except Exception as e:
                print(Fore.RED + f"Failed to fetch info for entry {idx}: {e}" + Style.RESET_ALL)
                with progress_lock:
                    progress_state['finished_files'] += 1
                return False

            entry_opts = ydl_opts.copy()
            entry_opts['outtmpl'] = os.path.join(download_path, f"%(title)s_{idx}.%(ext)s")
            entry_opts['noplaylist'] = True

            with progress_lock:
                progress_state['current_file'] = full_info.get('title', '')

            ok = download_video(entry_opts, entry_url, full_info, force=force_flag, preserve_index=True)
            if not ok:
                print(Fore.YELLOW + f"\nSkipping video {idx}: Already downloaded or failed." + Style.RESET_ALL)
            with progress_lock:
                # If download_video did not trigger a finished hook (skip), ensure progress is advanced
                # progress_hook will increment finished_files on successful 'finished' events; for skipped/failed, count here
                # We guard against double-counting by ensuring finished_files does not exceed total
                if progress_state['finished_files'] < progress_state['total_files']:
                    # If the download was skipped (ok == False) the finished counter likely was not incremented
                    if not ok:
                        progress_state['finished_files'] += 1
                files_done = progress_state['finished_files']
                total = progress_state['total_files']
                left = total - files_done
            print(Fore.GREEN + f"Progress: {files_done}/{total} downloaded. {left} remaining." + Style.RESET_ALL)
            return ok

        if concurrency > 1:
            with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as exe:
                # Submit all tasks and wait
                futures = {exe.submit(download_worker, item): item for item in prepared_entries}
                for fut in concurrent.futures.as_completed(futures):
                    # We simply ensure exceptions are observed
                    try:
                        fut.result()
                    except Exception as e:
                        item = futures.get(fut)
                        print(Fore.RED + f"Error downloading {item}: {e}" + Style.RESET_ALL)
        else:
            # Sequential fallback
            for item in prepared_entries:
                download_worker(item)
    else:
        # Single video download
        if not download_video(ydl_opts, url, info, force=force_flag):
            print(Fore.YELLOW + "\nSkipping video: Already downloaded or failed." + Style.RESET_ALL)
            progress_state['finished_files'] += 1
        else:
            files_done = progress_state['finished_files']
            total = progress_state['total_files']
            left = total - files_done
            print(Fore.GREEN + f"Progress: {files_done}/{total} downloaded. {left} remaining." + Style.RESET_ALL)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Easy YouTube Downloader (simple filesystem duplicate check)')
    # Removed DB maintenance CLI flags; the script now checks for file existence only.
    parser.add_argument('--audio', action='store_true', help='Download audio only (non-interactive)')
    parser.add_argument('--video', action='store_true', help='Download video + audio (non-interactive)')
    parser.add_argument('--quality', type=str, choices=['best', '1080', '720', '480', '360', 'low'], help='Desired video quality when downloading video (non-interactive)')
    parser.add_argument('--convert-mp3', action='store_true', help='When audio-only: convert to mp3 (requires ffmpeg)')
    parser.add_argument('--force', action='store_true', help='Force re-download of files that already exist')
    parser.add_argument('--subtitles', action='store_true', help='Download subtitles if available')
    parser.add_argument('--autosub', action='store_true', help='Download auto-generated subtitles (if available)')
    parser.add_argument('--sub-lang', type=str, default=None, help='Comma-separated list of subtitle languages (e.g., en,es)')
    parser.add_argument('--embed-subtitles', action='store_true', help='Embed subtitles into the video file (requires ffmpeg)')
    parser.add_argument('--dir', type=str, default=None, help='Specify download directory to operate on (overrides interactive prompt)')
    parser.add_argument('--info-timeout', type=int, default=60, help='Timeout in seconds for fetching video info (default 60)')
    parser.add_argument('--extract-flat', dest='extract_flat', action='store_true', help='(deprecated) kept for compatibility')
    parser.add_argument('--no-extract-flat', dest='no_extract_flat', action='store_true', help='Disable fast flat extraction for playlist listing')
    parser.add_argument('--concurrency', type=int, default=1, help='Number of concurrent downloads for playlists (default 1)')
    args = parser.parse_args()
    # Install dependencies and show banner
    install_dependencies()
    display_banner()

    if args.dir:
        download_path = args.dir
    else:
        download_path = get_download_path()
    try:
        os.makedirs(download_path, exist_ok=True)
        main()
    except (KeyboardInterrupt, EOFError):
        print(Fore.RED + "\nExited by user. Goodbye!" + Style.RESET_ALL)