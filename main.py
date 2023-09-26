import os, time, pypresence, random, sys, subprocess, threading, json, argparse, atexit, re, requests, requests_cache, math, unicodedata

try:
    import tty, termios

    UNIX_TTY = True
except Exception:
    UNIX_TTY = False
    try:
        import msvcrt

        MSVCRT = True
    except ImportError:
        MSVCRT = False

from typing import TYPE_CHECKING, Any

os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "hide"
from pygame import mixer

requests_cache.install_cache("inflo_cache", backend="memory", expire_after=3600)
print("\n\x1b[?25l")
atexit.register(print, "\x1b[?25h", end="")

try:
    from mutagen.mp3 import MP3
except ImportError:
    print("warning: no mutagen. falling back to ffmpeg for mp3 length detection.")

YOUTUBE_DL_ID_REGEX = re.compile(r"\[[a-zA-Z0-9\-_]{11}]")
MOVE_AND_CLEAR_LINE = "\x1b[1A\x1b[2K"

class MusicPlayer:
    presence: "pypresence.Presence | None"
    normal_tty_settings: "list[Any]"
    diff: "float | None"
    playing: "bool"
    presence_update_lock: "threading.Lock"
    weights_file: "str"
    length: "float"
    volume: "float"
    initial: "str"
    lines_written: "int"

    def __init__(self, presence: "pypresence.Presence | None", initial: "str", weights_file: "str", disable_api: "bool"):
        self.presence = presence
        self.disable_api = disable_api
        self.weights_file = weights_file
        self.initial = initial

    def start(self) -> None:
        self.presence_update_lock = threading.Lock()
        self.volume = 1.0
        self.lines_written = 3
        if UNIX_TTY:
            self.normal_tty_settings = termios.tcgetattr(sys.stdin.fileno())
            atexit.register(self.unsetraw)
        self.setraw()
        mixer.init()
        if self.initial is not None:
            self.play(self.initial)
        self.run()

    def generate_weights(self):
        if self.weights_file is None:
            return [list(filter(lambda k: k.endswith("mp3"), os.listdir("."))), None]
        data = json.load(open(self.weights_file, encoding="utf8"))
        files = list(filter(lambda k: k.endswith("mp3"), os.listdir(".")))
        weights = {}
        for key in data:
            if key in files:
                weights[key] = data[key]
            else:
                autocompletions = list(filter(lambda k: k.startswith(key), files))
                if len(autocompletions) == 0:
                    print(f"No such key {key}")
                for completion in autocompletions:
                    weights[completion] = data[key]
        for file in files:
            if file not in weights:
                weights[file] = 1
        return zip(*weights.items())

    def run(self):
        while True:
            keys, weights = self.generate_weights()
            self.play(random.choices(keys, weights)[0])

    def setraw(self):
        if UNIX_TTY:
            tty.setraw(sys.stdin.fileno())
            os.set_blocking(sys.stdin.fileno(), False)

    def unsetraw(self):
        if UNIX_TTY:
            termios.tcsetattr(
                sys.stdin.fileno(), termios.TCSADRAIN, self.normal_tty_settings
            )

    def update(self, *args, **kwargs):
        buttons = [
            {
                "label": "Source code",
                "url": "https://github.com/pandaninjas/Inflo",
            }
        ]
        match = YOUTUBE_DL_ID_REGEX.search(kwargs["state"])
        large_image_url = None
        channel_name = None
        if match:
            video_id = match.group(0).strip("[]")
            if self.disable_api:
                large_image_url = (
                    f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg"
                )
                channel_name = None
            else:
                try:
                    api_result = requests.get(
                        "https://inflo-api.thefightagainstmalware.workers.dev/"
                        + video_id,
                        timeout=1
                    ).json()
                    large_image_url = api_result["maxres"]
                    channel_name = api_result["channelTitle"]
                except Exception:
                    large_image_url = (
                        f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg"
                    )
                    channel_name = None
            if "end" in kwargs:
                buttons.append(
                    {
                        "label": "Join",
                        "url": f"https://youtube.com/watch?v={video_id}&t={round(self.length - (kwargs['end'] - time.time()))}",
                    }
                )
            else:
                buttons.append(
                    {"label": "Join", "url": f"https://youtube.com/watch?v={video_id}"}
                )

        if self.presence != None:
            try:
                self.presence.update(
                    *args,
                    **kwargs,
                    large_image=large_image_url,
                    buttons=buttons,
                    large_text=channel_name,
                )
            except Exception:
                try:
                    self.presence.close()
                except Exception:
                    pass
                self.presence = None

    def reload_presence(self, name, end):
        try:
            self.presence.close()
        except Exception:
            pass
        self.presence = pypresence.Presence("1033827079994753064")
        self.presence.connect()
        self.update(state=name, end=end)

    def play(self, song: str) -> None:
        name = song.replace(".mp3", "").strip()
        self.length = self.get_length(song)
        end = time.time() + self.length
        self.playing = True
        self.update(state=name, end=end)
        count = 0
        mixer.music.load(song)
        mixer.music.play()
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
                            state=name,
                            details="Paused",
                            start=time.time(),
                        )
                    self.unsetraw()
                    print(
                        f"\x1b[2K\r{MOVE_AND_CLEAR_LINE * (self.lines_written - 1)}\rPaused: {name}, time left: {self.diff:.2f}\ncontrols: [s]kip, [r]eload presence, [p]lay, volume [u]p, volume [d]own\nvolume: {self.volume:.2f}",
                        end="",
                    )
                    self.setraw()
                else:
                    if TYPE_CHECKING:
                        assert self.diff is not None
                    mixer.music.unpause()
                    self.playing = True
                    self.update(state=name, end=time.time() + self.diff)
                    end = time.time() + self.diff
            elif c == "u":
                self.volume += 0.01
                mixer.music.set_volume(self.volume)
            elif c == "d":
                self.volume -= 0.01
                mixer.music.set_volume(self.volume)
            if count % 100 == 0:
                end = (self.length - mixer.music.get_pos() / 1000) + time.time()
            # x1b for ESC
            if self.playing:
                self.unsetraw()
                if count % 100 == 0:
                    self.update(state=name, end=end)
                to_print = f"Now playing {name}, time left: {(end - time.time()):.2f}\ncontrols: [s]kip, [r]eload presence, [p]ause, volume [u]p, volume [d]own\nvolume: {self.volume:.2f}"
                print(
                    f"\x1b[2K\r{MOVE_AND_CLEAR_LINE * (self.lines_written - 1)}{to_print}\r",
                    end="",
                )
                self.lines_written = sum(map(lambda k: math.ceil(self.term_length(k) / os.get_terminal_size().columns), to_print.split("\n")))
                self.setraw()
            count += 1
            time.sleep(0.01)
        print(
            f"\x1b[2K\r{MOVE_AND_CLEAR_LINE * (self.lines_written - 1)}\rNow playing {name}, time left: 0.00\ncontrols: [s]kip, [r]eload presence, [p]ause, volume [u]p, volume [d]own\nvolume: {self.volume:.2f}",
            end="",
        )
        print(
            "\n" * (self.lines_written - 3), end=""
        )
        print("\x1b")

    def term_length(self, string: str) -> int:
        length = 0
        for char in string:
            length += 2 if unicodedata.east_asian_width(char) in ["W", "F"] else 1
        return length

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
                            "format=duration",
                            "-v",
                            "quiet",
                            "-of",
                            'csv="p=0"',
                        ]
                    )
                )
            except Exception:
                print("warning: ffmpeg failed. setting length to 0")
                return 0

    def getch(self):
        if UNIX_TTY or MSVCRT:
            if UNIX_TTY:
                c = sys.stdin.read(1)
            else:
                c = msvcrt.getwch() if msvcrt.kbhit() else ""
            if c == "\x03":
                raise KeyboardInterrupt()
            return c
        else:
            return ""


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        prog="Inflo",
        description="A lightweight music player",
    )

    parser.add_argument("first_song", nargs="?")
    parser.add_argument("--weights", required=False)
    parser.add_argument("--disable-discord", action="store_true")
    parser.add_argument("--disable-api", action="store_true")
    args = parser.parse_args()

    pres = None
    if not args.disable_discord:
        try:
            pres = pypresence.Presence("1033827079994753064")
            pres.connect()
        except Exception as e:
            print("No pres: " + str(e))
            pres = None

    player = MusicPlayer(
        pres, args.first_song, weights_file=args.weights, disable_api=args.disable_api
    )
    player.start()
