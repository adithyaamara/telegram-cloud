from bot import BotActions
import click
import os
import time

bot = BotActions()  # initializes a telegram BOT.

@click.group()
def cli():
    pass

def count_files(path):
    """Count the total number of files in the specified path."""
    file_count = sum(1 for root, dirs, files in os.walk(path) for file in files)
    return file_count

@cli.command()
@click.option('--path', type=click.Path(exists=True, file_okay=False, dir_okay=True), required=True, help='Absolute path to the folder to be processed, all subdirectories will be processed too.')
@click.option('--dry_run', is_flag=True, default=False, help='Set this option to do a crawl check, not do the actual upload!!')
def upload(path, dry_run):
    """Upload all files in each and every subdirectory in the specified path. Replicates local directory structure in cloud UI as well."""
    files_to_process = count_files(path)
    choice = bool(input(f"You are about to upload {files_to_process} files, Do you wish to proceed? Press any key, enter to proceed."))
    if choice is not False:
        processed_files = 0  # Total files processed.
        success = 0          # Successful uploads.
        failure_list:list[tuple(str, str, str)] = []  # Attempt to retry later. [At the end]. Tuple is file_path, target_directory(in server), filename
        base_dir = os.path.basename(path)   # Fetch the directory name that is being backed up. [Example: `c:/users/never/gonna/give` --> base_dir = `give`]
        start_time = time.time()
        for root, dirs, files in os.walk(path):
            for file in files:
                file_path = os.path.join(root, file)    # This is where file is physically present in your system.
                target_directory = str(root)[str(root).find(base_dir):].replace("\\", "/")   # Upload target in server will be starting from base_dir
                with open(file_path, 'rb') as file_binary:
                    click.echo(f"Processing file {processed_files} / {files_to_process} files. Attempting to upload file '{file}' to '{target_directory}' in server!")    # [Ex: If selected path is `c:/users/never/gonna/give` --> the folder structure replicated in server schema will be starting from `give`]
                    if not dry_run:
                        res, err = bot.upload_file(file_binary, file, True, target_directory)
                    else:
                        res, err = True, ""  # Return dummy response in case of dry run.
                    processed_files += 1    # file processed
                    time.sleep(0.1)  # Avoid DDOS Bro. Better to Increase this if you have patience.
                    if res is True:
                        click.echo(f"Successfully uploaded the file '{file}' to '{target_directory}'")
                        success += 1        # Successful process.
                    else:
                        click.echo(err)
                        failure_list.append((file_path, target_directory, file))

        # retry infinitely with small delay -> Doesn't effect folder structure in cloud.
        while len(failure_list) > 0:    # Try and Try until you succeed..
            for pos, (file_path, target_directory, file) in failure_list.copy():
                with open(file_path, 'rb') as file_binary:
                    click.echo(f"Retrying to Upload: '{file}' to '{target_directory}'")
                    res = bot.upload_file(file_binary, file, True, target_directory)
                    if res is True:
                        failure_list.pop(pos)  # Remove This item from original list if success.
                        click.echo(f"File Number: {success}, Successfully uploaded the file '{file}' to '{target_directory}'")
                        success += 1        # Successful process.
                        time.sleep(0.1)  # Avoid DDOS Bro. Better to Increase this if you have patience.
                    else:
                        click.echo(f"Retry attempt on '{file}' FAILED. we'll get em next time!!")
            time.sleep(10)  # delay before successive retry attempts. [Flood control]
        end_time = time.time()
        click.echo(f"Process finished in {round(end_time - start_time, 2)} seconds, Successfully uploaded {success} files out of a total of {files_to_process} files!!")
if __name__ == '__main__':
    cli()
