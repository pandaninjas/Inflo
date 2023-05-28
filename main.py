import os, time, pypresence, random, sys, subprocess, tty, termios, threading, json, argparse, atexit
from typing import Any

os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "hide"
from pygame import mixer

print()

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
    weights_file: str

    def __init__(self, presence, initial, weights_file):
        self.presence = presence
        self.normal_tty_settings = termios.tcgetattr(sys.stdin.fileno())
        atexit.register(self.unsetraw)
        self.presence_update_lock = threading.Lock()
        self.weights_file = weights_file
        self.setraw()
        mixer.init()
        if initial is not None:
            self.play(initial)
        self.run()

    def generate_weights(self):
        if self.weights_file is None:
            return [os.listdir("."), None]
        data = json.load(open(self.weights_file))
        files = os.listdir(".")
        weights = {}
        for key in data:
            if key in files:
                weights[key] = data[key]
            else:
                autocompletions = list(filter(lambda k: k.startswith(key), files))
                if len(autocompletions) > 1:
                    print(f"Ambiguous autocompletion: {key}")
                elif len(autocompletions) == 0:
                    print(f"No such key {key}")
                weights[autocompletions[0]] = data[key]
        
        for file in files:
            if file not in weights:
                weights[file] = 1
        return zip(*weights.items())

    def run(self):
        while True:
            keys, weights = self.generate_weights()
            self.play(random.choices(keys, weights)[0])

    def setraw(self):
        tty.setraw(sys.stdin.fileno())
        os.set_blocking(sys.stdin.fileno(), False)

    def unsetraw(self):
        termios.tcsetattr(
            sys.stdin.fileno(), termios.TCSADRAIN, self.normal_tty_settings
        )

    def update(self, *args, **kwargs):
        if self.presence != None:
            self.presence.update(
                *args,
                **kwargs,
                buttons=[
                    {
                        "label": "Source code",
                        "url": "https://github.com/pandaninjas/Inflo",
                    }
                ],
            )

    def reload_presence(self, name, end):
        self.presence.close()
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
                    threading.Thread(
                        target=self.reload_presence, args=(name, end)
                    ).start()
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
                            "-show_entries",
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


parser = argparse.ArgumentParser(
    prog="Inflo",
    description="A lightweight music player",
)

parser.add_argument("first_song", nargs="?")
parser.add_argument("--weights", required=False)

args = parser.parse_args()

try:
    pres = pypresence.Presence("1033827079994753064")
    pres.connect()
except Exception as e:
    print("No pres: " + str(e))
    pres = None

player = MusicPlayer(
    pres,
    args.first_song,
    weights_file=args.weights,
)
