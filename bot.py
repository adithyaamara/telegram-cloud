from flask import Flask, render_template, request, redirect, url_for, send_file, jsonify, flash
from flask_login import LoginManager, login_user, UserMixin, login_required, logout_user
from threading import Thread
from dotenv import load_dotenv
from core import BotActions
from datetime import datetime
import io
import os
import ssl
import logging
load_dotenv()
logger = logging.getLogger()

# Fetch temporary user credentials for app login, chosen by user, set to default if unspecified.
temp_app_username = os.getenv("APP_USER_NAME", "user")
temp_app_password = os.getenv("APP_PASSWORD", "password")

context = ssl.SSLContext(ssl.PROTOCOL_TLSv1_2)
context.load_cert_chain('certs/cert.pem', 'certs/key.pem')
app = Flask(__name__)
app.secret_key = 'your_secret_key_here'  # Optional for now, For Sake of flash messages.
login_manager = LoginManager(app)
login_manager.login_view = 'login'  # Specify the login route, otherwise auto-redirect to login page won't work.

bot = BotActions()  # Core telegram interaction functions.

class User(UserMixin):
    def __init__(self, user_id):
        self.id = user_id

def authenticate_user(username, password):
    # Replace this with your actual user authentication logic
    if username == temp_app_username and password == temp_app_password:
        return User(1)  # User id is always 1.
    return None

@login_manager.user_loader
def load_user(user_id):
    return User(user_id)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = authenticate_user(request.form['username'], request.form['password'])
        if user:
            login_user(user)  # Log in the user
            # flash('Login successful!', 'success')
            return redirect(url_for('index'))
        else:
            flash('Invalid credentials', 'danger')

    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Logout successful!', 'success')
    return redirect(url_for('login'))

@app.before_request
def block_on_validation_in_progress():
    """call this function in first line of each route, to block traffic during schema validation process. To maintain schema.json integrity."""
    if bot.is_validation_active() is True:
        return jsonify({"message": "No action allowed this time, A validation Job is in progress. Kindly come back later!"}), 404

# Flask routes
@app.route('/', methods=['GET'])
@login_required
def index():
    block_on_validation_in_progress()
    directory = request.args.get('target_directory', None)  # Directory to navigate to.
    if directory is None:   # If dir not specified, use home.
        folders = list(bot._schema.keys())
        folders.remove("root")  # reserved for storing files.
        folders.remove("meta")  # reserved for metadata in root.
        return render_template('index.html', files=bot._schema["root"], folders=folders, working_directory="", total_size=bot._schema["meta"]["total_size"], last_validated=str(datetime.fromtimestamp(bot._schema["meta"]["last_validated"])) if isinstance(bot._schema["meta"]["last_validated"], float) else bot._schema["meta"]["last_validated"])
    else:   # BUG: Write re-usable function to sanitize file paths.
        _, ret_structure, err = bot._ops.get_contents_in_directory(directory, bot._schema.copy(), files_only=False)  # get dict item from schema in a given directory path. COntains both files and folders.
        if ret_structure is not False:
            folders = list(ret_structure.keys())
            folders.remove("root")
            directory_parts = []
            path_str = ""
            for path_item in directory.split('/'):  # Building breadcrumb target_directory paths for easy navigation.
                if path_item != "":  # If path_item is "", an extra / is displayed in breadcrumb. We don;t even allow empty folder names to be created anyway.
                    path_str = path_str + '/' + path_item
                    directory_parts.append((path_item, path_str))   # read same way in template. path_item is folder name displayed in bread crumb (ex: sample), path_str is full path to reach that folder (ex: /bkp/folder/sample).
            return render_template('index.html', files=ret_structure["root"], folders=folders, working_directory=directory, directory_parts=directory_parts)   # working_directory is passed so that delete requests, further folder navigation is based on this current working directory.
        return jsonify({"error": err})

@app.route('/bulk-upload/', methods=['GET'])    # For full folder uploads.
@login_required
def bulk():
    """Upload a folder full of files, subdirs to root folder to server"""
    return render_template('bulk-upload.html')

@app.route('/upload/', methods=['POST'])
@login_required
def upload():
    block_on_validation_in_progress()
    files = request.files.getlist('upload_file')
    target_directory = request.form.get('target_directory', "")  # It will be uploaded to root folder if nothing is specified.
    logger.debug(f"Request received for uploading {len(files)} file[s] to directory: {target_directory}")
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
            flash("Recent Upload of File[s] Successful!", "success")
        else:
           flash(f"Failed to upload {len(files) - success_count} out of {len(files)} selected!!: Errors: {error_messages}", "danger")   # danger specifies that alert is displayed in red.
        return redirect(f"{url_for('index')}?target_directory={target_directory}")  # redirect to same location where the request came from.
    flash("Please select at-least one file to upload!!", "warning")
    return redirect(f"{url_for('index')}?target_directory={target_directory}")

@app.route('/download/<file_id>')
@login_required
def file_download(file_id):
    block_on_validation_in_progress()
    file_content, file_name_or_error = bot.download_file(file_id)
    if file_content:
        file_info = bot._ops.find_record_by_attribute(bot._schema.copy(), "file_id", file_id)   # Iteratively get file info from schema, use file_id as attribute for matching.
        file_name = file_info["filename"] if file_info else file_name_or_error  # If search returned a record, use file name from record. else some default name taken from telegram(Most usually it will be wrong).
        return send_file(io.BytesIO(file_content), as_attachment=True, download_name=file_name)  # same is reverted to user, with out saving locally.
    else:
        return jsonify({"message": f"Error Downloading the file: {file_name_or_error}"})

@app.route('/delete/<message_id>', methods=['POST'])
@login_required
def delete(message_id):
    block_on_validation_in_progress()
    logger.debug(f"Attempting to delete files in message with ID: {message_id}!")
    target_directory = request.form.get('target_directory', "")
    success, err = bot.delete_file(target_directory, message_id)     # supply directory where file is located, message id to delete. [Feature: Add support for deleting message id with out mentioning directory. (needs iterative search)]
    if success is not False:
        logger.debug(f"Deleted the files in message id: {message_id}")
        flash("File deleted successfully!", "success")  # Select category as bootstrap button class, other wise an ugly alert is displayed! Color of alert is based in class of message chosen.
        return redirect(f"{url_for('index')}?target_directory={target_directory}")  # redirect to same location where the delete request came from.
    else:
        logger.error(f"Error deleting file / message with ID: {message_id}")
        return render_template('error.html', error_message=f"Error deleting file / message with ID: {message_id}. Error: {err}")

@app.route('/delete_folder/', methods=['POST'])
@login_required
def delete_folder():
    folder_path = request.form.get('delete_folder', None)   # Which folder must be deleted?
    if folder_path is not None:
        success, err = bot.delete_folder(folder_path)
        if success is not False:
            flash("Folder deletion successful!!", "success")
            return redirect(url_for('index'))   # On success
        else:
            flash("Something went, Folder deletion un-successful! Please check logs.", "danger")
            return render_template('error.html', error_message=err)  # return error message
    return render_template('error.html', error_message="POST request to delete a folder is missing required form fields: 'delete_folder'.")

@app.route('/move_folder/', methods=['POST'])
@login_required
def move_folder():
    folder_to_move = request.form.get("folder_to_move", None)
    target_folder = request.form.get("target_folder", None)
    new_name_for_moved_folder = request.form.get("new_name_for_moved_folder", None)
    if (folder_to_move is None) or (target_folder is None):
        logger.error("MoveFile request is missing required form data, rejected it!")
        return redirect(url_for('index'))
    if new_name_for_moved_folder == "": new_name_for_moved_folder = None   # No new name specified by user.
    res, err = bot.move_folder(folder_to_move, target_folder, new_name_for_moved_folder)    # Invalid folder name sanity checks apply for this new_name_for_moved_folder as well.
    if res is False:
        return jsonify({"error": err})
    return redirect(url_for('index'))

@app.route('/validate/')
@login_required
def validate_schema():
    block_on_validation_in_progress()
    Thread(target=bot.validate_job, daemon=True).start()
    return "This will iterate through all the files in schema, and checks if they still exist in cloud. \
        Finally updates schema with only files that are still available in cloud. This will take a long time, happens in background. \
            Advised to not make any changes to cloud state meanwhile."

@app.route('/persist/upload/', methods=['GET'])
@login_required
def persist_schema():
    block_on_validation_in_progress()
    try:
        success, file_id = bot.upload_file(file=open(bot._schema_filename, 'rb'), file_name=bot._schema_filename.split('/')[-1], update_schema=False)
        if success is True:
            return jsonify({"message": f"Schema Upload successful, Use {file_id} to recover!"})
    except Exception as err:
        logger.error(f"Something went wrong during uploading schema: {err}")
    return render_template('error.html', error_message=file_id)  # This is not file_id but error if success is False.

@app.route('/persist/download/', methods=['GET', 'POST'])
@login_required
def recover_schema():
    block_on_validation_in_progress()
    if request.method == 'GET':
        return render_template('recovery.html')
    try:
        file_content, _ = bot.download_file(file_id=request.form.get("file_id"))
        if file_content:
            bot.save_schema(file_content)
            logger.info(f"Schema recovery successful!")
            flash("Schema recovery successful!", "success")
            return redirect(url_for('index'))
    except Exception as err:
        logger.error(f"Something went wrong recovering schema from cloud: {err}")
        flash("Something went wrong recovering schema from cloud", "danger")
    return render_template('error.html', error_message='Something went wrong during schema recovery. Please try again!!')

if __name__ == '__main__':
    logging.basicConfig(filename="logs.txt", filemode='a', level=os.getenv("LOGGING_LEVEL", 'DEBUG').upper())
    app.run(port=443, host='0.0.0.0', debug=True, ssl_context=context)
