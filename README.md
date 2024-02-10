# telegram-cloud  [![Docker Image CI](https://github.com/adithyaamara/telegram-cloud/actions/workflows/CI-Docker-Push.yml/badge.svg?branch=main)](https://github.com/adithyaamara/telegram-cloud/actions/workflows/CI-Docker-Push.yml)

    A personal, secure, free, unlimited cloud storage based on telegram.

## Usage

- Use `bot father` in telegram to create a new bot, save the `api_key` generated.
- Create a new **private channel** in telegram. Open telegram on web, navigate to this private channel.
- From the URL, copy last part, a number that starts with -100. This is your channel ID.
- Add newly created bot as an admin to this private channel. (So that bot can upload files to private channel.)
- Clone code, Create a .env file in current directory with below variables set
- Run `source run.sh` / `bash run.sh` in terminal to run the program in local.
    > Access Homepage at: `localhost:443` [SSL Enabled]
- To run as container, Run `docker-compose up -d`, access homepage at `machine-ip-or-hostname:443`
    > .env can be deleted once compose setup starts up.

  ```env
  API_KEY="get this api key from telegram botfather"
  CHANNEL_ID="channel id which will be used for file storage"
  # Below 2 env vars creates a user for login. Defaults are used if not specified (Defaults: user, password).
  APP_USER_NAME="SomeUserName-Use the same during login"
  APP_PASSWORD="SomePassword-Use the same during login"
  # Use True | False in below option to enable / disable encrypted uploads.
  FILE_ENCRYPTION="True"
  # File encryption adds some overhead, increasing final upload size.
  # Like a file that is originally 17MB, becomes 21MB after encryption. So this is not uploaded as current api limit is 20 mb only.
  LOGGING_LEVEL="DEBUG"
  ```

## Features

- Simple one-user login functionality. [Created from secrets specified in .env]
- Upload (Encrypt / Plain), Download, Delete files <= 50 MB. [Current telegram bot limit] [Workaround to support large file uploads is in planning]
- File Sharing via unique link.
- Search by filename across directories and nested directories.
- Simple UI, Shows the total cloud storage space consumed using this app.
- If telegram files uploaded using this app are deleted manually using app / web, `Revalidate Schema` feature will check entire schema and removes what is removed from channel.

## Notes

- The files uploaded using this app are tracked via a file named `schema.json`, it is persisted across server restarts using a docker volume.
- Deleting that volume will start the application empty next time. While the files are still available to you on telegram server, you can't see them and work on them using this app if `schema.json` is lost. [Use schema persist and recover features to avoid this]
- Please ensure to **create a private channel with only you as a subscriber**.

## Feature Addition

- File Sharing
  - Individual files can be shared by logged in user. Downloadable with unique link by any one without login.
  - Sharing on a file expires in 100 mins or 2 download attempts, Whichever is first.
  - Shared Files are not stored on server, each time fetched from telegram, decrypted, sent as download.
  - Active file shares details are stored in-memory, and are lost if server is restarted.

- Encrypted Files
  - All files are encrypted before uploading to telegram, Unless disabled manually via env setting `FILE_ENCRYPTION=FALSE`.
  - Files are downloaded form telegram, decrypted first, before sending file to user.

- Bulk Upload / Download CLI tool
  - Run `python backupper.py --help` to get started, follow the help content provided by CLI.
  - To Upload a local folder: `python backupper.py upload --path C:/Users/username/Desktop/ImportantFiles [--path_in_server Backup]  [--dry_run]`
    - Uploads all sub-directories, files in the local folder `ImportantFiles` to a folder in server named `Backup`.
    - `path_in_server` is optional to specify, default if unspecified will create `ImportantFiles` folder in root directory.
    - `--dry_run` Specifying this will just print summary of uploads, but doesn't actually upload anything. It is better to run using this arg first to check if
      everything is as expected or not, later run without specifying this argument to do the actual uploads to server.
  - To download a directory in server to local: `python backupper.py download --path_in_server Backup/ImportantFiles [--path C:/Users/username/Downloads] [--dry_run]`
    - `path_in_server` - specify the folder path in server that needs to be downloaded. `path` is optional, Uses `./Downloads` in current directory as default.
    - `--dry_run` - To just see download summary, not to actual download anything. A harmless trial run. Do not specify this if you actually want to download.
  > This tool currently only works if you are running the server not from docker but as a standalone python server.
  > This is because this cli tool directly invokes `BotActions` class, the updated schema after upload action will be from local `schema/` folder.

- Schema Backup
  - Now migrating app from one machine to another is easy.
  - Use `persist` button from home page to upload your current schema to telegram itself,
    which will give you a `file_id` as response,  **you need to save it somewhere.(It will be shown only once)**
  - Once you start the server in new machine, Use the same file_id to later recover this schema using `recover` button in homepage.
    > This will overwrite any schema changes you have made after previous `persist` (In new / old machine). Recovers schema to the point where it was backed up.
