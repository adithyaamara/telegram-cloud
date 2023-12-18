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
                        time.sleep(0.1)  # Avoid DDOS Bro. Better to Increase this if you have patience.
                    else:
                        res, err = True, ""  # Return dummy response in case of dry run.
                    processed_files += 1    # file processed
                    if res is True:
                        click.echo(f"Successfully uploaded the file '{file}' to '{target_directory}'.")
                        success += 1        # Successful process.
                        files_to_process.remove((file_path, target_directory, file))   # remove file record from process list, once it is successfully uploaded.
                    else:
                        click.echo(err)
            click.echo(f"One round of processing completed ({success} / {total_no_of_files} successful uploads). Will retry failed batch of files (if any) in 20 seconds...")
            if len(files_to_process) > 0:   # Avoid time waste if no pending files are there.
                time.sleep(20)
        end_time = time.time()  # end time.
        click.echo(f"Process finished in {round(end_time - start_time, 2)} seconds, Successfully uploaded {success} files out of a total of {total_no_of_files} files!!")
if __name__ == '__main__':
    cli()
