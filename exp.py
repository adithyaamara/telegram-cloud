from telethon.sync import TelegramClient, Message, events
import json
import os
import time

##################### Secrets ######################################
api_id = 'allnumbers'
api_hash = 'numbersandcharacters'
phone_number = '+919999999999'   # Pls include country code as well.
target_username = '@telegramusername'   # Messages go to saved messages.
#####################################################################

client = TelegramClient('session_name', api_id, api_hash)
client.connect()    # Connect to Telegram

# If not authorized, send code to the phone number
if not client.is_user_authorized():
    client.send_code_request(phone_number)
    client.sign_in(phone_number, input('Enter the Authorization code received from telegram app: '))

try:
    file_structure = json.load(open("files.json", 'r'))     # Load if present, create if not present.
except FileNotFoundError:
    file_structure = {}

def _upload_file(file_path: str, progress_callback=None):
    global file_structure
    if os.path.exists(file_path):
        file_name = os.path.basename(file_path)
    else:
        print(f"The file path is invalid: {file_path}")
        return False
    async def upload_async():
        def callback(current, total, start_time):
            if progress_callback:
                progress_callback(current, total, start_time)
        print(f"Attempting to upload file: {file_name}")
        start_time = time.time()
        message: Message = await client.send_file(target_username, file_path, progress_callback=lambda c, t: callback(c, t, start_time))  # Send the file and get the message object
        # file_id = message.media.document.id  # Get file, message id - Used for downloading the file.
        message_id = message.id
        file_structure[message_id] = {"path": file_path, "file_name": file_name}   # Each item is a dictionary with key being message_id.
        save_file_structure()
    client.loop.run_until_complete(upload_async())

def _download_file(message_id: int, progress_callback=None):
    global file_structure
    try:
        file_info = client.get_messages(target_username, ids=message_id)            # get message by id.
        file_to_restore = file_structure[str(message_id)]["path"]
        file_name = file_structure[str(message_id)]['file_name']
        if os.path.exists(file_to_restore):    # May be check size as well.
            print(f"File already exists in path: {file_name}")
            return True
        print(f"Attempting to download file: {file_name}")
        async def download_async():
            def callback(current, total, start_time):
                if progress_callback:
                    progress_callback(current, total, start_time)
            start_time = time.time()
            await client.download_media(file_info, file=file_to_restore, progress_callback=lambda c, t: callback(c, t, start_time))    # get file inside the message. Write to source path.
            print(f'File downloaded successfully from message_id : {message_id}!')
        client.loop.run_until_complete(download_async())
    except Exception as e:
        print(f'Error: {e}')

# Define a custom event for download progress
class DownloadProgressEvent(events.NewMessage):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.progress_callback = kwargs.get('progress_callback', None)

# Example progress callback functions
def upload_progress_callback(current: int, total: int, start_time: int):
    elapsed_time = int(time.time() - start_time)
    completion_pct = round((current/total)*100, 2)
    current_mb = int(current / 1048576)
    total_mb = int(total / 1048576)
    print(f"\rUpload Progress: {current_mb}/{total_mb} MegaBytes. Uploaded: {completion_pct}% . Elapsed Time: {elapsed_time} Seconds!", end="", flush=True)

def download_progress_callback(current, total, start_time: int):
    elapsed_time = int(time.time() - start_time)
    completion_pct = round((current/total)*100, 2)
    current_mb = int(current / 2048)
    total_mb = int(total / 2048)
    print(f"\rDownload Progress: {current_mb}/{total_mb} bytes. Downloaded: {completion_pct}% . Elapsed Time: {elapsed_time} Seconds!", end="", flush=True)

def save_file_structure():
    global file_structure
    json.dump(file_structure, open("files.json", 'w'), indent=4)    # save in-memory schema dictionary as file.

def is_file_backed_up(file_path: str):  # Time complexity.
    global file_structure
    for msg_id in file_structure:
        if file_structure[msg_id]["path"] == file_path: return True, msg_id
    return False, None    # not found.

def backup(folder_path: str):   # All subdirectories will be backed up.
    print(f"Attempting to backup the folder path: {folder_path}")
    for root, dirs, files in os.walk(folder_path):
        for file in files:
            file_path = os.path.join(root, file)    # This is where file is physically present in your system.
            if not is_file_backed_up(file_path)[0]:
                print(f"Attempting to upload file in path : {file_path}")
                _upload_file(file_path, progress_callback=upload_progress_callback)
            else:
                print(f"File already backed up! {file_path}")

def restore():      # restore doesn't need any path. Just tries to check file presence in source, writes if not present.
    global file_structure
    for msg_id in file_structure:
        _download_file(int(msg_id), progress_callback=download_progress_callback)

# backup("c:/Users/91984/Pictures/Screenshots")
# restore()

_upload_file("d:/English Movies/Telugu/Harry Potter Octalogy (2001 to 2011) Telugu Dub - 720p - Hx264 - MP3 - 6GB - ESub/3-Harry Potter 3 - The Prisoner of Azkaban(2004).mkv", progress_callback=upload_progress_callback)

# Disconnect the client
client.disconnect()
