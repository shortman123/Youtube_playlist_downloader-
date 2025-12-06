import os
import sys
import subprocess
import time
from yt_dlp import YoutubeDL
from colorama import init, Fore, Style
import psutil
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

# Call the dependency installer at the start of the script
install_dependencies()

# Call the banner at the start of the script
display_banner()

# Use the adjusted download path function
download_path = get_download_path()
os.makedirs(download_path, exist_ok=True)

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

    # Ensure ydl_opts is defined at the top of the main function
    ydl_opts = {
        'outtmpl': os.path.join(download_path, '%(title)s.%(ext)s'),
        'format': 'best',
        'progress_hooks': [progress_hook],
        'noplaylist': False,
        'extractor_args': {'youtube': {'player_client': 'default'}},
        'quiet': True,
        'no_warnings': True,
        'logger': None,
        'writesubtitles': False,
        'writeautomaticsub': False,
        'writethumbnail': False,
        'postprocessors': [],
    }

    # Improved prompts for user input
    url = prompt_with_default("Enter YouTube URL", "")
    if not url:
        print(Fore.RED + "No URL provided. Exiting." + Style.RESET_ALL)
        return

    print(Fore.YELLOW + "\nGetting video info..." + Style.RESET_ALL)
    ydl_info_opts = {
        'extractor_args': {'youtube': {'player_client': 'default'}},
        'quiet': True,
        'skip_download': True,
        'noplaylist': True,
        'no_warnings': True,
        'logger': None,
    }
    try:
        with YoutubeDL(ydl_info_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        print(Fore.RED + f"Error: Could not fetch video info. Check your link and try again.\nDetails: {e}" + Style.RESET_ALL)
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
                sys.stdout.write(Fore.GREEN + f"\r[{bar}] {percent:6.2f}% | {downloaded_mb:6.2f}MB / {total_mb:6.2f}MB | File {progress_state['finished_files']+1}/{progress_state['total_files']} ({d.get('filename','')}) | {stats}" + Style.RESET_ALL)
            else:
                sys.stdout.write(Fore.GREEN + f"\r[{bar}] {percent:6.2f}% | {downloaded_mb:6.2f}MB / {total_mb:6.2f}MB | {stats}" + Style.RESET_ALL)
            sys.stdout.flush()
        elif d['status'] == 'finished':
            progress_state['finished_files'] += 1
            print(Fore.CYAN + f"\nDownload finished: {d.get('filename', '')}" + Style.RESET_ALL)
            if os.path.exists(d.get('filename', '')):
                size = os.path.getsize(d.get('filename', '')) / (1024 * 1024)
                print(Fore.YELLOW + f"Saved: {d.get('filename', '')} ({size:.2f} MB)" + Style.RESET_ALL)

    # Adjust playlist handling to ensure all videos are checked
    if is_playlist:
        entries = info.get('entries', [])
        for idx, entry in enumerate(entries, start=1):
            print(Fore.CYAN + f"\nProcessing video {idx}/{len(entries)}: {entry.get('title', 'Unknown Title')}" + Style.RESET_ALL)
            entry_url = entry.get('url')
            if not entry_url:
                print(Fore.RED + f"\nSkipping video {idx}: URL not found." + Style.RESET_ALL)
                continue

            # Update ydl_opts for each entry
            entry_opts = ydl_opts.copy()
            entry_opts['outtmpl'] = os.path.join(download_path, f"%(title)s_{idx}.%(ext)s")

            if not download_video(entry_opts, entry_url, entry):
                print(Fore.YELLOW + f"\nSkipping video {idx}: Already downloaded or failed." + Style.RESET_ALL)
                continue  # Skip to the next video if this one is already downloaded or fails
    else:
        # Single video download
        if not download_video(ydl_opts, url, info):
            print(Fore.YELLOW + "\nSkipping video: Already downloaded or failed." + Style.RESET_ALL)

if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print(Fore.RED + "\nExited by user. Goodbye!" + Style.RESET_ALL)