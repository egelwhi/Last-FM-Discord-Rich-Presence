import json
from pypresence import Presence
from pypresence.types import ActivityType
import time
import requests
from xml.etree import ElementTree as ET
from pathlib import Path
import sys
import os

# Ensure UTF-8 output on Windows consoles to avoid 'gbk' encode errors
# Guard against `sys.stdout`/`sys.stderr` being None (windowed exe with no console)
try:
    if getattr(sys.stdout, 'reconfigure', None):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if getattr(sys.stderr, 'reconfigure', None):
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    import io
    try:
        # If stdout/stderr is None (pyinstaller --windowed), attach a memory buffer
        if sys.stdout is None:
            sys.stdout = io.TextIOWrapper(io.BytesIO(), encoding='utf-8', errors='replace', line_buffering=True)
        elif hasattr(sys.stdout, 'buffer'):
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)

        if sys.stderr is None:
            sys.stderr = io.TextIOWrapper(io.BytesIO(), encoding='utf-8', errors='replace', line_buffering=True)
        elif hasattr(sys.stderr, 'buffer'):
            sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace', line_buffering=True)
    except Exception:
        # Best-effort only; if this fails, continue without replacing streams
        pass

client_id = "" 
lastfm_key = ""
lastfm_name = ""
lastfm_url = "https://ws.audioscrobbler.com/2.0/?method={}"
user_track_method = "user.getrecenttracks"
track_info_method = "track.getInfo"
file_path = Path("./config.json")
check_interval = 10
pp_strategy = 1  # 0 for traditional, 1 for dynamic
kill_switch = False

class update:
    name = ""
    time = 0
    counter = 0

    def __init__(self):
        pass

    def get_name(self):
        return self.name
    
    def get_time(self):
        return self.time

    def change_name(self, n):
        self.name = n

    def change_time(self, t):
        self.time = t
    
    def increment_counter(self):
        self.counter += 1

    def clear_counter(self):
        self.counter = 0

def get_user_state():
    response = requests.get(lastfm_url.format(user_track_method) + f"&user={lastfm_name}&api_key={lastfm_key}&limit=1")
    return response.text

def get_track_info(artist, track):
    response = requests.get(lastfm_url.format(track_info_method) + f"&api_key={lastfm_key}&artist={artist}&track={track}")
    return response.text

def parse_data(u):
    default_pic = "https://images.gameinfo.io/pokemon/256/p79f447.png"

    # get user recent track data and handle parse errors
    try:
        file = ET.fromstring(get_user_state())
    except Exception:
        return {
            'now_playing': False,
            'title': '',
            'artist': '',
            'album': '',
            'l_image': default_pic,
            's_url': '',
            'u_start': u.time,
            'duration': 0
        }

    root = file.find('recenttracks/track')
    if root is None:
        return {
            'now_playing': False,
            'title': '',
            'artist': '',
            'album': '',
            'l_image': default_pic,
            's_url': '',
            'u_start': u.time,
            'duration': 0
        }

    def safe_text(elem, tag, default=""):
        if elem is None:
            return default
        child = elem.find(tag)
        if child is None or child.text is None:
            return default
        return child.text

    t_name = safe_text(root, 'name', '')
    t_artist = safe_text(root, 'artist', '')

    images = root.findall('image') or []
    pic = default_pic
    if images:
        last_img = images[-1]
        if last_img is not None and last_img.text:
            pic = last_img.text

    # get track info data of the current track (may fail)
    duration = 0
    try:
        track_info_xml = ET.fromstring(get_track_info(t_artist, t_name))
        t_root = track_info_xml.find('track')
        if t_root is not None:
            dur_text = safe_text(t_root, 'duration', None)
            if dur_text:
                try:
                    duration = int(dur_text)
                except ValueError:
                    duration = 0
    except Exception:
        duration = 0

    # check if now playing
    playing = False
    try:
        if root is not None and len(root.keys()) > 0:
            playing = True
    except Exception:
        playing = False

    # check if track has changed, if yes reset time
    update_check = u.name
    if update_check == "" or update_check != t_name:
        u.change_name(t_name)
        u.change_time(time.time())

    # set default image if placeholder or missing
    if pic is None or pic == "https://lastfm.freetls.fastly.net/i/u/300x300/2a96cbd8b46e442fc41c2b86b821562f.png":
        pic = default_pic

    # return data as dictionary (use safe_text for optional fields)
    return {
        'now_playing': playing,
        'title': t_name,
        'artist': t_artist,
        'album': safe_text(root, 'album', 'N/A'),
        'l_image': pic,
        's_url': safe_text(root, 'url', ''),
        'u_start': u.time,
        'duration': duration
    }

#print song info to console
def print_song_info(u, song):
    if song['now_playing']:
        print(f"{u.counter}. Now Playing: {song['artist']} - {song['title']} ... Duration: {int(time.time() - song['u_start'])} seconds \n Album: {song['album']} \n URL: {song['s_url']} \n Image: {song['l_image']}")
    else:
        print(f"Last Played: {song['artist']} - {song['title']}  \n Album: {song['album']} \n URL: {song['s_url']} \n Image: {song['l_image']}")

#update Discord presence
def update_discord_presence(u, RPC, song):
    print_song_info(u, song)

    if song['now_playing'] == True:
        RPC.update(
            activity_type=ActivityType.LISTENING,
            name = f"{song['artist']} - {song['title']}",
            details=f"Listening to {song['title']}",
            state=f"by {song['artist']}",
            large_image=song['l_image'],
            large_text=song['album'],
            start=int(song['u_start']),
            buttons=[{"label": "Check it out on Last.fm", "url": song['s_url']}]
        )
    else:
        RPC.update(
            activity_type=ActivityType.LISTENING,
            name = "Not listening to anything",
            details="Last listened to:",
            state=f"{song['artist']} - {song['title']}",
            large_image=song['l_image'],
            large_text=song['title'],
            buttons=[{"label": "Check it out on Last.fm", "url": song['s_url']}]
        )
        u.clear_counter()

#kill the Discord presence
def kill(RPC):
    try:
        RPC.clear()
        RPC.close()
        print("Discord Rich Presence stopped.\n")
        sys.exit()
    except Exception as e:
        print(f"Error closing RPC: {e}")
        sys.exit()

#stall for given seconds with kill switch check
def stall(seconds, RPC):
    c = 0
    if check_interval >= 1:
        while c < seconds:
            if(kill_switch):
                kill(RPC)
            time.sleep(0.5)
            c += 0.5
    else:
        if(kill_switch):
            kill(RPC)
        time.sleep(seconds)

#push-pull strategy handler
def push_pull_strategy(u, RPC):
    song = parse_data(u)
    u.increment_counter()
    if(pp_strategy == 1):
        #dynamic strategy
        #not fully implemented yet, for now just behaves like traditional
        update_discord_presence(u, RPC, song)
        stall(check_interval, RPC)
    else: 
        #traditional strategy, check every interval if song has changed
        update_discord_presence(u, RPC, song)
        stall(check_interval, RPC)

#start the main process
def start_process():
    try:
        RPC = Presence(client_id)
        RPC.connect()
    except Exception as e:
        print(e)
        print("Failed to connect to Discord. Please check your Client ID and ensure Discord is running.")
        os.remove(file_path)
        print("Configuration file deleted. Please restart the script to re-enter your details.")
        os._exit(0)
    
    print("Successfully connected to Discord.")
    if pp_strategy == 0:
        print("Using traditional Strategy")
    else:
        print("Using dynamic Strategy")
    u = update()

    while not kill_switch:
        try:
            push_pull_strategy(u, RPC)
        except Exception as e:
            print(f"Script crashed: {e}")
            print("Restarting in 2 seconds...")
            time.sleep(2)
    
    kill(RPC)

#set user data and save to config file, and start the process
def set_user_data():
    global client_id, lastfm_key, lastfm_name, check_interval, pp_strategy
    if (file_path.exists()):
        with open(file_path, "r", encoding="utf-8") as file:
            data = json.load(file)
            if ("client_id" in data and "lastfm_key" in data and "lastfm_name" in data and "check_interval" in data and "pp_strategy" in data):
                client_id = data.get("client_id")
                lastfm_key = data.get("lastfm_key")
                lastfm_name = data.get("lastfm_name")
                check_interval = data.get("check_interval")
                pp_strategy = data.get("pp_strategy")
    else:
        client_id = input("Enter your Discord Client ID: ")
        lastfm_key = input("Enter your Last.fm API Key: ")
        lastfm_name = input("Enter your Last.fm Username: ")
        check_interval = int(input("Enter the check interval in seconds: "))
        pp_strategy = int(input("Enter the push-pull strategy (0 or 1): "))
        with open(file_path, "w", encoding="utf-8") as file:
            json.dump({
                "client_id": client_id,
                "lastfm_key": lastfm_key,
                "lastfm_name": lastfm_name,
                "check_interval": check_interval,
                "pp_strategy": pp_strategy
            }, file, indent=4)

    start_process()

if __name__ == "__main__":
    set_user_data()