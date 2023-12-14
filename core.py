from telegram import Bot, InputFile, error as telegram_error
from os import environ as env
from werkzeug import datastructures
from datetime import datetime
from pathvalidate import sanitize_filename, sanitize_filepath
from dotenv import load_dotenv
import time
from hurry.filesize import size
import logging
import json
load_dotenv()
logger = logging.getLogger()

class BotActions:
    def __init__(self) -> None:
        self.__bot_token = env["API_KEY"]         # Raises key error if not found.
        self.__channel_id = env["CHANNEL_ID"]     # Channel Id where files are uploaded.
        self.__bot = Bot(token=self.__bot_token)  # Bot for all file operations.
        self._schema_filename = 'schema.json'
        self._schema: dict[str, list[dict[str, str|int]] | dict[str, str|int]] = self.load_or_reload_schema()
        self.VALIDATION_ACTIVE = False
        self._default_upload_directory = "root"
        logger.info("Required config variables are read from env!")

    def load_or_reload_schema(self):
        try:
            with open(self._schema_filename, 'r') as schema_file:
                schema = json.load(schema_file)
                if "meta" not in schema:
                    schema["meta"] = {"total_size": "Unknown", "last_validated": "Please re-validate schema ASAP!"}
                return schema
        except (FileNotFoundError, json.decoder.JSONDecodeError):
            logger.info("Schema.json not found in local directory, creating new empty schema.")
            return {'root': [], "meta": {"total_size": 0, "last_validated": "Unavailable! Please Revalidate schema."}}

    def save_schema(self, file_content_bytes: bytes = None):
        try:
            with open(self._schema_filename, 'w') as schema_file:
                if file_content_bytes is not None:  # If file is specified explicitly as byte array.
                    self._schema = json.loads(file_content_bytes.decode('utf8'))    # load bytes as str and then to dictionary.
                json.dump(self._schema, schema_file, indent=4)    # save in-memory schema dictionary as file.
            logger.debug(f"Latest Schema dumped!!")
            return True, None
        except Exception as err:
            return False, err

    def validate_job(self):
        """Works on global object schema, start this function as a background thread. Finally put the last validation date in schema for future reference (Display last validation date in homepage also.)"""
        total_space_consumed = 0    # Aggregate size of all uploaded files.
        self.VALIDATION_ACTIVE = True    # disable all routes during update via a control flag variable.
        try:
            total_records = len(self._schema['root'])
            validated_records = 0
            for pos, file_info in enumerate(self._schema["root"]):
                try:
                    file_id = file_info["file_id"]
                except KeyError:
                    self._schema['root'].pop(pos)
                    logger.error(f"Ill-Formatted record found. File_ID missing. Dropping it.")
                    continue    # no need to proceed further on this file.
                try:
                    cloud_file = self.__bot.get_file(file_id=file_id)
                    total_space_consumed += cloud_file.file_size
                    logger.debug(f"No issues found with record, Ref Files ID: {file_id}")
                except telegram_error.BadRequest:
                    logger.info(f"The file no longer exists on cloud! Removing it from schema. Ref Id: {file_id}")
                    self._schema['root'].pop(pos)
                # self._schema['root'][pos]["filename"] = cloud_file.file_path.split('/')[-1]
                self._schema['root'][pos]["size"] = size(cloud_file.file_size)     # save in KB / MB string.
                validated_records += 1
                logger.debug(f"{validated_records} out of {total_records} validated!!")
                time.sleep(1)   # small delay to avoid DDOS scenario.

            self._schema["meta"] = {"total_size": size(total_space_consumed), "last_validated": datetime.utcnow().timestamp()}
            self.save_schema()   # dumps updated schema file.
            logger.info("Schema Validation completed successfully!!")
            self.VALIDATION_ACTIVE = False
        except Exception as err:
            self.VALIDATION_ACTIVE = False
            logger.error(f"Something went wrong during schema validation. Operation failed. Error: {err}")

    def is_validation_active(self):
        return self.VALIDATION_ACTIVE

    def upload_file(self, file: datastructures.FileStorage, file_name: str, update_schema: bool = True, directory: str = ""):
        try:
            file_name = sanitize_filename(file_name)
            if directory[0] == "/": directory = directory[1:]    # remove first / if present.
            full_path = sanitize_filepath(directory).split('/')
            if len(full_path) > 1 and "" in full_path:  # "".split(/) becomes [""]. This is the default. In case of default, write to first parent directory. Checking if some long path is given, and no empty spaces are there in path.
                return False, f"Invalid Filepath: {directory}, has empty spaces / illegal folder names!"
            response = self.__bot.send_document(filename=file_name, caption=file_name, chat_id=self.__channel_id, document=InputFile(file, filename=file_name))
            # message_id is used to delete the file later, document.file_id is used for downloading, Size is saved in raw bytes (useful for calculating total size used in telegram cloud).
            file_info = {'filename': file_name, 'message_id': response.message_id, 'file_id': response.document.file_id, "size": size(response.document.file_size)}
            if update_schema:   # True for most cases, except for uploading schema file itself to cloud for persistence.
                def helper_fnc(full_path: list, target: dict, file_info: dict):  # create all nested keys / sub directories into schema, if not present.
                    if len(full_path) > 0:
                        sub_dir = full_path.pop(0)
                        if sub_dir not in target.keys():
                            target[sub_dir] = {"root": []}
                        if len(full_path) == 0:
                            target[sub_dir]["root"].append(file_info)
                        helper_fnc(full_path, target[sub_dir], file_info)
                    return target
                if directory == "":     # Append to default root directory if unspecified.
                    self._schema["root"].append(file_info)
                else:
                    helper_fnc(full_path, self._schema, file_info)
            logger.debug(f"File uploaded to path '{directory}' successfully. Message ID: {response.message_id}")
            self.save_schema()
            return True, response.document.file_id
        except Exception as e:
            logger.error(f"Error uploading file: {e}")
            return False, str(e)

    def delete_file(self, message_id: int):
        try:    # BUG: Refactor this to support nested directories, new schema.
            res = self.__bot.delete_message(chat_id=self.__channel_id, message_id=message_id)   # deletion is not based on file id, but message_id.
            if res is True:
                for pos, file_info in enumerate(self._schema['root']):
                    if file_info['message_id'] == message_id:
                        self._schema['root'].pop(pos)   # Remove the file_info from the schema (if there) (based on message_id)
                        break   # look no further.
                self.save_schema()
                logger.debug(f"File with Message_ID: {message_id} deleted successfully!")
                return True
        except Exception as e:
            logger.error(f"Error deleting file: {e}")
            return False

    def download_file(self, file_id: str):
        try:
            file_pointer = self.__bot.get_file(file_id)
            file_content: bytes = file_pointer.download_as_bytearray()    # All the file data is in ram, not on local file storage.
            logger.debug(f"Attempting to send file with ID '{file_id}' to user!!")
            file_name = None
            for info in self._schema['root']:
                if info['file_id'] == file_id:
                    file_name = info["filename"]
                    break
            if file_name is not None:
                return file_content, file_name
            else:
                logger.error(f"Schema problem detected, file info not found for an ID.")
                return file_content, file_pointer.file_path.split('/')[-1]
        except Exception as e:
            logger.error(f"Error downloading the file: {e}")
            return False, e


class SchemaManipulations:
    """Offload schema manipulations from other classes, provide methods for easy schema manipulation"""
    def __init__(self) -> None:
        pass
