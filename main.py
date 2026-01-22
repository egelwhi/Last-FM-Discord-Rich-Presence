import json
from pypresence import Presence
from pypresence.types import ActivityType
import time
import requests
from xml.etree import ElementTree as ET
from pathlib import Path

client_id = "" 
lastfm_key = ""
lastfm_name = ""
lastfm_url = "https://ws.audioscrobbler.com/2.0/?method={}"
user_track_method = "user.getrecenttracks"
track_info_method = "track.getInfo"
file_path = Path("./config.json")
check_interval = 10
pp_strategy = 1  # 0 for traditional, 1 for dynamic

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
    file = ET.fromstring(get_user_state())
    root = file.find('recenttracks/track')
    t_name = root.find('name').text
    t_artist = root.find('artist').text
    pic = root.findall('image')[-1].text

    track_info_xml = ET.fromstring(get_track_info(t_artist, t_name))
    t_root = track_info_xml.find('track')
    duration = int(t_root.find('duration').text)

    if(duration is None):
        duration = 0

    playing = False
    if (len(root.keys()) > 0):
        playing = True

    update_check = u.name
    if(update_check == "" or update_check != t_name):
        u.change_name(t_name)
        u.change_time(time.time())

    if(pic is None or pic == "https://lastfm.freetls.fastly.net/i/u/300x300/2a96cbd8b46e442fc41c2b86b821562f.png"):
        pic = "https://images.gameinfo.io/pokemon/256/p79f447.png"

    return {
        'now_playing': playing,
        'title': t_name,
        'artist': t_artist,
        'album': root.find('album').text,
        'l_image': pic,
        's_url': root.find('url').text,
        'u_start': u.time,
        'duration': duration
    }

def print_song_info(u, song):
    print("------------------------------")
    if song['now_playing']:
        print(f"{u.counter}. Now Playing: {song['artist']} - {song['title']} ... Duration: {int(time.time() - song['u_start'])} seconds \n Album: {song['album']} \n URL: {song['s_url']} \n Image: {song['l_image']}")
    else:
        print(f"Last Played: {song['artist']} - {song['title']}")
    print("------------------------------")

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

def push_pull_strategy(u, RPC):
    song = parse_data(u)
    u.increment_counter()
    if(pp_strategy == 1):
        update_discord_presence(u, RPC, song)
        time.sleep(check_interval)
    else: #not finished yet
        update_discord_presence(u, RPC, song)
        time.sleep(check_interval)


def start_process():
    RPC = Presence(client_id)
    RPC.connect()
    print("Successfully connected to Discord.")
    if pp_strategy == 0:
        print("Using traditional Strategy")
    else:
        print("Using dynamic Strategy")
    u = update()

    while True:
        try:
            push_pull_strategy(u, RPC)
        except Exception as e:
            print(f"Script crashed: {e}")
            print("Restarting in 5 seconds...")
            time.sleep(5)

def set_user_data(client_id_local, lastfm_key_local, lastfm_name_local, check_interval_local, pp_strategy_local):
    global client_id, lastfm_key, lastfm_name, check_interval, pp_strategy
    if (file_path.exists()):
        with open(file_path, "r") as file:
            data = json.load(file)
            client_id = data.get("client_id")
            lastfm_key = data.get("lastfm_key")
            lastfm_name = data.get("lastfm_name")
            check_interval = data.get("check_interval")
            pp_strategy = data.get("pp_strategy")
    else:
        client_id = client_id_local
        lastfm_key = lastfm_key_local
        lastfm_name = lastfm_name_local
        check_interval = check_interval_local
        pp_strategy = pp_strategy_local
        with open(file_path, "w") as file:
            json.dump({
                "client_id": client_id_local,
                "lastfm_key": lastfm_key_local,
                "lastfm_name": lastfm_name_local,
                "check_interval": check_interval_local,
                "pp_strategy": pp_strategy_local
            }, file, indent=4)

    start_process()

if __name__ == "__main__":
    #for direct run
    if (file_path.exists()):
        with open(file_path, "r") as file:
            data = json.load(file)
            set_user_data(data.get("client_id", client_id), data.get("lastfm_key", lastfm_key), data.get("lastfm_name", lastfm_name), data.get("check_interval", check_interval), data.get("pp_strategy", pp_strategy))
    set_user_data(input("Enter your Discord Client ID: "), input("Enter your Last.fm API Key: "), input("Enter your Last.fm Username: "), int(input("Enter the check interval in seconds: ")), int(input("Enter the push-pull strategy (0 or 1): ")))