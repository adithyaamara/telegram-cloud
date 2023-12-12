from flask import Flask, render_template, request, redirect, url_for, send_file
from telegram import Bot, InputFile
from dotenv import load_dotenv
import io
import json
import os

app = Flask(__name__)

# Load environment variables
load_dotenv()
bot_token = os.environ["API_KEY"]
channel_id = os.environ["CHANNEL_ID"]
schema_filename = 'schema.json'

# Initialize the bot
bot = Bot(token=bot_token)

# Load or initialize schema
try:
    with open(schema_filename, 'r') as schema_file:
        schema = json.load(schema_file)
except FileNotFoundError:
    schema = {'root': []}

# Function to upload a file and update the schema
def upload_file(file):
    try:
        response = bot.send_document(chat_id=channel_id, document=InputFile(file), filename=file.filename)
        file_info = {'filename': file.filename, 'message_id': response.message_id, 'file_id': response.document.file_id}
        schema['root'].append(file_info)
        print(f"File uploaded successfully. Message ID: {response.message_id}")
    except Exception as e:
        print(f"Error uploading file: {e}")
        return False, str(e)
    return True, None

# Function to download a file using the recorded file ID
def download_file(file_id, filename):
    try:
        file_content = bot.get_file(file_id).download_as_bytearray()
        return send_file(io.BytesIO(file_content), as_attachment=True, download_name=filename)
    except Exception as e:
        print(f"Error downloading file: {e}")

# Function to delete a file from the channel and update the schema
def delete_file(message_id, filename):
    try:
        bot.delete_message(chat_id=channel_id, message_id=message_id)
        # Remove the file_info from the schema
        schema['root'] = [file_info for file_info in schema['root'] if file_info['filename'] != filename]
    except Exception as e:
        print(f"Error deleting file: {e}")
        return False
    return True

# Function to save the schema to the file
def save_schema():
    with open(schema_filename, 'w') as schema_file:
        json.dump(schema, schema_file, indent=4)

# Flask routes

@app.route('/')
def index():
    return render_template('index.html', files=schema['root'])

@app.route('/upload', methods=['POST'])
def upload():
    file = request.files['file']
    if file:
        success, error_message = upload_file(file)
        if success:
            # Save the schema after a successful upload
            save_schema()
            return redirect(url_for('index'))
        else:
            return render_template('error.html', error_message=error_message)
    return redirect(url_for('index'))

@app.route('/download/<file_id>/<filename>')
def file_download(file_id, filename):
    return download_file(file_id, filename)

@app.route('/delete/<filename>', methods=['POST'])
def delete(filename):
    file_info = next((info for info in schema['root'] if info['filename'] == filename), None)
    if file_info:
        success = delete_file(file_info['message_id'], filename)
        if success:
            # Save the schema after a successful deletion
            save_schema()
            return redirect(url_for('index'))
        else:
            return render_template('error.html', error_message="Error deleting file.")
    else:
        return render_template('error.html', error_message="File not found.")

if __name__ == '__main__':
    app.run(debug=True)
