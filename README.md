# telegram-cloud

    A personal, secure, free, unlimited cloud storage.

## Usage

- Use `bot father` in telegram to create a new bot, save the `api_key` generated.
- Create a new **private channel** in telegram.
- Add newly created bot as an admin to this private channel. (So that bot can upload files to private channel.)
- Clone code, Create a .env file in current directory with below variables set
- Run `source start.sh` / `bash start.sh` in terminal to run the program in local.
    > Access Homepage at: `localhost:443` [SSL Enabled]
- To run as container, Run `docker-compose up -d`, access homepage at `machine-ip-or-hostname:443`
    > .env can be deleted once compose setup starts up.

  ```env
  API_KEY="get this api key from telegram botfather"
  CHANNEL_ID="channel id which will be used for file storage"
  LOGGING_LEVEL="DEBUG"
  ```

## Notes

- The files uploaded using this app are tracked via a file named `schema.json`, it is persisted across server restarts using a docker volume.
- Deleting that volume will start the application empty next time. While the files are still available to you on telegram server, you can't see them and work on them using this app if `schema.json` is lost.
- Please ensure to **create a private channel with only you as a subscriber**.
