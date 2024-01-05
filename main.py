import os, time, pypresence, random, sys, subprocess, threading, json, argparse, atexit, re, requests, requests_cache, math, unicodedata
from typing import TYPE_CHECKING, Any

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
ANSI_REGEX = re.compile("\x1b\\[\\d+?m")
INFLO_SHARE_URL = "https://inflo-share-server.onrender.com/"


class IOUtilities:
    @staticmethod
    def generate_weights(weights_file: str):
        if weights_file is None:
            return [list(filter(lambda k: k.endswith("mp3"), os.listdir("."))), None]
        data: "dict[str, str]" = json.load(open(weights_file, encoding="utf8"))
        # sort data by key length, shortest first. this allows longer completions to override shorter ones
        data = {k: v for k, v in sorted(data.items(), key=lambda item: len(item[0]))}

        files = list(filter(lambda k: k.endswith("mp3"), os.listdir(".")))
        weights = {}
        for key in data:
            if not isinstance(data[key], (int, float)):
                continue
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

    @staticmethod
    def setraw():
        if UNIX_TTY:
            tty.setraw(sys.stdin.fileno())
            os.set_blocking(sys.stdin.fileno(), False)

    @staticmethod
    def unsetraw(normal_tty_settings):
        if UNIX_TTY:
            termios.tcsetattr(
                sys.stdin.fileno(), termios.TCSADRAIN, normal_tty_settings
            )

    @staticmethod
    def term_length(string: str) -> int:
        string = ANSI_REGEX.sub("", string)
        length = 0
        for char in string:
            length += 2 if unicodedata.east_asian_width(char) in ["W", "F"] else 1
        return length

    @staticmethod
    def process_name(name: str) -> "list[str]":
        lines = []
        cur = ""
        cur_len = 0
        idx = 0
        while idx < len(name):
            while cur_len < 30 and idx < len(name):
                cur += name[idx]  # TODO: use graphemes instead
                cur_len += IOUtilities.term_length(name[idx])
                idx += 1
            lines.append(cur)
            cur = ""
            cur_len = 0
        return lines


class MusicPlayer:
    presence: "pypresence.Presence | None"
    normal_tty_settings: "list[Any]" = None
    diff: "tuple[float, float] | None"
    playing: "bool"
    presence_update_lock: "threading.Lock"
    weights_file: "str"
    length: "float"
    volume: "float"
    initial: "str"
    lines_written: "int"

    def __init__(
        self,
        presence: "pypresence.Presence | None",
        initial: "str",
        weights_file: "str",
        disable_api: "bool",
        enable_share: "bool",
    ):
        self.presence = presence
        self.disable_api = disable_api
        self.weights_file = weights_file
        self.initial = initial
        self.enable_share = enable_share

    def start(self) -> None:
        self.presence_update_lock = threading.Lock()
        self.volume = 1.0
        self.lines_written = 3
        if UNIX_TTY:
            self.normal_tty_settings = termios.tcgetattr(sys.stdin.fileno())
            atexit.register(IOUtilities.unsetraw, self.normal_tty_settings)
        IOUtilities.setraw()
        mixer.init()
        if self.presence is not None:
            atexit.register(self.presence.close)
        if self.enable_share:
            share = requests.post(INFLO_SHARE_URL + "start").json()
            self.secret: str = share["secret"]
            self.share_id: str = share["id"]
        if self.initial is not None:
            self.play(self.initial)
        self.run()

    def run(self):
        while True:
            keys, weights = IOUtilities.generate_weights(self.weights_file)
            self.play(random.choices(keys, weights)[0])

    def update(self, *args, **kwargs):
        if self.presence is not None:
            with self.presence_update_lock:
                buttons = [
                    {
                        "label": "Source code",
                        "url": "https://github.com/pandaninjas/Inflo",
                    }
                ]
                match = YOUTUBE_DL_ID_REGEX.search(kwargs["name"])
                name = kwargs.pop("name", "")
                details = kwargs.pop("details", "")
                processed_name = IOUtilities.process_name(name)
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
                                timeout=1,
                            ).json()
                            large_image_url = api_result["maxres"]
                            channel_name = api_result["channelTitle"]
                        except Exception:
                            large_image_url = f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg"
                            channel_name = None
                    if not self.enable_share:
                        if "end" in kwargs:
                            buttons.append(
                                {
                                    "label": "Join",
                                    "url": f"https://youtube.com/watch?v={video_id}&t={round(self.length - (kwargs['end'] - time.time()))}",
                                }
                            )
                        else:
                            buttons.append(
                                {
                                    "label": "Join",
                                    "url": f"https://youtube.com/watch?v={video_id}",
                                }
                            )
                    else:
                        buttons.append({
                            "label": "Join",
                            "url": f"{INFLO_SHARE_URL}{self.share_id}"
                        })
                    try:
                        self.presence.update(
                            *args,
                            **kwargs,
                            large_image=large_image_url,
                            buttons=buttons,
                            large_text=channel_name,
                            instance=False,
                            details=details + processed_name[0].strip(),
                            state="".join(processed_name[1:]).strip(),
                        )
                    except Exception as e:
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
        try:
            self.presence.connect()
            self.update(name=name, end=end)
        except Exception:
            pass

    def render_progress_bar(self) -> str:
        start = self.get_start()
        end = self.get_end()
        cur_time = time.time()
        bar_width = os.get_terminal_size().columns - 14
        left_bar_width = int((cur_time - start) / (end - start) * bar_width)
        right_bar_width = bar_width - left_bar_width
        mins_start, secs_start = divmod(cur_time - start, 60)
        mins_end, secs_end = divmod(end - cur_time, 60)
        return f"{int(mins_start)}:{int(secs_start):02d} \x1b[32m{left_bar_width * '━'}\x1b[0m{right_bar_width * '━'} -{int(mins_end)}:{int(secs_end):02d}"

    def update_share(self, youtube_id: str, progress: float, playing: bool):
        if not self.enable_share:
            return
        requests.put(INFLO_SHARE_URL + "update/" + self.secret, json={
            "playing": playing,
            "id": youtube_id,
            "progress": progress
        })

    def get_start(self):
        return time.time() - (mixer.music.get_pos() / 1000)
    
    def get_end(self):
        return time.time() + self.length - (mixer.music.get_pos() / 1000)

    def queue_thread(self, *args):
        threading.Thread(target=args[0], args=args[1:]).start()

    def play(self, song: str) -> None:
        name = song.replace(".mp3", "").strip()
        self.length = self.get_length(song)
        self.playing = True
        self.update(name=name, start=time.time(), end=time.time() + self.length)
        youtube_id = YOUTUBE_DL_ID_REGEX.search(name).group(0).strip("[]")
        self.queue_thread(self.update_share, youtube_id, 0, True)
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
                    self.queue_thread(self.reload_presence, name, self.get_end())
            elif c == "p":
                if self.playing:
                    self.queue_thread(self.update_share, youtube_id, mixer.music.get_pos() / 1000, False)
                    mixer.music.pause()
                    self.playing = False
                    if self.presence is not None:
                        self.update(
                            name="Paused: " + name,
                            start=time.time(),
                        )
                    IOUtilities.unsetraw(self.normal_tty_settings)
                    print(
                        f"\x1b[2K\r{MOVE_AND_CLEAR_LINE * (self.lines_written - 1)}\rPaused: {name}\n{self.render_progress_bar()}\ncontrols: [s]kip, [r]eload presence, [p]lay, volume [u]p, volume [d]own\nvolume: {self.volume:.2f}\n\n\n\n\n\n",
                        end="",
                    )
                    IOUtilities.setraw()
                else:
                    if TYPE_CHECKING:
                        assert self.diff is not None
                    mixer.music.unpause()
                    self.queue_thread(self.update_share,youtube_id, mixer.music.get_pos() / 1000, False)
                    self.playing = True
                    self.update(name=name, start=self.get_start(), end=self.get_end())
            elif c == "u":
                self.volume += 0.01
                self.volume = min(1, self.volume)
                mixer.music.set_volume(self.volume)
            elif c == "d":
                self.volume -= 0.01
                self.volume = max(0, self.volume)
                mixer.music.set_volume(self.volume)
            # x1b for ESC
            if self.playing:
                IOUtilities.unsetraw(self.normal_tty_settings)
                if count % 1500 == 0:
                    self.update(name=name, start=self.get_start(), end=self.get_end())
                to_print = f"Now playing {name}\n{self.render_progress_bar()}\ncontrols: [s]kip, [r]eload presence, [p]ause, volume [u]p, volume [d]own\nvolume: {self.volume:.2f}\n\n\n\n\n\n"
                print(
                    f"\x1b[2K\r{MOVE_AND_CLEAR_LINE * (self.lines_written - 1)}{to_print}\r",
                    end="",
                )
                self.lines_written = sum(
                    map(
                        lambda k: self.ceil(
                            IOUtilities.term_length(k) / os.get_terminal_size().columns
                        ),
                        to_print.split("\n"),
                    )
                )
                IOUtilities.setraw()
            count += 1
            time.sleep(0.01)
        print(
            f"\x1b[2K\r{MOVE_AND_CLEAR_LINE * (self.lines_written - 1)}Now playing {name}\n{self.render_progress_bar()}\ncontrols: [s]kip, [r]eload presence, [p]ause, volume [u]p, volume [d]own\nvolume: {self.volume:.2f}\n\n\n\n\n\n",
        )

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

    def ceil(self, val):
        return int(math.ceil(val) if val % 1 != 0 else val + 1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        prog="Inflo",
        description="A lightweight music player",
    )

    parser.add_argument("first_song", nargs="?")
    parser.add_argument("--weights", required=False)
    parser.add_argument("--disable-discord", action="store_true")
    parser.add_argument("--disable-api", action="store_true")
    parser.add_argument("--enable-share", action="store_true")

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
        pres,
        args.first_song,
        weights_file=args.weights,
        disable_api=args.disable_api,
        enable_share=args.enable_share,
    )
    player.start()
