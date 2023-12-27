from telegram import Bot, InputFile, error as telegram_error # InputMediaDocument - Used for editing media in a message id.
from os import environ as env
from werkzeug import datastructures
from datetime import datetime
from pathvalidate import sanitize_filename, sanitize_filepath
from dotenv import load_dotenv
import time
from hurry.filesize import size
import logging
import json
## file enc / dec
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.fernet import Fernet
import base64
####
load_dotenv()
logger = logging.getLogger()

class BotActions:
    def __init__(self, schema_filepath=None, encrypted: bool=True) -> None:
        self.__bot_token = str(env["API_KEY"])         # Raises key error if not found.
        self.__channel_id = str(env["CHANNEL_ID"])     # Channel Id where files are uploaded.
        self.__bot = Bot(token=self.__bot_token)  # Bot for all file operations.
        self._is_encryption_enabled = encrypted
        if self._is_encryption_enabled:  # Below helper id needed only when encryption is enabled by user.
            logger.info("File Encryption is enabled for this session! All uploads done in this session will be encrypted uploads.")
            self.__file_ops = EncDecHelper(self.__bot_token + self.__channel_id)    # bot token + channel id combined as a string is used as base encryption key.
        if schema_filepath is None:  # If none, use default, else use user-defined path. This will be used for doing multiple backups using cli. Or for testing purposes.
            self._schema_filepath = './schema/schema.json'   # This folder must be pointed to a named volume for schema persistence.
        self._schema: dict[str, list[dict[str, str|int]] | dict[str, str|int]] = self.load_or_reload_schema()
        self.save_schema()  # SAVE SCHEMA ONCE At start
        self._ops = SchemaManipulations()
        self.VALIDATION_ACTIVE = False
        self._default_upload_directory = ""
        logger.info("Required config variables are read from env!")

    def load_or_reload_schema(self):
        try:
            with open(self._schema_filepath, 'r') as schema_file:
                schema = json.load(schema_file)
                if "meta" not in schema:
                    schema["meta"] = {"total_size": "Unknown", "last_validated": "Please re-validate schema ASAP!"}
                return schema
        except (FileNotFoundError, json.decoder.JSONDecodeError):
            logger.info("Schema.json not found in local directory, creating new empty schema.")
            return {'root': [], "meta": {"total_size": 0, "last_validated": "Unavailable! Please Revalidate schema."}}

    def save_schema(self, file_content_bytes: bytes = None):
        try:
            with open(self._schema_filepath, 'w') as schema_file:
                if file_content_bytes is not None:  # If file is specified explicitly as byte array.
                    self._schema = json.loads(file_content_bytes.decode('utf8'))    # load bytes as str and then to dictionary.
                json.dump(self._schema, schema_file, indent=4)    # save in-memory schema dictionary as file.
            logger.debug(f"Latest Schema dumped!!")
            return True, None
        except Exception as err:
            return False, err

    def validate_job(self):   # Needs refactoring as schema changed.
        """Works on schema, start this function as a background thread. Finally put the last validation date in schema for future reference (Display last validation date in homepage also.)"""
        self.VALIDATION_ACTIVE = True    # disable all routes during update via a control flag variable.
        try:
            meta = {"total_size": 0, "last_validated": ""}
            def process_schema(schema, meta):
                if isinstance(schema, dict):
                    for key, val in schema.items():
                        if key == "root" and isinstance(val, list):
                            file_validate(val, meta)  # Update the 'root' list in-place
                        else:
                            process_schema(val, meta)
                return schema, meta

            def file_validate(file_list: list[dict], meta: dict):
                for pos, file_info in enumerate(file_list.copy()):
                    try:
                        file_id = file_info["file_id"]
                        message_id = file_info["message_id"]
                    except KeyError:
                        file_list.remove(file_info)
                        logger.error(f"Ill-Formatted record found. File_ID missing. Dropping it.")
                        continue    # no need to proceed further on this file.
                    try:
                        cloud_file = self.__bot.get_file(file_id=file_id)
                        logger.debug(f"File is present in cloud, Ref Files ID: {file_id}")
                    except (telegram_error.BadRequest, telegram_error.TelegramError):
                        logger.info(f"The file no longer exists on cloud! Removing it from schema. Ref Id: {file_id}")
                        file_list.remove(file_info)
                        continue
                    try:
                        underlying_message = self.__bot.copy_message(from_chat_id=self.__channel_id, chat_id="", message_id=message_id)    # not specifying to chat_id. As we are using this method to just check if message exists or not.
                    except telegram_error.TelegramError as err:
                        if "Message to copy not found" in str(err):
                            logger.info(f"Underlying message for a file with message id '{message_id}' is deleted. SO deleting file record from schema!!")
                            file_list.remove(file_info)
                            continue
                    meta["total_size"] += cloud_file.file_size
                    file_list[pos]["size"] = size(cloud_file.file_size)     # save in KB / MB string.
                    time.sleep(1)   # small delay to avoid DDOS scenario.

            process_schema(self._schema, meta)
            self._schema["meta"]["last_validated"] = str(datetime.utcnow())
            self._schema["meta"]["total_size"] = size(meta["total_size"])
            self.save_schema()
            logger.info("Schema Validation completed successfully!!")
            self.VALIDATION_ACTIVE = False
        except Exception as err:
            self.VALIDATION_ACTIVE = False
            logger.error(f"Something went wrong during schema validation. Operation failed. Error: {err}")

    def is_validation_active(self) -> bool:
        return self.VALIDATION_ACTIVE

    def get_active_users_in_channel(self):
        """Get Number of users are currently added to channel. For best security only you and bot (total 2) must be the members present in the private channel."""
        error = None
        chat_member_count = self.__bot.get_chat_members_count(self.__channel_id)     # Get number of users added to the channel.
        if chat_member_count > 2:
            error = f"[Security Breach] -> Number of users in channel is more than two: '{chat_member_count}' !! Please go to telegram app, manually remove everyone except the bot. Otherwise they may have access to any un-encrypted files in the channel!!"
            logger.warning(error)
        return chat_member_count, error

    def upload_file(self, file: datastructures.FileStorage, file_name: str, update_schema: bool = True, directory: str = ""):
        try:
            file_name = sanitize_filename(file_name)
            res, err = self._ops.get_sanitized_file_path(directory)  # sanity check
            if res is False:
                return False, err   # return the error to caller.
            if self._is_encryption_enabled:
                logger.info(f"Attempting to encrypt the file '{file_name}' before upload!")
                file = self.__file_ops.get_encrypted_data_binary(file.read())   # Upload encrypted file if encryption is enabled.
            response = self.__bot.send_document(filename=file_name, caption=file_name, chat_id=self.__channel_id, document=InputFile(file, filename=file_name))   # Encrypted upload.
            # message_id is used to delete the file later, document.file_id is used for downloading, Size is saved in raw bytes (useful for calculating total size used in telegram cloud).
            file_info = {'filename': file_name, 'message_id': response.message_id, 'file_id': response.document.file_id, "size": size(response.document.file_size), "is_encrypted": self._is_encryption_enabled}
            if update_schema:   # True for most cases, except for uploading schema file itself to cloud for persistence.
                if directory == "":     # Append to default root directory if unspecified.
                    self._schema["root"].append(file_info)
                else:
                    modified_schema, err = self._ops.manipulate_schema(directory, file_info, self._schema.copy(), False)
                    if modified_schema is False:
                        logger.error(f"File uploaded, but unable to add it to schema, Error: {err}")
                        return False, err
                    self._schema = modified_schema.copy()
            logger.debug(f"File uploaded to path '{directory}' successfully. Message ID: {response.message_id}")
            self.save_schema()
            return True, response.document.file_id
        except Exception as e:
            logger.error(f"Error uploading file: {e}")
            return False, str(e)

    def delete_file(self, full_path: str, message_id: int, with_out_schema_change: bool = False):
        """Delete a file based in `message_id` and pop it's corresponding record from schema.\n
           If `with_out_schema_change=True`, `full_path` is ignored, just delete is performed.
        """
        try:
            try:
                res = self.__bot.delete_message(chat_id=self.__channel_id, message_id=message_id)   # deletion is not based on file id, but message_id.
            except telegram_error.TelegramError as err:
                if "Message to delete not found" in str(err):
                    res = True  # Message is already deleted from telegram, so we can proceed to delete it from schema as well.. Any other error, we don't remove from schema.
            if res is True:
                if with_out_schema_change is True:
                    return True, ""  # return without schema change if arg is specified.
                modified_schema, err = self._ops.manipulate_schema(full_path, {"message_id": int(message_id)}, self._schema.copy(), delete=True)
                if modified_schema is False:
                    return False, err
                self._schema = modified_schema.copy()
                self.save_schema()
                logger.debug(f"File with Message_ID: {message_id} deleted successfully!")
                return True, None
        except Exception as e:
            logger.error(f"Error deleting file: {e}")
            return False, e

    def move_folder(self, folder_to_move: str, target_folder: str, new_name_for_moved_folder: str=None):
        # we want to get sub schema starting from folder path. So we can paste it in new path.
        folder_name, sub_schema, err = self._ops.get_contents_in_directory(folder_to_move, self._schema.copy(), False)  # folder_name - The name of the folder that is being moved, where as folder_to_move is full path to folder. folder_name is final word of folder_to_move.
        if new_name_for_moved_folder is not None:
            folder_name = new_name_for_moved_folder     # Use name specified by user.
        logger.info(f"The folder '{folder_name}' in path {folder_to_move} is requested to be moved to new path '{target_folder}'")
        if sub_schema in [False, None]:  # Schema manipulation functions doesn't return False when crash exited, it will be None.
            return False, err
        # Delete the folder(that is being moved) from schema , from old path. Later we can add the same in new path. [This way even if folder_to_move, target_folder are given same also, we are not loosing actual anything. This most harmless way]
        modified_schema_after_folder_deletion, err = self._ops.manipulate_schema(folder_to_move, None, self._schema.copy().copy(), delete=True)  # deleting original folder path from schema.
        if modified_schema_after_folder_deletion in [False, None]:
            return False, err
        logger.info("Substitution success!")
        # Substitute the schema in new path after deleting original from schema. [If you substitute first and delete later --> There is a risk of directory structure loss if folder to move and target folder are same]
        modified_schema_after_substitution, err = self._ops.manipulate_schema(target_folder, sub_schema, modified_schema_after_folder_deletion, delete=False, add_folder=True, folder_name=folder_name)  # substituting sub_schema in original schema, with specific folder name at said target_folder path.
        if modified_schema_after_substitution in [False, None]:
            return False, err
        logger.info("delete of original path success!")
        self._schema = modified_schema_after_substitution.copy()   # This modified schema is after deleting the specified folder in original schema, moving it to new path.
        self.save_schema()
        return True, ""

    def delete_folder(self, folder_path: str):
        try:    # Pop folder path from schema, delete files one by one, ignore deletion errors.
            _, sub_schema, err = self._ops.get_contents_in_directory(folder_path, self._schema.copy(), False)  # we want to get sub schema starting from folder path.
            if sub_schema is False:
                return False, err
            file_list, err = self._ops.get_file_list_in_a_directory(sub_schema)     # get list of files in this sub schema.
            if file_list is False:
                return False, err
            logger.info(f"Received {len(file_list)} files for deletion under path: {str(folder_path)}!!")
            modified_schema, err = self._ops.manipulate_schema(folder_path, None, self._schema.copy(), delete=True)
            if modified_schema is False:
                return False, err
            for file_info in file_list:
                logger.info(f"Attempting to delete file: {file_info['filename']}")
                res = True
                res, err = self.delete_file(full_path=None, message_id=file_info["message_id"], with_out_schema_change=True)   # As with_out_schema_change is True, full path is ignored and just delete is attempted.
                if res is False:
                    logger.error(f"Failed to delete file {file_info['filename']} during folder deletion. Ignoring that, proceed to next file anyway.")  # If failed, file may still be in telegram, but won't show up in our schema / UI at-least.  # Bulk delete may cause flood control error.
            if len(file_list) == 0:
                logger.debug(f"Received folder deletion request, but there are no files inside specified folder path {folder_path}!!")
            self._schema = modified_schema.copy()   # This modified schema is after deleting the specified folder in original schema.
            self.save_schema()
            return True, ""
        except Exception as err:
            return False, err

    def download_file(self, file_id: str, is_encrypted: bool=None):   # Specify if file has to be decrypted before returning. Taken for granted if supplied, else will read schema to determine if a file was encrypted during upload. [Option for users using CLI.]
        """Fetch file from telegram using `file_id`, return the file as binary (with / without decrypting). \n
           `is_encrypted` is optional, if supplied, decrypts the file before returning (Doesn't matter if the file was encrypted during upload or not ;)\n
           if `is_encrypted` argument is not specified, checks the file record from schema to see if `is_encrypted` flag is set, act accordingly. If that was also not set, send without decryption.
        """
        try:
            file_pointer = self.__bot.get_file(file_id)
            file_content: bytes = file_pointer.download_as_bytearray()    # All the file data is in ram, not on local file storage.
            file_name = file_pointer.file_path.split('/')[-1]   # fetch file name from response. Mostly this is wrong name. Fetch from schema if that's an option.
            if is_encrypted is None:    # Arg not specified, try to read from schema.
                logger.debug(f"`is_encrypted` was not specified for a file download operation! Determining from schema.")
                file_record = self._ops.find_record_by_attribute(self._schema.copy(), "file_id", file_id)  # find the file record from schema for this file_id. From that we can know if file was initially encrypted or not.
                if file_record is not None and len(file_record) > 0:
                    file_record = file_record[0]    # If search by file_id returned multiple records, pick first one. Happens only if schema is manually tampered.
                    is_encrypted = file_record.get("is_encrypted", False)   # is_encrypted is set during file upload based on if user decided to use encryption or not. If flag is not set in record, assume that a file is not encrypted by default.(Backward compatibility)
                    file_name = file_record.get("filename", file_name)  # use filename from schema if available.
                else:   # if file record itself is not found. Assume no encryption.
                    logger.debug(f"No records was found in schema for file_id: '{file_id}'. Sending file without decryption!")
                    is_encrypted = False
            if is_encrypted:
                logger.debug(f"Attempting to decrypt the file with ID '{file_id}'!")
                file_content = self.__file_ops.get_decrypted_data_binary(file_content)  # decrypt before sending binary.
            logger.debug(f"Attempting to send file with ID '{file_id}' to user!!")
            return file_content, file_name
        except Exception as e:
            logger.error(f"Error downloading the file: {e}")
            return False, e


class SchemaManipulations:
    """Offload schema manipulations from other classes, provide methods for easy schema manipulation"""

    def get_sanitized_file_path(self, full_path: str) -> list[str]:
        disallowed_dir_names = ["root", "", " ", "meta", "/", "\\"]    # meta, root are reserved keywords for our schema.
        if full_path == "":     # callers should handle this as root directory.
            return full_path, ""
        if full_path[0] == "/": full_path = full_path[1:]    # remove first '/' if present.
        if full_path[-1] == "/": full_path = full_path[:-1]    # remove last '/' if present.
        full_path: list = sanitize_filepath(full_path).split('/')
        if len(full_path) > 1 and "" in full_path:  # "".split(/) becomes [""]. This is the default. In case of default, write to first parent directory. Checking if some long path is given, and no empty spaces are there in path.
            logger.error(f"Invalid Path Supplied, Unable to sanitize: {full_path}")
            return False, f"Invalid Filepath: {full_path}, has empty spaces / illegal folder names!"
        if any(sub_dir in disallowed_dir_names for sub_dir in full_path):
            return False, f"Path {full_path} contains invalid sub directory names. Not allowed: {disallowed_dir_names}"
        return full_path, ""

    def get_contents_in_directory(self, directory: str, ret_structure: dict, files_only: bool=False) -> dict | list:
        """Returns the dictionary item by navigating to the given directory (nested)."""
        full_path, err = self.get_sanitized_file_path(directory)  # get sanitized file path from a directory string.
        if full_path is False:  # Invalid path.
            return False, False, err   # return error.
        sub_dir = ""    # avoid unbound local error in some cases.
        for sub_dir in full_path:
            if sub_dir not in ret_structure:
                return False, False, f"Invalid Path - {directory}!!"
            ret_structure = ret_structure[sub_dir]
        if files_only:
            return sub_dir, ret_structure["root"], ""    # no error. Just return files.
        else:
            try:
                ret_structure.pop("meta")   # reserved folder. Not to be displayed to user.
            except KeyError:
                pass
            return sub_dir, ret_structure, ""    # no error. Return final sub_dir in path + files, folders inside given directory.

    def manipulate_schema(self, full_path: str, file_info: dict, schema: dict, delete: bool, add_folder: bool=False, folder_name=None):   # This function needs some severe refactoring.
        """iteratively creates / navigates a nested directory structure in schema, adds the given file_info dict to the nested path, attempts to delete the same from schema if del is set to True. returns updated schema.\n
           1. Ex: self.manipulate_schema("some/valid/path/in_schema", None, full_schema_or_sub_schema_as_dict, True) --> This will delete the specified full_path from specified schema, returns updated schema. Deletes all the sub_directories, files inside specified path completely.\n
           2. Ex: self.manipulate_schema("some/valid/path/in_schema", {"message_id": 123}, full_schema_or_sub_schema_as_dict, True)  --> This will delete the specified file_info single record from specified schema under full_path, returns updated schema.\n
           3. Ex: self.manipulate_schema("some/valid/path/in_schema", {"message_id": 123}, full_schema_or_sub_schema_as_dict, False)  --> This will Add the specified file_info single record to specified schema under full_path, returns updated schema.
           4. self.manipulate_schema("some/valid/path/in_schema", {"root": [], "folder2": {"root": [{"message_id": 123}]}}, full_schema_or_sub_schema_as_dict, False, True, "newFolder5") --> This will add the file_info (folder info in this case) to specified schema under full_path, folder key name would be as supplied `folder_name`.
        """
        def helper_fnc(full_path: list, target: dict, file_info: dict):  # create all nested keys / sub directories into schema, if not present.
            if len(full_path) > 0:
                sub_dir = full_path.pop(0)
                if delete and len(full_path) == 0 and file_info is None:
                    # if delete = True, full_path is given, file_info = None (not specified), it means delete the given whole path.
                    logger.info(f"deleting sub dir: {sub_dir}")
                    target.pop(sub_dir)  # remove final sub_dir specified in path.
                    return target
                if sub_dir not in target.keys():    # this is not a possible scenario during delete.
                    target[sub_dir] = {"root": []}
                if len(full_path) == 0:     # if previously fetched sub_dir was the last in path, add the file to that sub dir only. "root" is a list in each directory that holds file_infos.
                    if delete:  # to delete. No other attribute other than `message_id` needs to be supplied for deletion.
                        logger.debug(f"Attempting to delete stale file from schema. MessageId: {file_info['message_id']}, Path: {full_path}")
                        for pos, info in enumerate(target[sub_dir]["root"].copy()):
                            if info["message_id"] == file_info["message_id"]:     # Delete based on supplied message_id.
                                target[sub_dir]["root"].pop(pos)    # remove the record for this message_id.
                                break   # once found and deleted return from loop.
                    else:   # to add
                        target[sub_dir]["root"].append(file_info)   # Whole target will be returned in next run, as the primary check was len(full_path) > 0. Recursion ends.
                helper_fnc(full_path, target[sub_dir], file_info)
            return target

        def add_folder_in_path(full_path: list, folder_name: str, schema_dict: dict, folder_info: dict):
            if len(full_path) > 0:
                sub_dir = full_path.pop(0)
                if sub_dir not in schema_dict.keys():
                    logger.info(f"Creating new sub directory: {sub_dir}!!")
                    schema_dict[sub_dir] = {"root": []}     # create target path if not already there.
                if len(full_path) == 0:  # If current sub_dir is final one. Add folder here it self, return updated schema.
                    if folder_name not in schema_dict[sub_dir]:  # If a folder with same folder_name is present in specified path, it should not overwrite.
                        schema_dict[sub_dir][folder_name] = folder_info  # Added a folder with specified name, sub_schema in the said path.
                    else:
                        raise Exception("A folder with same name is already present where the folder add is attempted!")
                add_folder_in_path(full_path, folder_name, schema_dict[sub_dir], folder_info)
            return schema_dict

        try:
            sanitized_path, err = self.get_sanitized_file_path(full_path)
            if sanitized_path is False:
                logger.error(f"Schema manipulation aborted, as path sanity check failed for: {full_path}")
                return False, err
            if sanitized_path == "" and delete:   # Special code for delete in root.
                logger.debug("Attempting to delete a file in root folder!!")
                for pos, info in enumerate(schema.copy()["root"]):
                    if info["message_id"] == int(file_info["message_id"]):
                        schema["root"].pop(pos)
                modified_schema = schema
            elif add_folder and folder_name is not None and isinstance(file_info, dict):  # If `add_folder` is specified, consider `file_info` as a sub_schema_dict, full path as target_folder to place this sub_schema on key/folder name specified by arg `folder_name`
                folder_name, err = self.get_sanitized_file_path(folder_name)
                folder_name = folder_name[0]    # As we have given folder name not path.
                if folder_name is False:    # applying name sanity checks for new folder as well.
                    logger.error(f"Schema manipulation aborted, as path sanity check failed for: {folder_name}")
                    return False, err
                if sanitized_path == "":    # A folder move to root.
                    logger.debug("Attempting to Move a folder to root directory!!")
                    schema[folder_name] = file_info  # Added a new folder in root directory.
                    modified_schema = schema.copy()
                else:
                    modified_schema = add_folder_in_path(sanitized_path, folder_name, schema, file_info)
            else:
                modified_schema = helper_fnc(sanitized_path, schema.copy(), file_info)
            return modified_schema, ""   # at the end of recursion, we will get updated schema. Starting schema manipulation on a copy of schema to be safe.
        except Exception as err:
            logger.error(f"Serious Problem in manipulating schema. (During Deletion? {delete}), Error: {err}")
            return False, f"Internal Error: {err}"

    def find_record_by_attribute(self, data, attr: str, attr_val: str | int, partial_match: bool=False, results=None) -> list:
        """If `partial_match` is set to True, records are compared as SQL "like" instead of exact match. \n
        I may have messed up the code. But please don't supply `results` argument during this function call. It is supposed to be for internal recursion use only. """
        if results == None:  # For the actual function call, user shouldn't supply this argument, so we start with empty list at first. Later this list is passed through whole recursion process. To finally return populated list.
            results = []
        if isinstance(data, dict):
            if attr in data:
                if partial_match:
                    if str(attr_val).lower() in str(data[attr]).lower():
                        results.append(data)
                else:   # do exact match
                    if data[attr] == attr_val:
                        results.append(data)
            else:
                for value in data.values():  # Iterate through values in the dictionary
                    self.find_record_by_attribute(value, attr, attr_val, partial_match, results)   # Recursively search through the nested structure
        elif isinstance(data, list):    # Check if data is a list
            for item in data:   # Iterate through items in the list
                self.find_record_by_attribute(item, attr, attr_val, partial_match, results)    # Search through list of files.
        return results

    def get_file_list_in_a_directory(self, schema_dict: dict):
        """Iterates through all nested keys in given schema dictionary(this can be whole schema are a sub_schema whose structure is similar to ur standard schema). \n
           Adds each file in each sub_directory to file_list. Same can be looped through to get every individual file for processing. \n
            To get all the files present in a sub_directory in schema, call get_contents_in_directory with a path to sub dir, and feed it's response to this function.
        """
        def get_file_list(schema_dict: dict, file_list:list = []):    # file list is initially empty. Internal recursive function.
            for key, value in schema_dict.items():
                if isinstance(value, dict):
                    get_file_list(value, file_list)
                elif key == "root" and isinstance(value, list):
                    file_list.extend(value)
            return file_list
        try:
            file_list = get_file_list(schema_dict.copy())
            return file_list, ""
        except Exception as err:
            return False, err


class EncDecHelper:
    """Helper class to provide methods for encrypting and decrypting data from and to binary"""
    def __init__(self, passwd: str) -> None:
        self.__enc_key = self.derive_key_from_password(passwd)
        self.__cipher = Fernet(self.__enc_key)

    def derive_key_from_password(self, password, salt=b"salt", iterations=100000):
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,  # 32 bytes for Fernet key
            salt=salt,
            iterations=iterations,
            backend=default_backend()
        )
        key = kdf.derive(password.encode())
        return base64.urlsafe_b64encode(key).decode('utf-8')

    def get_encrypted_data_binary(self, file_binary):
        return self.__cipher.encrypt(file_binary)

    def get_decrypted_data_binary(self, encrypted_file_binary):
        if isinstance(encrypted_file_binary, bytearray):
            encrypted_file_binary = bytes(encrypted_file_binary)
        return self.__cipher.decrypt(encrypted_file_binary)
