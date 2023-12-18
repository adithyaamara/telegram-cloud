from bot import BotActions
import click
import os
import time

bot = BotActions()  # initializes a telegram BOT.

@click.group()
def cli():
    pass

def fetch_files(path, path_in_server):
    """Count the total number of files in the specified path."""
    path = str(path).replace("\\", "/")
    if path_in_server is not None:
        path_in_server = str(path_in_server).replace("\\", "/")
    else:
        path_in_server = ""  # Root in server.
    path = os.path.abspath(path)    # removes trailing slashes.
    base_dir = os.path.basename(path)   # Fetch the directory name that is being backed up. [Example: `c:/users/never/gonna/give` --> base_dir = `give`]
    files_to_process:list[tuple(str, str, str)] = []    # List of files, Tuple is file_path, target_directory(in server), filename.
    for root, dirs, files in os.walk(path):
        for file in files:
            file_path = os.path.join(root, file)    # This is where file is physically present in your system.
            target_directory = os.path.join(path_in_server, str(root)[str(root).find(base_dir):].replace("\\", "/"))   # Upload target in server will be starting from base_dir
            target_directory = target_directory.replace("\\", "/")
            files_to_process.append((file_path, target_directory, file))
    return files_to_process

@cli.command()
@click.option('--path', type=click.Path(exists=True, file_okay=False, dir_okay=True), required=True, help='Absolute path to the folder to be processed (Use forward slash "/" as path separator), all subdirectories will be processed too.')
@click.option('--path_in_server', default=None, help='Path to the folder in server UI where all the current files will be placed, (Use forward slash "/" as path separator), Default is, A new base_dir in root folder in server.')
@click.option('--dry_run', is_flag=True, default=False, help='Set this option to do a crawl check, not do the actual upload!!')
def upload(path: str, path_in_server: str, dry_run: bool):
    """Upload all files in each and every subdirectory in the specified path. Replicates local directory structure in cloud UI as well."""
    files_to_process = fetch_files(path, path_in_server)
    total_no_of_files = len(files_to_process)
    choice = bool(input(f"You are about to upload {total_no_of_files} files, Do you wish to proceed? Press any key, enter to proceed."))
    if choice is not False:
        processed_files = 0  # Total attempts.
        success = 0          # Successful uploads.
        start_time = time.time()    # start time
        while len(files_to_process) > 0:
            for file_path, target_directory, file in files_to_process.copy():
                with open(file_path, 'rb') as file_binary:
                    click.echo(f"Process Attempt Number: {success}. Attempting to upload file '{file}' to '{target_directory}' in server!")    # [Ex: If selected path is `c:/users/never/gonna/give` --> the folder structure replicated in server schema will be starting from `give`]
                    if not dry_run:
                        res, err = bot.upload_file(file_binary, file, True, target_directory)
                        time.sleep(1)  # Avoid DDOS Bro. Better to Increase this if you have patience.
                    else:
                        res, err = True, ""  # Return dummy response in case of dry run.
                    processed_files += 1    # file processed
                    if res is True:
                        click.echo(f"Successfully uploaded the file '{file}' to '{target_directory}'.")
                        success += 1        # Successful process.
                        files_to_process.remove((file_path, target_directory, file))   # remove file record from process list, once it is successfully uploaded.
                    else:
                        click.echo(err)
                        if "Flood control" in err:
                            click.echo("[Flood Control] - Waiting for 35 seconds, as telegram is afraid that you are DDOS-ing it!!")
                            time.sleep(35)  # If telegram complained a flood control, we just need to stop.

            click.echo(f"One round of processing completed ({success} / {total_no_of_files} successful uploads). Will retry failed batch of files (if any) in 20 seconds...")
            if len(files_to_process) > 0:   # Avoid time waste if no pending files are there.
                time.sleep(20)
        end_time = time.time()  # end time.
        click.echo(f"Process finished in {round(end_time - start_time, 2)} seconds, Successfully uploaded {success} files out of a total of {total_no_of_files} files!!")


@cli.command()
@click.option('--path', type=click.Path(file_okay=False, dir_okay=True), default="./Downloads/", help='Absolute path to the folder where files will be downloaded. (Use forward slash "/" as path separator). Default is to download to current directory/downloads folder.')
@click.option('--path_in_server', default=None, help='Path to the folder in server UI, ALL the files in all the directories inside the pointed folder will be downloaded, (Use forward slash "/" as path separator), Default is, All files in cloud starting from root folder.')
@click.option('--dry_run', is_flag=True, default=False, help='Set this option to do a crawl check, not do the actual download!!')
@click.option('--force', is_flag=True, default=False, help='Set this option to True if you want to re-download even if the file in question is already present in your local.')
def download(path: str, path_in_server: str, dry_run: bool, force: bool):
    sub_schema, err = bot._ops.get_contents_in_directory(path_in_server, bot._schema, files_only=False)   # Get bot files and folders inside this directory.
    if sub_schema is False:
        click.echo(f"Something went wrong! Error: {err}")
    else:
        file_list = []  # A list of tuples, Each tuple is local_path, file_name

        def process_sub_schema(schema_dict: dict, base_path="./Downloads/", path_in_server: str = ""):
            """Iterates through all nested keys in given schema dictionary, adds each file in each sub_directory to file_list. Same can be looped through during download"""
            for key, value in schema_dict.items():
                current_path = os.path.join(base_path, path_in_server, key) if key != "root" else base_path  # root key doesn't need to be created.
                if isinstance(value, dict):
                    process_sub_schema(value, current_path)
                elif key == "root" and isinstance(value, list):
                    for file_info in value:
                        file_path = os.path.join(current_path, file_info["filename"])
                        file_list.append((current_path, file_info["filename"], file_info["file_id"]))  # current_path is location of file, filename is name of file, id is used to download from telegram channel.
                        click.echo(f"File: {file_path}")

        click.echo("Summary of file structure that will be created, if you choose to accept it..")
        process_sub_schema(sub_schema, path, path_in_server)  # Just verify number of files across all directories, populate list of files to download.
        choice = bool(input(f"You are about to download {len(file_list)} files from server. Press any key and Enter to continue..."))
        if choice is True:
            start_time = time.time()
            success = 0
            total_files = len(file_list)
            while len(file_list) > 0:   # Actual download happens
                for path, file_name, file_id in file_list.copy():
                    file_path = os.path.join(path, file_name)
                    if not os.path.exists(path):
                        click.echo(f"Creating Directory: {path}")
                        os.makedirs(path)
                    if not os.path.exists(file_path) or force:   # leave if already files is present, do it anyway if force flag is specified.
                        if not dry_run:
                            file_in_bytes, err = bot.download_file(file_id)  # Download from server if this is not a dry run.
                        else:
                            file_in_bytes, err = "True", ""
                        if file_in_bytes is not False:  # if download is success.
                            if not dry_run:
                                with open(file_path, 'wb') as fp: fp.write(file_in_bytes)
                                time.sleep(1)
                            file_list.remove((path, file_name, file_id))
                            success += 1
                            click.echo(f"Successfully downloaded, saved the file: {file_path}")
                        else:
                            click.echo(f"Something went wrong while downloading '{file_path}', Error: {err}")
                            if "Flood control" in err:
                                click.echo("[Flood Control] - Waiting for 35 seconds, as telegram is afraid that you are DDOS-ing it!!")
                                time.sleep(35)
                            time.sleep(1)
                    else:
                        click.echo(f"Skip downloading of '{file_path}', as it is already present! Run with `--force` arg set, to force download everything.")
                click.echo(f"Finished one round of downloads ({success} / {total_files} downloads). Will process the failure (if any) in 20 seconds")
                if len(file_list) > 0:
                    time.sleep(20)  # Wait time before retry.
            end_time = time.time()
            click.echo(f"Downloaded a total of {total_files} files in {round(end_time-start_time, 2)} seconds!")

if __name__ == '__main__':
    cli()
