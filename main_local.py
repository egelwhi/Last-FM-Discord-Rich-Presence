from pypresence import Presence # type: ignore
from pypresence.types import ActivityType
import time
import requests
from xml.etree import ElementTree as ET

client_id = "1454009737778561067"
lastfm_key = "401228c37da23c23dcae477deee917e9" 
lastfm_name = "egelwhi"
lastfm_url = "https://ws.audioscrobbler.com/2.0/?method=user.getrecenttracks&user={}&api_key={}&limit=1"
check_interval = 10

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
    response = requests.get(lastfm_url.format(lastfm_name, lastfm_key))
    return response.text

def parse_data(u):
    file = ET.fromstring(get_user_state())
    root = file.find('recenttracks/track')
    t_name = root.find('name').text
    pic = root.findall('image')[-1].text

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
        'artist': root.find('artist').text,
        'album': root.find('album').text,
        'l_image': pic,
        's_url': root.find('url').text,
        'u_start': u.time
    }

def print_song_info(u, song):
    print("------------------------------")
    if song['now_playing']:
        print(f"{u.counter}. Now Playing: {song['artist']} - {song['title']} ... Duration: {int(time.time() - song['u_start'])} seconds \n Album: {song['album']} \n URL: {song['s_url']} \n Image: {song['l_image']}")
    else:
        print(f"Last Played: {song['artist']} - {song['title']}")
    print("------------------------------")

def update_discord_presence(u, RPC):
    song = parse_data(u)
    print_song_info(u, song)

    if song['now_playing'] == True:
        RPC.update(
            activity_type=ActivityType.LISTENING,
            name = f"{song['artist']} - {song['title']}",
            details=f"Listening to {song['title']}",
            state=f"by {song['artist']}",
            large_image=song['l_image'],
            large_text=song['title'],
            start=int(song['u_start']),
            buttons=[{"label": "Check it out on Last.fm", "url": song['s_url']}]
        )

        u.increment_counter()
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

    

def main():
    RPC = Presence(client_id)
    RPC.connect()
    print("Successfully connected to Discord.")
    u = update()

    while True:
        try:
            update_discord_presence(u, RPC)
            time.sleep(check_interval)
        except Exception as e:
            print(f"Script crashed: {e}")
            print("Restarting in 5 seconds...")
            time.sleep(5)

main()