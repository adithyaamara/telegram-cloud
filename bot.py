from flask import Flask, render_template, request, redirect, url_for, send_file, jsonify
from threading import Thread
from dotenv import load_dotenv
from pathvalidate import sanitize_filepath
from core import BotActions
from datetime import datetime
import io
import os
import ssl
import logging
load_dotenv()
logger = logging.getLogger()

context = ssl.SSLContext(ssl.PROTOCOL_TLSv1_2)
context.load_cert_chain('certs/cert.pem', 'certs/key.pem')
app = Flask(__name__)
bot = BotActions()

@app.before_request
def block_on_validation_in_progress():
    """call this function in first line of each route, to block traffic during schema validation process. To maintain schema.json integrity."""
    if bot.is_validation_active() is True:
        return jsonify({"message": "No action allowed this time, A validation Job is in progress. Kindly come back later!"}), 404

# Flask routes
@app.route('/', methods=['GET'])
def index():
    block_on_validation_in_progress()
    directory = request.args.get('directory', None)  # Directory to navigate to.
    if directory is None:   # If dir not specified, use home.
        return render_template('index.html', files=bot._schema["root"], working_directory=bot._default_upload_directory, total_size=bot._schema["meta"]["total_size"], last_validated=str(datetime.fromtimestamp(bot._schema["meta"]["last_validated"])) if isinstance(bot._schema["meta"]["last_validated"], float) else bot._schema["meta"]["last_validated"])
    else:   # BUG: Write re-usable function to sanitize file paths.
        if directory[0] == "/": directory = directory[1:]    # remove first '/' if present.
        full_path = sanitize_filepath(directory).split('/')
        ret_structure = bot._schema.copy()
        for sub_dir in full_path:
            if sub_dir not in ret_structure:
                return jsonify({"message": f"Invalid Path - {directory}!!"})
            ret_structure = ret_structure[sub_dir]
        return render_template('index.html', files=ret_structure["root"], working_directory=directory, total_size=bot._schema["meta"]["total_size"], last_validated=str(datetime.fromtimestamp(bot._schema["meta"]["last_validated"])) if isinstance(bot._schema["meta"]["last_validated"], float) else bot._schema["meta"]["last_validated"])

@app.route('/upload/', methods=['POST'])
def upload():
    block_on_validation_in_progress()
    files = request.files.getlist('upload_file')
    target_directory = request.form.get('upload_directory', "")  # It will be uploaded to root folder if nothing is specified.
    success_count = 0
    error_messages = []
    if len(files) > 0:
        for file in files:
            success, error_message = bot.upload_file(file, file.filename, directory=target_directory)   # On success we get, True, file_id
            if success:
                success_count += 1
            else:   # on failure we get false, error_message
                error_messages.append(error_message)
                logger.error(f"Failed to upload file {file.filename}, Error: {str(error_message)}")
        if success_count == len(files):
            return redirect(url_for("index"))
        else:
            return render_template('error.html', error_message=f"Failed to upload {len(files) - success_count} out of {len(files)} selected!!: Errors: {error_messages}")
    return redirect(url_for("index"))

@app.route('/download/<file_id>')
def file_download(file_id):
    block_on_validation_in_progress()
    file_content, file_name_or_error = bot.download_file(file_id)
    if file_content:
        return send_file(io.BytesIO(file_content), as_attachment=True, download_name=file_name_or_error)  # same is reverted to user, with out saving locally.
    else:
        return jsonify({"message": f"Error Downloading the file: {file_name_or_error}"})

@app.route('/delete/<message_id>', methods=['POST'])
def delete(message_id):
    block_on_validation_in_progress()
    logger.debug(f"Attempting to delete files in message with ID: {message_id}!")
    success = bot.delete_file(message_id)
    if success:
        logger.debug(f"Deleted the files in message id: {message_id}")
        return redirect(url_for('index'))
    else:
        logger.error(f"Error deleting file / message with ID: {message_id}")
        return render_template('error.html', error_message=f"Error deleting file / message with ID: {message_id}")

@app.route('/validate/')
def validate_schema():
    block_on_validation_in_progress()
    Thread(target=bot.validate_job, daemon=True).start()
    return "This will iterate through all the files in schema, and checks if they still exist in cloud. \
        Finally updates schema with only files that are still available in cloud. This will take a long time, happens in background. \
            Advised to not make any changes to cloud state meanwhile."

@app.route('/persist/upload/', methods=['GET'])
def persist_schema():
    block_on_validation_in_progress()
    try:
        success, file_id = bot.upload_file(file=open(bot._schema_filename, 'rb'), file_name=bot._schema_filename, update_schema=False)
        if success is True:
            return jsonify({"message": f"Schema Upload successful, Use {file_id} to recover!"})
    except Exception as err:
        logger.error(f"Something went wrong during uploading schema: {err}")
    return render_template('error.html', error_message=file_id)  # This is not file_id but error if success is False.

@app.route('/persist/download/', methods=['GET', 'POST'])
def recover_schema():
    block_on_validation_in_progress()
    if request.method == 'GET':
        return render_template('recovery.html')
    try:
        file_content, _ = bot.download_file(file_id=request.form.get("file_id"))
        if file_content:
            bot.save_schema(file_content)
            logger.info(f"Schema recovery successful!")
            return redirect(url_for('index'))
    except Exception as err:
        logger.error(f"Something went wrong recovering schema from cloud: {err}")
    return render_template('error.html', error_message='Something went wrong during schema recovery. Please try again!!')

if __name__ == '__main__':
    logging.basicConfig(filename="logs.txt", filemode='a', level=os.getenv("LOGGING_LEVEL", 'INFO').upper())
    app.run(port=443, host='0.0.0.0', debug=True, ssl_context=context)
