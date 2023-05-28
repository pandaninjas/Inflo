import os, time, pypresence, random, sys, subprocess, tty, termios, threading
from typing import Any
from pygame import mixer

try:
    from mutagen.mp3 import MP3
except ImportError:
    print("warning: no mutagen. falling back to ffmpeg for mp3 length detection.")


class MusicPlayer:
    presence: "pypresence.Presence | None"
    normal_tty_settings: "list[Any]"
    diff: "float | None"
    playing: "bool"
    presence_update_lock: "threading.Lock"

    def __init__(self, presence, initial):
        self.presence = presence
        self.normal_tty_settings = termios.tcgetattr(sys.stdin.fileno())
        self.presence_update_lock = threading.Lock()
        self.setraw()
        mixer.init()
        if initial is not None:
            self.play(initial)
        self.run()

    def run(self):
        while True:
            self.play(random.choice(os.listdir(".")))

    def setraw(self):
        tty.setraw(sys.stdin.fileno())
        os.set_blocking(sys.stdin.fileno(), False)

    def unsetraw(self):
        termios.tcsetattr(
            sys.stdin.fileno(), termios.TCSADRAIN, self.normal_tty_settings
        )

    def update(self, *args, **kwargs):
        if self.presence != None:
            self.presence.update(*args, **kwargs, buttons=[{"label": "Source code", "url": "https://github.com/pandaninjas/Inflo"}])

    def reload_presence(self, name, end):
        self.presence = pypresence.Presence("1033827079994753064")
        self.presence.connect()
        self.presence.update(state=f"Listening to {name}", end=end)

    def play(self, song: str) -> None:
        name = song.replace(".mp3", "").strip()
        length = self.get_length(song)
        end = time.time() + length
        mixer.music.load(song)
        mixer.music.play()
        self.playing = True
        self.update(state=f"Listening to {name}", end=end)
        last_time_update = time.time()
        while mixer.music.get_busy() or not self.playing:
            c = self.getch()
            if c == "s":
                print()
                return
            elif c == "r":
                with self.presence_update_lock:
                    threading.Thread(target=self.reload_presence, args=(name, end)).start()                                
            elif c == "p":
                if self.playing:
                    self.diff = end - time.time()
                    mixer.music.pause()
                    self.playing = False
                    if self.presence is not None:
                        self.update(
                            state=f"Listening to {name}",
                            details="Paused",
                            start=time.time(),
                        )
                    self.unsetraw()
                    print(
                        f"\x1b[2K\r\x1b[1A\x1b[2K\rPaused: {name}, time left: {self.diff:.2f}\ncontrols: [s]kip, [r]eload presence, [p]ause",
                        end="",
                    )
                    self.setraw()
                else:
                    mixer.music.unpause()
                    self.playing = True
                    self.update(
                        state=f"Listening to {name}", end=time.time() + self.diff
                    )
                    end = time.time() + self.diff
            
            end = (length - mixer.music.get_pos() / 1000) + time.time()
            self.unsetraw()
            # x1b for ESC
            if self.playing:
                if last_time_update + 10 <= time.time():
                    last_time_update = time.time()
                    self.update(state=f"Listening to {name}", end=end)
                print(
                    f"\x1b[2K\r\x1b[1A\x1b[2K\rNow playing {name}, time left: {(end - time.time()):.2f}\ncontrols: [s]kip, [r]eload presence, [p]ause",
                    end="",
                )
            self.setraw()
            time.sleep(0.01)
        print("\x1b")

    def get_length(self, music: str) -> float:
        try:
            return MP3(music).info.length
        except Exception:
            try:
                return float(
                    subprocess.check_output(
                        [
                            "ffprobe",
                            "-i",
                            music,
                            "-show_entries"
                            "format=duration"
                            "-v"
                            "quiet"
                            "-of"
                            'csv="p=0"',
                        ]
                    )
                )
            except Exception:
                print("warning: ffmpeg failed. setting length to 0")
                return 0

    def getch(self) -> str:
        ch = sys.stdin.read(1)
        if ch == "\x03":
            raise KeyboardInterrupt()
        elif ch == "\x04":
            raise EOFError()
        else:
            return ch


try:
    pres = pypresence.Presence("1033827079994753064")
    pres.connect()
except Exception as e:
    print("No pres: " + str(e))
    pres = None

player = MusicPlayer(pres, sys.argv[1] if len(sys.argv) > 1 else None)
