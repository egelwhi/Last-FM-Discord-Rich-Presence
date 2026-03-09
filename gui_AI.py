import tkinter as tk
from tkinter import ttk, messagebox
import json
from pathlib import Path
import sys
import subprocess
import main
import shutil
import pystray
from PIL import Image, ImageDraw, ImageTk
import requests
from io import BytesIO
import webbrowser
import threading

class LastFMGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Last.fm Discord Rich Presence")
        self.root.geometry("600x800")
        self.root.resizable(False, False)
        
        self.config_path = Path("./config.json")
        self.is_running = False
        self.rpc_thread = None

        self.stdout_thread = None
        self.stderr_thread = None


        self.tray_icon = None
        self.tray_thread = None
        self.is_tray = False
        # Current song info (populated from main.py stdout)
        self.current_state = None
        self.current_title = None
        self.current_artist = None
        self.current_album = None
        self.current_lastfm_url = None
        self.current_image_url = None
        # UI-bound vars for display
        self.display_state_var = tk.StringVar(value="")
        self.display_title_var = tk.StringVar(value="")
        self.display_artist_var = tk.StringVar(value="")
        self.display_album_var = tk.StringVar(value="")
        # Status indicators
        self.service_running_var = tk.StringVar(value="Stopped")
        self.now_playing_var = tk.StringVar(value="No")

        # Load current config first
        self.load_config()
        # Now config is available for minimize_to_tray_var
        self.minimize_to_tray_var = tk.BooleanVar(value=self.config.get("minimize_to_tray", False))
        # Start-on-launch option variable (initialized from config)
        self.start_on_launch_var = tk.BooleanVar(value=self.config.get("start_on_launch", False))

        # Create GUI elements
        self.create_widgets()

        # Bind minimize event
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.root.bind('<Unmap>', self.on_minimize)

        # Auto-start service if configured
        try:
            if self.start_on_launch_var.get():
                if not self.is_running:
                    self.start_service()
        except Exception:
            pass

    def create_tray_icon(self):
        # Create a simple icon (red circle)
        image = Image.new('RGB', (64, 64), (255, 255, 255))
        draw = ImageDraw.Draw(image)
        draw.ellipse((16, 16, 48, 48), fill=(255, 0, 0))
        return image

    def show_tray_icon(self):
        if self.tray_icon is not None:
            return
        image = self.create_tray_icon()
        # menu is built/kept up-to-date by update_tray_menu()
        menu = pystray.Menu()
        self.tray_icon = pystray.Icon("LastFMGUI", image, "Last.fm Discord Rich Presence", menu)
        # populate initial menu (includes a Now Playing row)
        try:
            self.update_tray_menu()
        except Exception:
            pass
        self.tray_thread = threading.Thread(target=self.tray_icon.run, daemon=True)
        self.tray_thread.start()
        self.is_tray = True

    def update_tray_menu(self):
        # Rebuild the tray menu so the first row shows Now Playing / Last Played
        try:
            # Build the display label
            label = "No song"
            if getattr(self, 'current_artist', None) or getattr(self, 'current_title', None):
                parts = []
                if self.current_artist:
                    parts.append(self.current_artist)
                if self.current_title:
                    parts.append(self.current_title)
                label = " - ".join(parts)

            # action to open last.fm url when clicking the song row
            def _open_lastfm(icon, item):
                try:
                    self._open_lastfm_url()
                except Exception:
                    pass

            # Compose menu with Now Playing as the first (possibly-disabled) item
            menu = pystray.Menu(
                pystray.MenuItem(f"Now: {label}", _open_lastfm, enabled=lambda item: bool(getattr(self, 'current_lastfm_url', None))),
                pystray.MenuItem('Restore', self.restore_window, default=True),
                pystray.MenuItem('Start', self.tray_start, enabled=lambda item: not self.is_running),
                pystray.MenuItem('Stop', self.tray_stop, enabled=lambda item: self.is_running),
                pystray.MenuItem('Exit', self.exit_from_tray)
            )

            # Assign menu to the icon; pystray will update the displayed menu
            if self.tray_icon:
                self.tray_icon.menu = menu
                # Also update tooltip/title for quick hover info
                self.tray_icon.title = f"Last.fm: {label}"
        except Exception:
            pass

    def hide_tray_icon(self):
        if self.tray_icon:
            self.tray_icon.stop()
            self.tray_icon = None
            self.is_tray = False

    def on_minimize(self, event):
        # Minimize to tray if enabled
        if self.minimize_to_tray_var.get():
            if self.root.state() == 'iconic' and not self.is_tray:
                self.root.withdraw()
                self.show_tray_icon()

    def restore_window(self, icon=None, item=None):
        self.root.after(0, self._restore_window)

    def _restore_window(self):
        self.root.deiconify()
        self.root.state('normal')
        self.hide_tray_icon()

    def exit_from_tray(self, icon=None, item=None):
        self.root.after(0, self.on_closing)
        
    def tray_start(self):
        if not self.is_running:
            self.start_service()

    def tray_stop(self):
        if self.is_running:
            self.stop_service()

    def load_config(self):
        # Load configuration from file
        if self.config_path.exists():
            with open(self.config_path, "r") as file:
                self.config = json.load(file)
        else:
            self.config = {}
    
    def save_config(self):
        # Save configuration to file"""
        self.config = {
            "client_id": self.client_id_var.get(),
            "lastfm_key": self.lastfm_key_var.get(),
            "lastfm_name": self.lastfm_name_var.get(),
            "check_interval": int(self.check_interval_var.get()),
            "pp_strategy": self.pp_strategy_var.get(),
            "minimize_to_tray": self.minimize_to_tray_var.get(),
            "start_on_launch": self.start_on_launch_var.get()
        }
        with open(self.config_path, "w") as file:
            json.dump(self.config, file, indent=4)
        self.log_message("Configuration saved.")

    def validate_config(self):
        """Enable the Start button only when required config fields are filled and valid.

        Fields required: client_id, lastfm_key, lastfm_name, check_interval (int >=1)
        """
        try:
            # If start_button not created yet, do nothing
            if not hasattr(self, 'start_button'):
                return

            # If service is already running, keep Start disabled
            if getattr(self, 'is_running', False):
                try:
                    self.start_button.config(state='disabled')
                except Exception:
                    pass
                return

            cid = (self.client_id_var.get() or '').strip()
            key = (self.lastfm_key_var.get() or '').strip()
            name = (self.lastfm_name_var.get() or '').strip()
            interval = (self.check_interval_var.get() or '').strip()

            valid = True
            if not cid or not key or not name:
                valid = False
            else:
                try:
                    ival = int(interval)
                    if ival < 1:
                        valid = False
                except Exception:
                    valid = False

            try:
                self.start_button.config(state='normal' if valid else 'disabled')
            except Exception:
                pass
        except Exception:
            pass
    
    def create_widgets(self):
        # Create GUI elements"""

        notebook = ttk.Notebook(self.root)
        notebook.pack(fill="both", expand=True, padx=10, pady=10)

        # --- Main Settings Tab ---
        main_frame = ttk.Frame(notebook)
        notebook.add(main_frame, text="Main")

        # Title
        title = ttk.Label(main_frame, text="Last.fm Discord Rich Presence", font=("Arial", 16, "bold"))
        title.pack(pady=12)

        # Configuration Frame
        config_frame = ttk.LabelFrame(main_frame, text="Configuration", padding=12)
        # Reduce vertical expansion so the config frame doesn't leave large empty space
        config_frame.pack(fill="x", expand=False, padx=12, pady=6)

        # Discord Client ID
        ttk.Label(config_frame, text="Discord Client ID:", font=("Arial", 10)).grid(row=0, column=0, sticky="w", pady=8)
        self.client_id_var = tk.StringVar(value=self.config.get("client_id", ""))
        client_id_entry = ttk.Entry(config_frame, textvariable=self.client_id_var, width=40)
        client_id_entry.grid(row=0, column=1, pady=8)

        # Last.fm API Key
        ttk.Label(config_frame, text="Last.fm API Key:", font=("Arial", 10)).grid(row=1, column=0, sticky="w", pady=8)
        self.lastfm_key_var = tk.StringVar(value=self.config.get("lastfm_key", ""))
        lastfm_key_entry = ttk.Entry(config_frame, textvariable=self.lastfm_key_var, width=40, show="*")
        lastfm_key_entry.grid(row=1, column=1, pady=8)

        # Last.fm Username
        ttk.Label(config_frame, text="Last.fm Username:", font=("Arial", 10)).grid(row=2, column=0, sticky="w", pady=8)
        self.lastfm_name_var = tk.StringVar(value=self.config.get("lastfm_name", ""))
        lastfm_name_entry = ttk.Entry(config_frame, textvariable=self.lastfm_name_var, width=40)
        lastfm_name_entry.grid(row=2, column=1, pady=8)

        # Check Interval
        ttk.Label(config_frame, text="Check Interval (seconds):", font=("Arial", 10)).grid(row=3, column=0, sticky="w", pady=8)
        self.check_interval_var = tk.StringVar(value=str(self.config.get("check_interval", 10)))
        check_interval_spinbox = ttk.Spinbox(config_frame, from_=1, to=60, textvariable=self.check_interval_var, width=10)
        check_interval_spinbox.grid(row=3, column=1, sticky="w", pady=8)

        # Attach validation traces to config fields so Start button updates
        try:
            # traces may fire before start_button exists; validate_config handles that
            self.client_id_var.trace_add('write', lambda *a: self.validate_config())
            self.lastfm_key_var.trace_add('write', lambda *a: self.validate_config())
            self.lastfm_name_var.trace_add('write', lambda *a: self.validate_config())
            self.check_interval_var.trace_add('write', lambda *a: self.validate_config())
        except Exception:
            pass

        # Strategy
        ttk.Label(config_frame, text="Update Strategy:", font=("Arial", 10)).grid(row=4, column=0, sticky="w", pady=8)
        self.pp_strategy_var = tk.IntVar(value=self.config.get("pp_strategy", 1))
        strategy_frame = ttk.Frame(config_frame)
        strategy_frame.grid(row=4, column=1, sticky="w", pady=8)
        ttk.Radiobutton(strategy_frame, text="Traditional", variable=self.pp_strategy_var, value=0).pack(anchor="w")
        ttk.Radiobutton(strategy_frame, text="Dynamic", variable=self.pp_strategy_var, value=1).pack(anchor="w")

        # Control Frame
        control_frame = ttk.Frame(main_frame)
        control_frame.pack(fill="x", padx=20, pady=10)

        # Save Button
        save_button = ttk.Button(control_frame, text="Save Configuration", command=self.save_config)
        save_button.pack(side="left", padx=5)

        # Start Button
        self.start_button = ttk.Button(control_frame, text="Start", command=self.start_service)
        self.start_button.pack(side="left", padx=5)

        # Ensure start button reflects current config validity
        try:
            self.validate_config()
        except Exception:
            pass

        # Stop Button
        self.stop_button = ttk.Button(control_frame, text="Stop", command=self.stop_service, state="disabled")
        self.stop_button.pack(side="left", padx=5)

        # Status Frame
        # Now Playing Frame (shows current or last played song)
        now_frame = ttk.LabelFrame(main_frame, text="Now Playing", padding=10)
        now_frame.pack(fill="x", padx=20, pady=10)

        # Left: cover image
        cover_size = 128
        self.cover_placeholder = Image.new('RGB', (cover_size, cover_size), (200, 200, 200))
        self.cover_photo = ImageTk.PhotoImage(self.cover_placeholder)
        self.cover_label = ttk.Label(now_frame, image=self.cover_photo)
        self.cover_label.image = self.cover_photo
        self.cover_label.grid(row=0, column=0, rowspan=4, padx=(0, 10))

        # Right: text info
        ttk.Label(now_frame, text="State:").grid(row=0, column=1, sticky="w")
        ttk.Label(now_frame, textvariable=self.display_state_var, wraplength=360, justify="left").grid(row=0, column=2, sticky="w")
        ttk.Label(now_frame, text="Title:").grid(row=1, column=1, sticky="w")
        ttk.Label(now_frame, textvariable=self.display_title_var, wraplength=360, justify="left").grid(row=1, column=2, sticky="w")
        ttk.Label(now_frame, text="Artist:").grid(row=2, column=1, sticky="w")
        ttk.Label(now_frame, textvariable=self.display_artist_var, wraplength=360, justify="left").grid(row=2, column=2, sticky="w")
        ttk.Label(now_frame, text="Album:").grid(row=3, column=1, sticky="w")
        ttk.Label(now_frame, textvariable=self.display_album_var, wraplength=360, justify="left").grid(row=3, column=2, sticky="w")

        # Allow the right-side info column to expand and wrap long text
        try:
            now_frame.columnconfigure(2, weight=1)
        except Exception:
            pass

        # Open on Last.fm button
        self.open_button = ttk.Button(now_frame, text="Open on Last.fm", command=self._open_lastfm_url, state="disabled")
        self.open_button.grid(row=4, column=1, columnspan=2, sticky="w", pady=(6,0))

        # Status Frame (keeps only the status label)
        status_frame = ttk.LabelFrame(main_frame, text="Status", padding=15)
        status_frame.pack(fill="x", expand=False, padx=20, pady=10)

        # Status Label
        self.status_var = tk.StringVar(value="Idle")
        self.status_label = ttk.Label(status_frame, textvariable=self.status_var, font=("Arial", 12), foreground="gray")
        self.status_label.pack(pady=10)

        # Indicators placed in one row
        indicators_frame = ttk.Frame(status_frame)
        indicators_frame.pack(fill="x", padx=5, pady=4)

        # Service running indicator (left)
        ttk.Label(indicators_frame, text="Service:", font=("Arial", 10)).grid(row=0, column=0, sticky="w")
        ttk.Label(indicators_frame, textvariable=self.service_running_var, font=("Arial", 10)).grid(row=0, column=1, sticky="w", padx=(6, 10))

        # Spacer to increase separation between the two indicators
        indicators_frame.grid_columnconfigure(1, minsize=300)

        # Now playing indicator (right)
        ttk.Label(indicators_frame, text="Now Playing:", font=("Arial", 10)).grid(row=0, column=2, sticky="w")
        ttk.Label(indicators_frame, textvariable=self.now_playing_var, font=("Arial", 10)).grid(row=0, column=3, sticky="w", padx=(6, 0))

        # --- Logs Tab ---
        log_frame = ttk.Frame(notebook)
        notebook.add(log_frame, text="Logs")

        # Log Text (top area) with scrollbar using grid so scrollbar sticks to the text
        self.log_text = tk.Text(log_frame, height=20, width=80, state="disabled")
        scrollbar = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        self.log_text.config(yscrollcommand=scrollbar.set)
        # place widgets with grid to ensure proper layout
        self.log_text.grid(row=0, column=0, sticky="nsew", padx=(10,0), pady=(10,0))
        scrollbar.grid(row=0, column=1, sticky="ns", padx=(0,10), pady=(10,0))
        # allow text to expand
        log_frame.grid_rowconfigure(0, weight=1)
        log_frame.grid_columnconfigure(0, weight=1)

        # Bottom button bar for actions related to logs
        button_bar = ttk.Frame(log_frame)
        button_bar.grid(row=1, column=0, columnspan=2, sticky="ew", pady=8, padx=10)

        # Clear Log Button centered in the button bar
        clear_button = ttk.Button(button_bar, text="Clear Log", command=self.clear_log)
        clear_button.pack(anchor="center")

        # --- Settings Tab ---
        settings_frame = ttk.Frame(notebook)
        notebook.add(settings_frame, text="Settings")

        # Minimize to tray option
        minimize_check = ttk.Checkbutton(settings_frame, text="Minimize to system tray when minimized", variable=self.minimize_to_tray_var)
        minimize_check.pack(anchor="w", padx=20, pady=20)
        # Start service on app startup option
        start_launch_check = ttk.Checkbutton(settings_frame, text="Start service on application startup", variable=self.start_on_launch_var)
        start_launch_check.pack(anchor="w", padx=20, pady=(0,20))
    
    def log_message(self, message):
        # Add message to log
        self.log_text.config(state="normal")
        self.log_text.insert("end", message + "\n")
        self.log_text.see("end")
        self.log_text.config(state="disabled")
    
    def clear_log(self):
        # Clear log
        self.log_text.config(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.config(state="disabled")

    def stream_process_output(self, proc):
        # Start background threads to stream subprocess stdout/stderr into GUI log.
        def reader(stream, prefix=""):
            try:
                partial = {}
                for line in iter(stream.readline, ""):
                    if not line:
                        break
                    text = line.rstrip()
                    try:
                        self.root.after(0, self.log_message, f"{prefix}{text}")
                    except Exception:
                        pass

                    # Only attempt to parse stdout (ignore stderr prefixed lines)
                    if prefix:
                        continue

                    l = text.strip()

                    # Detect Now Playing line (may contain a leading counter like '1. ')
                    if "Now Playing:" in l:
                        try:
                            after = l.split("Now Playing:", 1)[1].strip()
                            # remove trailing duration info if present
                            if "..." in after:
                                main_part = after.split("...")[0].strip()
                            elif "Duration" in after:
                                main_part = after.split("Duration")[0].strip()
                            else:
                                main_part = after
                            parts = main_part.split(" - ", 1)
                            artist = parts[0].strip() if len(parts) > 0 else ""
                            title = parts[1].strip() if len(parts) > 1 else ""
                        except Exception:
                            artist = ""
                            title = ""
                        partial = {"state": "Now Playing", "artist": artist, "title": title, "album": "", "s_url": "", "l_image": ""}
                        self.root.after(0, self._update_current_song, partial.copy())

                    # Detect Last Played line (short form)
                    elif "Last Played:" in l:
                        try:
                            after = l.split("Last Played:", 1)[1].strip()
                            parts = after.split(" - ", 1)
                            artist = parts[0].strip() if len(parts) > 0 else ""
                            title = parts[1].strip() if len(parts) > 1 else ""
                        except Exception:
                            artist = ""
                            title = ""
                        partial = {"state": "Last Played", "artist": artist, "title": title, "album": "", "s_url": "", "l_image": ""}
                        self.root.after(0, self._update_current_song, partial.copy())

                    # Additional detail lines follow when Now Playing: Album/URL/Image
                    elif l.startswith("Album:"):
                        album = l.split("Album:", 1)[1].strip()
                        partial["album"] = album
                        self.root.after(0, self._update_current_song, partial.copy())

                    elif l.startswith("URL:"):
                        s_url = l.split("URL:", 1)[1].strip()
                        partial["s_url"] = s_url
                        self.root.after(0, self._update_current_song, partial.copy())

                    elif l.startswith("Image:"):
                        img = l.split("Image:", 1)[1].strip()
                        partial["l_image"] = img
                        self.root.after(0, self._update_current_song, partial.copy())
            except Exception as e:
                try:
                    self.root.after(0, self.log_message, f"Error reading process output: {e}")
                except Exception:
                    pass

        if proc is None:
            return

        if getattr(proc, 'stdout', None):
            self.stdout_thread = threading.Thread(target=reader, args=(proc.stdout, ""), daemon=True)
            self.stdout_thread.start()
        if getattr(proc, 'stderr', None):
            self.stderr_thread = threading.Thread(target=reader, args=(proc.stderr, "ERR: "), daemon=True)
            self.stderr_thread.start()

    # Internal helper: create a stream-like object that forwards writes to the GUI log
    class _StreamWriter:
        def __init__(self, gui, prefix=""):
            self.gui = gui
            self.prefix = prefix
            self._buf = ""

        def write(self, s):
            try:
                if not s:
                    return
                self._buf += s
                while "\n" in self._buf:
                    line, self._buf = self._buf.split("\n", 1)
                    text = line.rstrip('\r')
                    try:
                        # log line in GUI
                        self.gui.root.after(0, self.gui.log_message, f"{self.prefix}{text}")
                        # also hand the raw text to the GUI parser (without ERR: prefix)
                        # use root.after to ensure GUI thread safety
                        self.gui.root.after(0, self.gui._handle_output_text, text)
                    except Exception:
                        pass
            except Exception:
                pass

        def flush(self):
            return

        # Provide minimal attributes some code may expect
        def isatty(self):
            return False

        @property
        def encoding(self):
            return 'utf-8'

    def _run_main_wrapper(self):
        # Run main.set_user_data() and restore streams when finished
        try:
            main.set_user_data()
        except Exception as e:
            try:
                self.root.after(0, self.log_message, f"Error in in-process service: {e}")
            except Exception:
                pass
        finally:
            try:
                # restore original streams if we replaced them
                if hasattr(self, '_orig_stdout'):
                    sys.stdout = self._orig_stdout
                else:
                    sys.stdout = sys.__stdout__
            except Exception:
                pass
            try:
                if hasattr(self, '_orig_stderr'):
                    sys.stderr = self._orig_stderr
                else:
                    sys.stderr = sys.__stderr__
            except Exception:
                pass

            # Ensure GUI reflects stopped service
            try:
                self.is_running = False
                self.root.after(0, lambda: self.service_running_var.set("Stopped"))
                self.root.after(0, lambda: self.status_var.set("Stopped"))
                self.root.after(0, lambda: self.status_label.config(foreground="red"))
                self.root.after(0, lambda: self.start_button.config(state="normal"))
                self.root.after(0, lambda: self.stop_button.config(state="disabled"))
                self.root.after(0, self._clear_now_playing_display)
                self.root.after(0, lambda: self.log_message("Service stopped."))
            except Exception:
                pass

    def _handle_output_text(self, l):
        # Parse a single output line (runs on GUI thread via root.after)
        try:
            text = l.strip()
        except Exception:
            text = l

        # keep a partial dict for in-process parsing
        if not hasattr(self, '_inproc_partial') or self._inproc_partial is None:
            self._inproc_partial = {}

        partial = self._inproc_partial

        # Detect Now Playing line (may contain a leading counter like '1. ')
        if "Now Playing:" in text:
            try:
                after = text.split("Now Playing:", 1)[1].strip()
                if "..." in after:
                    main_part = after.split("...")[0].strip()
                elif "Duration" in after:
                    main_part = after.split("Duration")[0].strip()
                else:
                    main_part = after
                parts = main_part.split(" - ", 1)
                artist = parts[0].strip() if len(parts) > 0 else ""
                title = parts[1].strip() if len(parts) > 1 else ""
            except Exception:
                artist = ""
                title = ""
            partial.clear()
            partial.update({"state": "Now Playing", "artist": artist, "title": title, "album": "", "s_url": "", "l_image": ""})
            try:
                self._update_current_song(partial.copy())
            except Exception:
                pass

        # Detect Last Played
        elif "Last Played:" in text:
            try:
                after = text.split("Last Played:", 1)[1].strip()
                parts = after.split(" - ", 1)
                artist = parts[0].strip() if len(parts) > 0 else ""
                title = parts[1].strip() if len(parts) > 1 else ""
            except Exception:
                artist = ""
                title = ""
            partial.clear()
            partial.update({"state": "Last Played", "artist": artist, "title": title, "album": "", "s_url": "", "l_image": ""})
            try:
                self._update_current_song(partial.copy())
            except Exception:
                pass

        # Album line
        elif text.startswith("Album:"):
            try:
                album = text.split("Album:", 1)[1].strip()
                partial["album"] = album
                self._update_current_song(partial.copy())
            except Exception:
                pass

        # URL line
        elif text.startswith("URL:"):
            try:
                s_url = text.split("URL:", 1)[1].strip()
                partial["s_url"] = s_url
                self._update_current_song(partial.copy())
            except Exception:
                pass

        # Image line
        elif text.startswith("Image:"):
            try:
                img = text.split("Image:", 1)[1].strip()
                partial["l_image"] = img
                self._update_current_song(partial.copy())
            except Exception:
                pass

    def _update_current_song(self, songdict):
        # Update stored song fields (called on the Tk main thread via root.after)
        try:
            self.current_state = songdict.get('state')
            self.current_artist = songdict.get('artist')
            self.current_title = songdict.get('title')
            # album, url, image may be empty until their lines are parsed
            album = songdict.get('album')
            if album:
                self.current_album = album
            s_url = songdict.get('s_url')
            if s_url:
                self.current_lastfm_url = s_url
            img = songdict.get('l_image')
            if img:
                self.current_image_url = img
        except Exception:
            pass
        # Also update UI display vars (this runs on main thread)
        try:
            self.display_state_var.set(self.current_state or "")
            self.display_title_var.set(self.current_title or "")
            self.display_artist_var.set(self.current_artist or "")
            self.display_album_var.set(self.current_album or "")
        except Exception:
            pass

        # Update now playing indicator
        try:
            if songdict.get('state') == 'Now Playing':
                try:
                    self.root.after(0, lambda: self.now_playing_var.set('Yes'))
                except Exception:
                    pass
            else:
                try:
                    self.root.after(0, lambda: self.now_playing_var.set('No'))
                except Exception:
                    pass
        except Exception:
            pass

        # If there's an image URL and it's changed, fetch it asynchronously
        try:
            img_url = songdict.get('l_image')
            if img_url and img_url != "" and img_url != getattr(self, 'last_fetched_image_url', None):
                self.last_fetched_image_url = img_url
                def fetch():
                    try:
                        resp = requests.get(img_url, timeout=6)
                        resp.raise_for_status()
                        im = Image.open(BytesIO(resp.content)).convert('RGB')
                        im.thumbnail((128, 128))
                        photo = ImageTk.PhotoImage(im)
                        def set_image():
                            try:
                                self.cover_photo = photo
                                self.cover_label.configure(image=self.cover_photo)
                                self.cover_label.image = self.cover_photo
                            except Exception:
                                pass
                        self.root.after(0, set_image)
                    except Exception:
                        pass
                t = threading.Thread(target=fetch, daemon=True)
                t.start()
        except Exception:
            pass
        # Enable or disable the Open button depending on URL availability
        try:
            if getattr(self, 'open_button', None):
                if self.current_lastfm_url:
                    self.open_button.config(state='normal')
                else:
                    self.open_button.config(state='disabled')
        except Exception:
            pass

        # Update tray menu/title if tray is active
        try:
            if getattr(self, 'is_tray', False) and getattr(self, 'tray_icon', None):
                try:
                    self.update_tray_menu()
                except Exception:
                    pass
        except Exception:
            pass

    def _open_lastfm_url(self):
        try:
            url = self.current_lastfm_url
            if url:
                webbrowser.open(url)
        except Exception:
            pass

    def _clear_now_playing_display(self):
        # Clear stored song info and reset UI elements
        try:
            self.current_state = None
            self.current_title = None
            self.current_artist = None
            self.current_album = None
            self.current_lastfm_url = None
            self.current_image_url = None
            self.last_fetched_image_url = None
        except Exception:
            pass

        try:
            self.display_state_var.set("")
            self.display_title_var.set("")
            self.display_artist_var.set("")
            self.display_album_var.set("")
        except Exception:
            pass

        try:
            self.now_playing_var.set('No')
        except Exception:
            pass

        try:
            if getattr(self, 'open_button', None):
                self.open_button.config(state='disabled')
        except Exception:
            pass

        try:
            # restore placeholder cover
            if getattr(self, 'cover_placeholder', None) is not None:
                photo = ImageTk.PhotoImage(self.cover_placeholder)
                self.cover_photo = photo
                self.cover_label.configure(image=self.cover_photo)
                self.cover_label.image = self.cover_photo
        except Exception:
            pass
        # Update tray to reflect cleared state
        try:
            if getattr(self, 'is_tray', False) and getattr(self, 'tray_icon', None):
                try:
                    self.update_tray_menu()
                except Exception:
                    pass
        except Exception:
            pass
    
    def start_service(self):
        # Start the Discord presence service
        if not self.is_running:
            self.is_running = True
            try:
                self.root.after(0, lambda: self.status_var.set("Running"))
                self.root.after(0, lambda: self.service_running_var.set("Running"))
                self.root.after(0, lambda: self.status_label.config(foreground="green"))
            except Exception:
                pass
            self.start_button.config(state="disabled")
            self.stop_button.config(state="normal")
            
            # Save config before starting
            self.save_config()
            # Ensure any previous stop signal is cleared so the service can restart
            try:
                main.kill_switch = False
            except Exception:
                pass
            
            try:
                # If running as a frozen executable, run the service in-process
                # to avoid requiring a separate main.py file alongside the exe.
                if getattr(sys, 'frozen', False):
                    self.log_message("Running service in-process (frozen executable).")
                    # Replace stdout/stderr so prints from main show up in the GUI
                    try:
                        self._orig_stdout = sys.stdout
                        self._orig_stderr = sys.stderr
                        sys.stdout = self._StreamWriter(self, "")
                        sys.stderr = self._StreamWriter(self, "ERR: ")
                    except Exception:
                        pass

                    # Run main in a background thread but keep handle so we can join on stop
                    t = threading.Thread(target=self._run_main_wrapper, daemon=True)
                    self.rpc_thread = t
                    t.start()
                    return

                # When not frozen, prefer launching an external Python interpreter
                # so the GUI process isn't blocked by the service.
                interpreter = sys.executable
                py = shutil.which("python") or shutil.which("py")
                if py:
                    interpreter = py

                self.rpc_thread = subprocess.Popen([interpreter, "-u", "main.py", self.config['client_id'], self.config['lastfm_key'], self.config['lastfm_name'], str(self.config['check_interval']), str(self.config['pp_strategy'])], stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=1, text=True, encoding='utf-8', errors='replace')
                # Start streaming subprocess output into GUI log
                self.stream_process_output(self.rpc_thread)
            except Exception as e:
                self.log_message(f"Error starting service: {str(e)}")
                self.is_running = False
                try:
                    self.root.after(0, lambda: self.service_running_var.set("Stopped"))
                    self.root.after(0, lambda: self.status_var.set("Error"))
                    self.root.after(0, lambda: self.status_label.config(foreground="red"))
                except Exception:
                    pass
                self.start_button.config(state="normal")
                self.stop_button.config(state="disabled")
                print(f"Error starting service: {e}")
                return
    
            self.log_message("Service started...")
            self.log_message(f"Username: {self.config['lastfm_name']}")
            self.log_message(f"Check Interval: {self.config['check_interval']}s")
            self.log_message(f"Strategy: {'Dynamic' if self.config['pp_strategy'] == 1 else 'Traditional'}")

    def stop_service(self):
        # Stop the Discord presence service"""
        if self.is_running:
            self.is_running = False
            main.kill_switch = True
            try:
                if self.rpc_thread:
                    # If rpc_thread is a threading.Thread (in-process run), join it
                    if isinstance(self.rpc_thread, threading.Thread):
                        try:
                            # For in-process (frozen) runs: signal the main loop to stop
                            # via main.kill_switch and allow the background thread to
                            # perform clean shutdown (it restores streams in its
                            # finally block). Avoid joining or restoring streams here
                            # — joining on the GUI thread or touching streams can
                            # cause the frozen exe to terminate unexpectedly.
                            if self.rpc_thread.is_alive():
                                self.log_message("Signaled in-process service to stop; waiting for cleanup.")
                        except Exception:
                            pass
                    else:
                        # assume subprocess.Popen
                        try:
                            self.rpc_thread.terminate()
                            self.rpc_thread.wait()
                        except Exception:
                            try:
                                self.rpc_thread.kill()
                            except Exception:
                                pass
                        try:
                            if getattr(self.rpc_thread, 'stdout', None):
                                self.rpc_thread.stdout.close()
                            if getattr(self.rpc_thread, 'stderr', None):
                                self.rpc_thread.stderr.close()
                        except Exception:
                            pass
                    if self.stdout_thread and self.stdout_thread.is_alive():
                        try:
                            self.stdout_thread.join(timeout=1)
                        except Exception:
                            pass
                    if self.stderr_thread and self.stderr_thread.is_alive():
                        try:
                            self.stderr_thread.join(timeout=1)
                        except Exception:
                            pass
            except Exception as e:
                print(f"Error stopping Discord Rich Presence: {e}")
                try:
                    if self.rpc_thread:
                        self.rpc_thread.kill()
                        print("Discord Rich Presence forcefully stopped.")
                except Exception as e:
                    print(f"Error forcefully stopping Discord Rich Presence: {e}")
            
            try:
                self.root.after(0, lambda: self.status_var.set("Stopped"))
                self.root.after(0, lambda: self.service_running_var.set("Stopped"))
                self.root.after(0, lambda: self.status_label.config(foreground="red"))
            except Exception:
                pass
            self.start_button.config(state="normal")
            self.stop_button.config(state="disabled")


            self.log_message("Service stopped.")
            try:
                # Clear Now Playing display when service is stopped
                self.root.after(0, self._clear_now_playing_display)
            except Exception:
                pass
    
    def on_closing(self):
        # Handle window closing"""
        if self.is_running:
            self.stop_service()
        self.hide_tray_icon()
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    gui = LastFMGUI(root)
    root.mainloop()