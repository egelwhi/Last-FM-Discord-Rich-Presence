## Last.fm -> Discord RPC
This is a simple application that gets your scrobble from Last.FM API, process it, and show it on your Discord Rich Presence. I built this for learning and for my own needs. This is a pure Python project.
##Lib
main:
- pypresence
- requests
GUI:
- Pillow
- pystray
##Features
What this application provides
* A simple GUI for user to start the service or stop the service, also monitor the current status
* The main service can run by itself, GUI is not a must
* Run at background (tray)
