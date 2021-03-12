"""
cli.py

Sample CLI Clubhouse Client

RTC: For voice communication
"""

import os
import sys
import threading
import selectors
import configparser
import readline
from rich.table import Table
from rich.console import Console
from clubhouse.clubhouse import Clubhouse
from typing import Union, Optional
from queue import Queue

# Clubhouse.API_URL = "https://www.clubhouseapi.com/api"
# Clubhouse.API_URL = "http://localhost:8080/api"

# Set some global variables
try:
    import agorartc
    RTC = agorartc.createRtcEngineBridge()
    eventHandler = agorartc.RtcEngineEventHandlerBase()
    RTC.initEventHandler(eventHandler)
    # 0xFFFFFFFE will exclude Chinese servers from Agora's servers.
    RTC.initialize(Clubhouse.AGORA_KEY, None, agorartc.AREA_CODE_GLOB & 0xFFFFFFFE)
    # Enhance voice quality
    if RTC.setAudioProfile(
            agorartc.AUDIO_PROFILE_MUSIC_HIGH_QUALITY_STEREO,
            agorartc.AUDIO_SCENARIO_GAME_STREAMING
        ) < 0:
        print("[-] Failed to set the high quality audio profile")
    input_devices, err = RTC.createAudioRecordingDeviceManager()
    devcount = input_devices.getCount()
    print(f"there are {devcount} input devices")
    print(input_devices.getDevice(0, '', ''))

    output_devices, err = RTC.createAudioPlaybackDeviceManager()
    devcount = output_devices.getCount()
    print(output_devices.getDevice(0, '', ''))
    print(f"there are {devcount} output devices")
except ImportError as e:
    print("failed to import AgoraRtc", e)
    RTC = None

def set_interval(interval):
    """ (int) -> decorator

    set_interval decorator
    """
    def decorator(func):
        def wrap(*args, **kwargs):
            stopped = threading.Event()
            def loop():
                while not stopped.wait(interval):
                    ret = func(*args, **kwargs)
                    if not ret:
                        break
            thread = threading.Thread(target=loop)
            thread.daemon = True
            thread.start()
            return stopped
        return wrap
    return decorator

def write_config(user_id, user_token, user_device, filename='setting.ini'):
    """ (str, str, str, str) -> bool

    Write Config. return True on successful file write
    """
    config = configparser.ConfigParser()
    config["Account"] = {
        "user_device": user_device,
        "user_id": user_id,
        "user_token": user_token,
    }
    with open(filename, 'w') as config_file:
        config.write(config_file)
    return True

def read_config(filename='setting.ini'):
    """ (str) -> dict of str

    Read Config
    """
    config = configparser.ConfigParser()
    config.read(filename)
    if "Account" in config:
        return dict(config['Account'])
    return dict()

def process_onboarding(client):
    """ (Clubhouse) -> NoneType

    This is to process the initial setup for the first time user.
    """
    print("=" * 30)
    print("Welcome to Clubhouse!\n")
    print("The registration is not yet complete.")
    print("Finish the process by entering your legal name and your username.")
    print("WARNING: THIS FEATURE IS PURELY EXPERIMENTAL.")
    print("         YOU CAN GET BANNED FOR REGISTERING FROM THE CLI ACCOUNT.")
    print("=" * 30)

    while True:
        user_realname = input("[.] Enter your legal name (John Smith): ")
        user_username = input("[.] Enter your username (elonmusk1234): ")

        user_realname_split = user_realname.split(" ")

        if len(user_realname_split) != 2:
            print("[-] Please enter your legal name properly.")
            continue

        if not (user_realname_split[0].isalpha() and
                user_realname_split[1].isalpha()):
            print("[-] Your legal name is supposed to be written in alphabets only.")
            continue

        if len(user_username) > 16:
            print("[-] Your username exceeds above 16 characters.")
            continue

        if not user_username.isalnum():
            print("[-] Your username is supposed to be in alphanumerics only.")
            continue

        client.update_name(user_realname)
        result = client.update_username(user_username)
        if not result['success']:
            print(f"[-] You failed to update your username. ({result})")
            continue

        result = client.check_waitlist_status()
        if not result['success']:
            print("[-] Your registration failed.")
            print(f"    It's better to sign up from a real device. ({result})")
            continue

        print("[-] Registration Complete!")
        print("    Try registering by real device if this process pops again.")
        break

def print_channel_list(client, max_limit=20):
    """ (Clubhouse) -> NoneType

    Print list of channels
    """
    # Get channels and print out
    console = Console()
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("")
    table.add_column("channel_name", style="cyan", justify="right")
    table.add_column("topic")
    table.add_column("speaker_count")
    channels = client.get_channels()['channels']
    i = 0
    for channel in channels:
        i += 1
        if i > max_limit:
            break
        _option = ""
        _option += "\xEE\x85\x84" if channel['is_social_mode'] or channel['is_private'] else ""
        table.add_row(
            str(_option),
            str(channel['channel']),
            str(channel['topic']),
            str(int(channel['num_speakers'])),
        )
    print("")
    console.print(table)
    print("> ")

class Session:
    def __init__(self, client):
        super(Session, self).__init__()
        self.client = client
        self.max_limit = 20
        self.user_id = client.HEADERS.get("CH-UserID")
        self.hotkey_listener = None
        self.is_mute = False
        self.room = None
        self.room_switcher = Queue()
        self.room_shell = Queue()
        self.in_a_room = False

    def loop(self):
        print_channel_list(self.client)

        shell_thread = threading.Thread(target=lambda: self.shell())
        shell_thread.daemon = True
        shell_thread.start()

        def room_loop():
            while True:
                self.in_a_room = False
                channel_name = self.room_switcher.get()
                room = RoomSession(self.client, channel_name, self.room_shell)
                while True:
                    self.in_a_room = True
                    nxt = room.run()
                    if nxt is not None:
                        room = nxt
                        continue
                    break
        # room_thread = threading.Thread(target=room_loop)
        # room_thread.daemon = True
        # room_thread.start()
        room_loop()

    def outputs(self):
        devs, err = RTC.createAudioPlaybackDeviceManager()
        devcount = devs.getCount()
        for i in range(0, devcount):
            info = devs.getDevice(i, '', '')
            print(f"device[{i}]: {info[1]} = [{info[2]}]")
    def inputs(self):
        input_devices, err = RTC.createAudioRecordingDeviceManager()
        devcount = input_devices.getCount()
        for i in range(0, devcount):
            info = input_devices.getDevice(i, '', '')
            print(f"device[{i}]: {info[1]} = [{info[2]}]")
        print(f"current device: { input_devices.getCurrentDevice('50') }")
    def set_output(self, x):
        input_devices, err = RTC.createPlaybackDeviceManager()
        input_devices.setDevice(x)
    def set_input(self, x):
        input_devices, err = RTC.createAudioRecordingDeviceManager()
        print(f"setting to [{x}]")
        input_devices.setDevice(x)

    def shell(self):
        print("[*] Type \"leave\" to leave the conversation.")
        while True:
            inp = input("> ").strip().split()
            if len(inp) == 0:
                continue
            ev = None
            if inp[0] == "leave":
                self.room_shell.put(UIEvent(UIEventType.Leave, None))
            elif inp[0] == "hand-up":
                self.room_shell.put(UIEvent(UIEventType.RequestSpeaker, None))
            elif inp[0] == "rejoin":
                self.room_shell.put(UIEvent(UIEventType.Rejoin, None))
            elif inp[0] == "toggle-mute" or inp[0] == "m":
                self._toggle_mute()
            elif inp[0] == "outputs":
                self.outputs()
            elif inp[0] == "inputs":
                self.inputs()
            elif inp[0] == "set-output":
                if len(inp) == 2:
                    self.set_output(inp[1])
            elif inp[0] == "set-input":
                if len(inp) == 2:
                    self.set_input(inp[1])
            elif inp[0] == "update-photo":
                self.client.update_photo(inp[1])
            elif inp[0] == "refresh":
                self.room_shell.put(UIEvent(UIEventType.Refresh, None))
            elif inp[0] == "join":
                if len(inp) == 2:
                    if self.in_a_room:
                        self.room_shell.put(UIEvent(UIEventType.Leave, None))
                    self.room_switcher.put(inp[1])
                else:
                    print("syntax: join <channel name>")
            else:
                print("unknown command")
                continue

    def _toggle_mute(self):
        """ (str) -> bool

        Toggle microphone mute status.
        """
        # if self.room is None:
        #     return
        # if not self.room.channel_speaker_permission:
        #     print("[/] You aren't a speaker at the moment.")
        #     return

        if RTC:
            self.is_mute = not self.is_mute
            result = RTC.muteLocalAudioStream(self.is_mute)
            if result < 0:
                print("Failed to toggle mute status.")
                return
            if self.is_mute:
                print("[/] Microphone muted.")
            else:
                print("[/] Microphone enabled. You are broadcasting.")


from dataclasses import dataclass
from typing import Any
from enum import Enum
UIEventType = Enum("UIEventType", ["Leave", "ToggleMute", "RequestSpeaker", "Refresh", "Rejoin"])
@dataclass
class UIEvent:
    enum: UIEventType
    data: Any

def select(*queues):
    combined = Queue(maxsize=0)
    def listen_and_forward(queue):
        while True:
            combined.put((queue, queue.get()))
    threads = []
    for queue in queues:
        t = threading.Thread(target=listen_and_forward, args=(queue,))
        t.daemon = True
        t.start()
        threads.push(t)
    while True:
        yield combined.get()
    for t in threads:
        t.stop()

class RoomSession:
    """
    This is created when you join a room, and destroyed when you leave the room.
    """

    @classmethod
    def try_join(cls, client, channel_name) -> Optional['RoomSession']:
        """
        Returns a RoomSession if successful
        Returns None if unable to join
        """
        session = cls(client, channel_name)
        if not session.join():
            return None
        return session

    def __init__(self, client, channel_name, shell_events) -> None:
        super(RoomSession, self).__init__()
        self.client = client
        self.channel_name = channel_name
        self.user_id = client.HEADERS.get("CH-UserID")
        self.max_limit = 20
        self._ping_func = None
        self._wait_func = None
        self.channel_speaker_permission = False
        self.is_mute = False
        self.channel_info = None
        self.zombie = False
        self.shell_events = shell_events

    def run(self):
        if not self.join():
            return None
        self._print_users()

        while True:
            ev = self.shell_events.get()
            if ev.enum == UIEventType.Leave:
                break
            elif ev.enum == UIEventType.RequestSpeaker:
                self._request_speaker_permission()
            elif ev.enum == UIEventType.Refresh:
                self._print_users()
            elif ev.enum == UIEventType.Rejoin:
                return self.rejoin()
        self.leave()
        print(f"left room [{self.channel_name}]")
        return None

    def join(self) -> bool:
        self.channel_info = self.client.join_channel(self.channel_name)
        if not self.channel_info['success']:
            # Check if this channel_name was taken from the link
            self.channel_info = self.client.join_channel(self.channel_name, "link", "e30=")
            if not self.channel_info['success']:
                print(f"[-] Error while joining the channel ({self.channel_info['error_message']})")
                return False

        print(f"joined channel [{self.channel_name}]")

        for user in self.channel_info['users']:
            if user['user_id'] == int(self.user_id):
                self.channel_speaker_permission = bool(user['is_speaker'])
                break

        # Check for the voice level.
        if RTC:
            token = self.channel_info['token']
            print("running joinChannel")
            RTC.joinChannel(token, self.channel_name, "", int(self.user_id))
            print("ran joinChannel")
        else:
            print("[!] Agora SDK is not installed.")
            print("    You may not speak or listen to the conversation.")

        # Activate pinging
        self.client.active_ping(self.channel_name)
        self._ping_func = self._ping_keep_alive()
        self._wait_func = None

        return True

    def _refresh_info(self):
        _channel_info = self.client.get_channel(self.channel_name)
        if bool(_channel_info['success']):
            self.channel_info = _channel_info

    def _print_users(self):
        self._refresh_info()
        console = Console()
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("user_id", style="cyan", justify="right")
        table.add_column("username")
        table.add_column("name")
        table.add_column("is_speaker")
        table.add_column("is_moderator")
        users = self.channel_info['users']
        i = 0
        for user in users:
            i += 1
            if i > self.max_limit:
                break
            table.add_row(
                str(user['user_id']),
                str(user['name']),
                str(user['username']),
                str(user['is_speaker']),
                str(user['is_moderator']),
            )
            # Check if the user is the speaker
            if user['user_id'] == int(self.user_id):
                self.channel_speaker_permission = bool(user['is_speaker'])
        print("")
        console.print(table)

    def leave(self):
        # Safely leave the channel upon quitting the channel.
        if self.zombie:
            return
        if self._ping_func:
            self._ping_func.set()
        if self._wait_func:
            self._wait_func.set()
        if RTC:
            RTC.leaveChannel()
        # if self._listener:
        #     self.listener.stop()
        self.client.leave_channel(self.channel_name)
        self.zombie = True

    def rejoin(self) -> Optional['RoomSession']:
        self.leave()
        neu = RoomSession(self.client, self.channel_name, self.shell_events)
        if neu is not None:
            neu.channel_speaker_permission = self.channel_speaker_permission
        return neu

    def _request_speaker_permission(self):
        """ (str) -> bool

        Raise hands for permissions
        """
        if self.zombie:
            return
        if not self.channel_speaker_permission:
            self.client.audience_reply(self.channel_name, True, False)
            self._wait_func = self._wait_speaker_permission(self.user_id)
            print("[/] You've raised your hand. Wait for the moderator to give you the permission.")
        else:
            print("[/] You are already a speaker.")

    @set_interval(30)
    def _ping_keep_alive(self):
        """ (str) -> bool
        Continue to ping alive every 30 seconds.
        """
        self.client.active_ping(self.channel_name)
        return True

    @set_interval(10)
    def _wait_speaker_permission(self, user_id):
        """ (str) -> bool
        Function that runs when you've requested for a voice permission.
        """
        # Get some random users from the channel.
        _channel_info = self.client.get_channel(self.channel_name)
        if _channel_info['success']:
            for _user in _channel_info['users']:
                if _user['user_id'] != user_id:
                    user_id = _user['user_id']
                    break
            # Check if the moderator allowed your request.
            res_inv = self.client.accept_speaker_invite(self.channel_name, user_id)
            if res_inv['success']:
                print("[-] Now you have a speaker permission.")
                print("    Please re-join this channel to activate a permission.")
                self.shell_events.put(UIEvent(UIEventType.Rejoin, None))
                return False
        return True


def chat_main(client):
    """ (Clubhouse) -> NoneType
    Main function for chat
    """

    # import pdb; pdb.set_trace()
    session = Session(client)
    session.loop()

def user_authentication(client):
    """ (Clubhouse) -> NoneType

    Just for authenticating the user.
    """

    result = None
    while True:
        user_phone_number = input("[.] Please enter your phone number. (+818043217654) > ")
        result = client.start_phone_number_auth(user_phone_number)
        if not result['success']:
            print(f"[-] Error occured during authentication. ({result['error_message']})")
            continue
        break

    result = None
    while True:
        verification_code = input("[.] Please enter the SMS verification code (1234, 0000, ...) > ")
        result = client.complete_phone_number_auth(user_phone_number, verification_code)
        if not result['success']:
            print(f"[-] Error occured during authentication. ({result['error_message']})")
            continue
        break

    user_id = result['user_profile']['user_id']
    user_token = result['auth_token']
    user_device = client.HEADERS.get("CH-DeviceId")
    write_config(user_id, user_token, user_device)

    print("[.] Writing configuration file complete.")

    if result['is_waitlisted']:
        print("[!] You're still on the waitlist. Find your friends to get yourself in.")
        return

    # Authenticate user first and start doing something
    client = Clubhouse(
        user_id=user_id,
        user_token=user_token,
        user_device=user_device
    )
    if result['is_onboarding']:
        process_onboarding(client)

    return

def main():
    """
    Initialize required configurations, start with some basic stuff.
    """
    # Initialize configuration
    client = None
    user_config = read_config()
    user_id = user_config.get('user_id')
    user_token = user_config.get('user_token')
    user_device = user_config.get('user_device')

    # Check if user is authenticated
    if user_id and user_token and user_device:
        client = Clubhouse(
            user_id=user_id,
            user_token=user_token,
            user_device=user_device
        )

        # # Check if user is still on the waitlist
        # _check = client.check_waitlist_status()
        # if _check['is_waitlisted']:
        #     print("[!] You're still on the waitlist. Find your friends to get yourself in.")
        #     return

        # Check if user has not signed up yet.
        _check = client.me()
        if not _check['user_profile'].get("username"):
            process_onboarding(client)

        chat_main(client)
    else:
        client = Clubhouse()
        user_authentication(client)
        main()

# from pubnub.callbacks import SubscribeCallback
# from pubnub.enums import PNStatusCategory, PNOperationType
# from pubnub.pnconfiguration import PNConfiguration
# from pubnub.pubnub import PubNub
# pnconfig = PNConfiguration()
# pnconfig.publish_key = Clubhouse.PUBNUB_PUB_KEY
# pnconfig.subscribe_key = Clubhouse.PUBNUB_SUB_KEY
# pnconfig.uuid = 'myUniqueUUID'
# PUBNUB_ROOM = PubNub(pnconfig)


def my_publish_callback(envelope, status):
    # Check whether request successfully completed or not
    if not status.is_error():
        pass  # Message successfully published to specified channel.
    else:
        pass  # Handle message publish error. Check 'category' property to find out possible issue
              # because of which request did fail.
              # Request can be resent using: [status retry];

class RoomSubscribeCallback:
# class RoomSubscribeCallback(SubscribeCallback):
    def presence(self, pubnub, presence):
        print(presence)

    def status(self, pubnub, status):
        if status.category == PNStatusCategory.PNUnexpectedDisconnectCategory:
            pass  # This event happens when radio / connectivity is lost

        elif status.category == PNStatusCategory.PNConnectedCategory:
            # Connect event. You can do stuff like publish, and know you'll get it.
            # Or just use the connected event to confirm you are subscribed for
            # UI / internal notifications, etc
            pubnub.publish().channel('my_channel').message('Hello world!').pn_async(my_publish_callback)
        elif status.category == PNStatusCategory.PNReconnectedCategory:
            pass
            # Happens as part of our regular operation. This event happens when
            # radio / connectivity is lost, then regained.
        elif status.category == PNStatusCategory.PNDecryptionErrorCategory:
            pass
            # Handle message decryption error. Probably client configured to
            # encrypt messages and on live data feed it received plain text.

    def message(self, pubnub, message):
        # Handle new message stored in message.message
        print(message.message)

# PUBNUB_ROOM.add_listener(RoomSubscribeCallback())

class RoomPubNub:
    def __init__(self, client):
        super(RoomPubNub, self).__init__()
        pubnub.subscribe().channels('my_channel').execute()
        pass

if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Remove dump files on exit.
        file_list = os.listdir(".")
        for _file in file_list:
            if _file.endswith(".dmp"):
                os.remove(_file)
