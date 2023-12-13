from flask import Flask, render_template, request, redirect, url_for, send_file, jsonify
from werkzeug import datastructures
# from werkzeug.utils import secure_filename
from telegram import Bot, InputFile, error as telegram_error
from threading import Thread
from dotenv import load_dotenv
from datetime import datetime
import time
import io
import json
import os
import ssl
import logging
from hurry.filesize import size

context = ssl.SSLContext(ssl.PROTOCOL_TLSv1_2)
context.load_cert_chain('certs/cert.pem', 'certs/key.pem')
VALIDATION_ACTIVE = False   # Global must be set to true to disable traffic on all routes, during schema validation. So that state of schema is predictable after validation.
app = Flask(__name__)
logger = logging.getLogger()
# Load environment variables
load_dotenv()
bot_token = os.environ["API_KEY"]
channel_id = os.environ["CHANNEL_ID"]
schema_filename = 'schema.json'
logger.info("Required config variables are read from env!")
# Initialize the bot
bot = Bot(token=bot_token)

# Load or initialize schema
try:    # FEATURE: Migrate schema to mongo db. [Allow us for a greater level of aggregation, avoid using mean json manipulation loops.]
    with open(schema_filename, 'r') as schema_file:
        schema = json.load(schema_file)
        if "meta" not in schema:
            schema["meta"] = {"total_size": "Unknown", "last_validated": "Please re-validate schema ASAP!"}
except FileNotFoundError:
    logger.info("Schema.json not found in local directory, creating new empty schema.")
    schema = {'root': [], "meta": {"total_size": 0, "last_validated": "Unavailable! Please Revalidate schema."}}

# Function to upload a file and update the schema
def upload_file(file: datastructures.FileStorage, file_name: str):
    try:
        response = bot.send_document(filename=file_name, chat_id=channel_id, document=InputFile(file))  # BUG: Filename given in send_document is not reaching cloud, all files are getting uploaded as `upload_file`.
        # message_id is used to delete the file later, document.file_id is used for downloading, Size is saved in raw bytes (useful for calculating total size used in telegram cloud).
        file_info = {'filename': file_name, 'message_id': response.message_id, 'file_id': response.document.file_id, "size": size(response.document.file_size)}
        schema['root'].append(file_info)    # At the moment, default directory is 'root' only.
        logger.debug(f"File uploaded successfully. Message ID: {response.message_id}")
        save_schema()
        return True, None
    except Exception as e:
        logger.error(f"Error uploading file: {e}")
        return False, str(e)

# Function to download a file using the recorded file ID
def download_file(file_id: str):
    try:
        file_content: bytes = bot.get_file(file_id).download_as_bytearray()    # All the file data is in ram, not on local file storage.
        logger.debug(f"Attempting to send file with ID '{file_id}' to user!!")
        file_info = next((info for info in schema['root'] if info['file_id'] == file_id), None)
        return send_file(io.BytesIO(file_content), as_attachment=True, download_name=file_info["filename"])  # same is reverted to user, with out saving locally.
    except Exception as e:
        logger.error(f"Error downloading the file: {e}")

# Function to delete a file from the channel and update the schema
def delete_file(message_id: int):
    try:
        res = bot.delete_message(chat_id=channel_id, message_id=message_id)   # deletion is not based on file id, but message_id.
        if res is True:
            schema['root'] = [file_info for file_info in schema['root'] if file_info['message_id'] != message_id]   # Remove the file_info from the schema (based on message_id)
            save_schema()
            logger.debug(f"File with Message_ID: {message_id} deleted successfully!")
            return True
    except Exception as e:
        logger.error(f"Error deleting file: {e}")
        return False

# Function to save the schema to the file
def save_schema():
    with open(schema_filename, 'w') as schema_file:
        json.dump(schema, schema_file, indent=4)    # save as file. [Should be migrated to mongodb]
    logger.debug(f"Latest Schema dumped!!")

def validate_job():
    global VALIDATION_ACTIVE, schema
    """Works on global object schema, start this function as a background thread. Finally put the last validation date in schema for future reference (Display last validation date in homepage also.)"""
    total_space_consumed = 0    # Aggregate size of all uploaded files.
    VALIDATION_ACTIVE = True    # disable all routes during update via a control flag variable.
    try:
        total_records = len(schema['root'])
        validated_records = 0
        for pos, file_info in enumerate(schema["root"]):
            try:
                file_id = file_info["file_id"]
            except KeyError:
                schema['root'].pop(pos)
                logger.error(f"Ill-Formatted record found. File_ID missing. Dropping it.")
                continue    # no need to proceed further on this file.
            try:
                cloud_file = bot.get_file(file_id=file_id)
                total_space_consumed += cloud_file.file_size
                logger.debug(f"No issues found with record, Ref Files ID: {file_id}")
            except telegram_error.BadRequest:
                logger.info(f"The file no longer exists on cloud! Removing it from schema. Ref Id: {file_id}")
                schema['root'].pop(pos)
            # Updating needed attributes in schema from cloud freshly.
            # schema['root'][pos]["filename"] = cloud_file.file_path.split('/')[-1]  # Should be enabled after BUG on setting right file name during upload is fixed.
            schema['root'][pos]["size"] = size(cloud_file.file_size)     # save in KB / MB.
            validated_records += 1
            logger.debug(f"{validated_records} out of {total_records} validated!!")
            time.sleep(1)   # small delay to avoid DDOS scenario.

        schema["meta"] = {"total_size": size(total_space_consumed), "last_validated": datetime.utcnow().timestamp()}
        save_schema()   # dumps updated schema file.
        logger.info("Schema Validation completed successfully!!")
        VALIDATION_ACTIVE = False
    except Exception as err:
        VALIDATION_ACTIVE = False
        logger.error(f"Something went wrong during schema validation. Operation failed. Error: {err}")

@app.before_request
def block_on_validation_in_progress():
    """call this function in first line of each route, to block traffic during schema validation process. To maintain schema.json integrity."""
    global VALIDATION_ACTIVE
    if VALIDATION_ACTIVE is True:
        return jsonify({"message": "No action allowed this time, A validation Job is in progress. Kindly come back later!"}), 404

# Flask routes
@app.route('/')
def index():
    block_on_validation_in_progress()
    return render_template('index.html', files=schema['root'], total_size=schema["meta"]["total_size"], last_validated=str(datetime.fromtimestamp(schema["meta"]["last_validated"])) if isinstance(schema["meta"]["last_validated"], int) else schema["meta"]["last_validated"])

@app.route('/upload', methods=['POST'])
def upload():
    block_on_validation_in_progress()
    files = request.files.getlist('upload_file')
    success_count = 0
    if len(files) > 0:
        for file in files:
            success, error_message = upload_file(file, file.filename)
            if success:
                success_count += 1
            else:
                logger.error(f"Failed to upload file {file.filename}, Error: {str(error_message)}")
        if success_count == len(files):
            return redirect(url_for("index"))
        else:
            return render_template('error.html', error_message=f"Failed to upload {len(files) - success_count} out of {len(files)} selected!!")
    return redirect(url_for("index"))

@app.route('/download/<file_id>')
def file_download(file_id):
    block_on_validation_in_progress()
    return download_file(file_id)

@app.route('/delete/<message_id>', methods=['POST'])
def delete(message_id):
    block_on_validation_in_progress()
    file_info = next((info for info in schema['root'] if info['message_id'] == int(message_id)), None)   # find file info from schema by message id
    if file_info:
        logger.debug(f"Attempting to delete files in message with ID: {message_id}!")
        success = delete_file(file_info['message_id'])
        if success:
            logger.debug(f"Deleted the files in message id: {message_id}")
            return redirect(url_for('index'))
        else:
            logger.error(f"Error deleting file / message with ID: {message_id}")
            return render_template('error.html', error_message=f"Error deleting file / message with ID: {message_id}")
    else:
        logger.error(f"No message found with ID: {message_id}")
        return render_template('error.html', error_message=f"No message / files found on ID: {message_id}")

@app.route('/validate/')
def validate_schema():
    block_on_validation_in_progress()
    Thread(target=validate_job, daemon=True).start()
    return "This will iterate through all the files in schema, and checks if they still exist in cloud. \
        Finally updates schema with only files that are still available in cloud. This will take a long time, happens in background. \
            Advised to not make any changes to cloud state meanwhile."

if __name__ == '__main__':
    logging.basicConfig(filename="logs.txt", filemode='a', level=os.getenv("LOGGING_LEVEL", 'INFO').upper())
    app.run(port=443, host='0.0.0.0', debug=True, ssl_context=context)
