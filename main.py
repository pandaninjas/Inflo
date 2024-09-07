import functools
import os, time, pypresence, random, sys, subprocess, threading, json, argparse, atexit, re, requests, requests_cache, math, unicodedata, contextlib, bisect
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
        string = ANSI_REGEX.sub("", string).replace("\n", "")
        length = 0
        for char in string:
            length += 2 if unicodedata.east_asian_width(char) in ["W", "F"] else 1
        return length

    @staticmethod
    @functools.cache
    def process_name(name: str) -> "list[str]":
        length = IOUtilities.term_length(name)
        if length < 60:
            cur_len, idx = 0, 0
            cur = ""
            while cur_len < length / 2:
                cur += name[idx]
                cur_len += IOUtilities.term_length(name[idx])
                idx += 1
            return [cur, name[idx:]]
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

    @staticmethod
    @functools.cache
    def normalize(text: str) -> str:
        return unicodedata.normalize("NFC", text)

    @staticmethod
    def getch():
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

    @staticmethod
    def get_length(music: str) -> float:
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


class MusicPlayer:
    presence: "pypresence.Presence | None"
    normal_tty_settings: "list[Any]" = None
    diff: "tuple[float, float] | None"
    playing: "bool"
    presence_update_lock: "threading.Lock"
    weights_file: "str"
    length: "float"
    volume: "float"
    queue: "list[str]"
    lines_written: "list[str] | None"

    def __init__(
        self,
        presence: "pypresence.Presence | None",
        initial: "str | None",
        weights_file: "str",
        disable_api: "bool",
        enable_share: "bool",
    ):
        self.presence = presence
        self.disable_api = disable_api
        self.weights_file = weights_file
        self.queue = [initial] if initial is not None else []
        self.enable_share = enable_share

    def start(self) -> None:
        requests_cache.install_cache("inflo_cache", backend="memory", expire_after=3600)
        self.queue_content = ""
        self.auto = ""
        self.is_queueing = False
        self.lines_written = None
        self.presence_update_lock = threading.Lock()
        self.volume = 1.0
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
        self.run()

    def run(self):
        while True:
            if len(self.queue) != 0:
                self.play(self.queue[0])
                self.queue.pop(0)
            else:
                keys, weights = IOUtilities.generate_weights(self.weights_file)
                self.play(random.choices(keys, weights)[0])

    def update(self, *args, **kwargs):
        with contextlib.redirect_stderr(None), contextlib.redirect_stderr(
            None
        ), self.presence_update_lock:
            if self.presence is not None:
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
                        buttons.append(
                            {
                                "label": "Join",
                                "url": f"{INFLO_SHARE_URL}{self.share_id}",
                            }
                        )
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
                        if isinstance(e, pypresence.PipeClosed):
                            self.queue_thread(self.reload_presence)
                            return
                        try:
                            self.presence.close()
                        except Exception:
                            pass
                        self.presence = None

    def reload_presence(self):
        with contextlib.redirect_stderr(None), contextlib.redirect_stderr(None):
            try:
                self.presence.close()
            except Exception:
                pass
            try:
                self.presence = pypresence.Presence("1033827079994753064")
                self.presence.connect()
            except Exception:
                pass

    def render_progress_bar(self) -> str:
        start = self.get_start()
        end = self.get_end()
        cur_time = time.time()
        mins_start, secs_start = divmod(cur_time - start, 60)
        mins_end, secs_end = divmod(end - cur_time, 60)
        left_timer = f"{int(mins_start)}:{int(secs_start):02d} "
        right_timer = f" -{int(mins_end)}:{int(secs_end):02d}"
        bar_width = os.get_terminal_size().columns - len(left_timer) - len(right_timer)
        left_bar_width = int(min((cur_time - start) / (end - start), 1) * bar_width)
        right_bar_width = bar_width - left_bar_width
        return f"{left_timer}\x1b[32m{left_bar_width * '━'}\x1b[0m{right_bar_width * '━'}{right_timer}"

    def update_share(self, youtube_id: str, progress: float, playing: bool):
        if not self.enable_share:
            return
        try:
            r = requests.put(
                INFLO_SHARE_URL + "update/" + self.secret,
                json={"playing": playing, "id": youtube_id, "progress": progress},
            ).json()
            if r["status"] == "fail":
                share = requests.post(INFLO_SHARE_URL + "start").json()
                self.secret: str = share["secret"]
                self.share_id: str = share["id"]
        except Exception:
            return

    def get_start(self):
        return time.time() - (mixer.music.get_pos() / 1000)

    def get_end(self):
        return time.time() + self.length - (mixer.music.get_pos() / 1000)

    def queue_thread(self, *args):
        threading.Thread(target=args[0], args=args[1:]).start()

    def autocomplete(self):
        if not self.auto:
            self.auto = self.queue_content

        files = sorted(
            filter(
                lambda file: file.startswith(self.auto) and file.endswith(".mp3"),
                os.listdir("."),
            )
        )
        if len(files) == 0:
            return
        if self.auto != "":
            # get next autocomplete
            idx = bisect.bisect(files, self.auto) % len(files)
            self.queue_content = files[idx]
        else:
            self.queue_content = files[0]

    def play(self, song: str) -> None:
        name = song.replace(".mp3", "").strip()
        self.length = IOUtilities.get_length(song)
        self.playing = True
        self.update(name=name, start=time.time(), end=time.time() + self.length)
        youtube_id = YOUTUBE_DL_ID_REGEX.search(name).group(0).strip("[]")
        self.queue_thread(self.update_share, youtube_id, 0, True)
        count = 0
        mixer.music.load(song)
        mixer.music.play()
        while mixer.music.get_busy() or not self.playing:
            c = IOUtilities.getch()
            if self.is_queueing:
                if c == "\x1b":  # escape key
                    self.is_queueing = False
                    self.queue_content = ""
                    self.auto = ""
                elif c == "\x08":  # backspace
                    self.queue_content = self.queue_content[:-1]
                    self.auto = ""
                elif c == "\t":  # tab
                    self.autocomplete()
                elif c == "\r":
                    self.queue.append(
                        next(
                            filter(
                                lambda file: file.startswith(self.queue_content)
                                and file.endswith(".mp3"),
                                os.listdir("."),
                            )
                        )
                    )
                    self.auto = ""
                    self.is_queueing = False
                    self.queue_content = ""
                else:
                    self.queue_content += c
                    self.auto = ""
            else:
                if c == "s":
                    print()
                    return
                elif c == "r":
                    with self.presence_update_lock:
                        self.queue_thread(self.reload_presence)
                    if self.playing:
                        self.update(
                            name=name, start=self.get_start(), end=self.get_end()
                        )
                    else:
                        self.update(
                            name="Paused: " + name,
                            start=time.time(),
                        )
                elif c == "p":
                    if self.playing:
                        self.queue_thread(
                            self.update_share,
                            youtube_id,
                            mixer.music.get_pos() / 1000,
                            False,
                        )
                        mixer.music.pause()
                        self.playing = False
                        if self.presence is not None:
                            self.update(
                                name="Paused: " + name,
                                start=time.time(),
                            )
                    else:
                        mixer.music.unpause()
                        self.queue_thread(
                            self.update_share,
                            youtube_id,
                            mixer.music.get_pos() / 1000,
                            True,
                        )
                        self.playing = True
                        self.update(
                            name=name, start=self.get_start(), end=self.get_end()
                        )
                elif c == "u":
                    self.volume += 0.01
                    self.volume = min(1, self.volume)
                    mixer.music.set_volume(self.volume)
                elif c == "d":
                    self.volume -= 0.01
                    self.volume = max(0, self.volume)
                    mixer.music.set_volume(self.volume)
                elif c == "q":
                    self.is_queueing = True
                # x1b for ESC
            controls = (
                "controls: [s]kip, [r]eload presence, [p]ause, volume [u]p, volume [d]own, [q]ueue mode"
                if not self.is_queueing
                else "enter to submit, tab to autocomplete, esc to leave"
            )
            if self.playing:
                IOUtilities.unsetraw(self.normal_tty_settings)
                if count % 1500 == 0:
                    self.update(name=name, start=self.get_start(), end=self.get_end())
                to_print = f"Now playing {IOUtilities.normalize(name)}\n{self.render_progress_bar()}\n{controls}\nvolume: {self.volume:.2f}\n{self.queue_content}"
                print(
                    f"\x1b[2K\r{MOVE_AND_CLEAR_LINE * (self.calculate_lines_written() - 1)}{to_print}\r",
                    end="",
                )
                self.lines_written = to_print.split("\n")
                IOUtilities.setraw()
            else:
                IOUtilities.unsetraw(self.normal_tty_settings)
                to_print = f"\rPaused: {IOUtilities.normalize(name)}\n{self.render_progress_bar()}\n{controls}\nvolume: {self.volume:.2f}\n{self.queue_content}"
                print(
                    f"\x1b[2K\r{MOVE_AND_CLEAR_LINE * (self.calculate_lines_written() - 1)}{IOUtilities.normalize(to_print)}\r",
                    end="",
                )
                self.lines_written = to_print.split("\n")
                IOUtilities.setraw()
            count += 1
            time.sleep(0.01)
        print()

    def calculate_lines_written(self) -> int:
        if self.lines_written == None:
            return 3
        return sum(
            map(
                lambda k: self.ceil(
                    IOUtilities.term_length(k) / os.get_terminal_size().columns
                ),
                self.lines_written,
            )
        )

    def ceil(self, val: int):
        return math.ceil(val) if val > 0 else 1


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

    print("\n\x1b[?25l")
    atexit.register(print, "\x1b[?25h", end="")

    player = MusicPlayer(
        pres,
        args.first_song,
        weights_file=args.weights,
        disable_api=args.disable_api,
        enable_share=args.enable_share,
    )
    try:
        player.start()
    except KeyboardInterrupt:
        sys.exit(0)
