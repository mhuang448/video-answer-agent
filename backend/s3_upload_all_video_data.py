import boto3
import os
import sys
import time
import concurrent.futures
import threading
from botocore.exceptions import ClientError, NoCredentialsError
from dotenv import load_dotenv

load_dotenv()

# --- Configuration ---
# Use environment variable or default to 10 concurrent workers
DEFAULT_MAX_WORKERS = 10
MAX_WORKERS = int(os.getenv('MAX_UPLOAD_WORKERS', DEFAULT_MAX_WORKERS))
if MAX_WORKERS <= 0:
    print(f"Warning: MAX_UPLOAD_WORKERS must be positive. Falling back to default: {DEFAULT_MAX_WORKERS}")
    MAX_WORKERS = DEFAULT_MAX_WORKERS


def _upload_single_file(s3_client, local_path, bucket_name, s3_key, content_type):
    """
    Uploads a single file to S3. Designed to be called concurrently.

    Args:
        s3_client: Initialized boto3 S3 client.
        local_path (str): Path to the local file.
        bucket_name (str): Target S3 bucket name.
        s3_key (str): Target S3 object key.
        content_type (str): MIME type for the file (e.g., 'video/mp4', 'application/json').

    Returns:
        tuple: (bool, str) indicating (success_status, s3_key)
    """
    thread_id = threading.get_ident()
    short_filename = os.path.basename(local_path)
    print(f"[Thread-{thread_id}] Uploading '{short_filename}' to s3://{bucket_name}/{s3_key} ({content_type})...")
    start_time = time.time()
    try:
        s3_client.upload_file(
            local_path,
            bucket_name,
            s3_key,
            ExtraArgs={'ContentType': content_type}
        )
        end_time = time.time()
        print(f"[Thread-{thread_id}] SUCCESS: Uploaded '{short_filename}' to '{s3_key}' in {end_time - start_time:.2f} seconds.")
        return True, s3_key
    except ClientError as e:
        print(f"[Thread-{thread_id}] ERROR uploading '{short_filename}' to '{s3_key}': {e}")
        return False, s3_key
    except FileNotFoundError:
        print(f"[Thread-{thread_id}] ERROR: Local file not found: '{local_path}'")
        return False, s3_key
    except Exception as e:
        # Catch unexpected errors during upload
        print(f"[Thread-{thread_id}] UNEXPECTED ERROR uploading '{short_filename}' to '{s3_key}': {e}")
        import traceback
        traceback.print_exc() # Print full traceback for unexpected errors
        return False, s3_key


def upload_all_processed_concurrent(local_base_dir, bucket_name, s3_target_prefix="video-data/"):
    """
    Iterates through subdirectories in local_base_dir, identifies all files to upload,
    and uploads them concurrently to S3 using a ThreadPoolExecutor.
    """
    overall_start_time = time.time()
    print(f"Starting concurrent bulk upload from '{local_base_dir}' to 's3://{bucket_name}/{s3_target_prefix}'")
    print(f"Using up to {MAX_WORKERS} concurrent worker threads.")

    upload_tasks = []
    processed_dirs_count = 0
    skipped_items = []

    # --- Phase 1: Scan directories and collect upload tasks ---
    print("Scanning directories and collecting file upload tasks...")
    scan_start_time = time.time()

    if not os.path.isdir(local_base_dir):
        print(f"Error: Local base directory '{local_base_dir}' not found.")
        return

    try:
        dir_items = sorted(os.listdir(local_base_dir))
        for item_name in dir_items:
            potential_video_dir = os.path.join(local_base_dir, item_name)

            if os.path.isdir(potential_video_dir):
                processed_dirs_count += 1
                video_id = item_name # Directory name is the video_id
                s3_video_prefix = f"{s3_target_prefix}{video_id}/"

                # Scan items within the video directory
                try:
                    for sub_item_name in os.listdir(potential_video_dir):
                        local_item_path = os.path.join(potential_video_dir, sub_item_name)
                        s3_key = f"{s3_video_prefix}{sub_item_name}"

                        # Main MP4
                        if sub_item_name == f"{video_id}.mp4" and os.path.isfile(local_item_path):
                            upload_tasks.append({
                                'local_path': local_item_path, 's3_key': s3_key, 'content_type': 'video/mp4'
                            })
                        # Main JSON
                        elif sub_item_name == f"{video_id}.json" and os.path.isfile(local_item_path):
                             upload_tasks.append({
                                'local_path': local_item_path, 's3_key': s3_key, 'content_type': 'application/json'
                            })
                        # Chunks directory
                        elif sub_item_name == "chunks" and os.path.isdir(local_item_path):
                            chunks_s3_prefix = f"{s3_video_prefix}chunks/"
                            try:
                                for chunk_filename in os.listdir(local_item_path):
                                    local_chunk_path = os.path.join(local_item_path, chunk_filename)
                                    if os.path.isfile(local_chunk_path) and chunk_filename.lower().endswith('.mp4'):
                                        chunk_s3_key = f"{chunks_s3_prefix}{chunk_filename}"
                                        upload_tasks.append({
                                            'local_path': local_chunk_path, 's3_key': chunk_s3_key, 'content_type': 'video/mp4'
                                        })
                                    # Optionally log skipped files within chunks
                            except OSError as e:
                                 print(f"Warning: Could not list chunks in '{local_item_path}': {e}")
                        # Optionally log other skipped items within video dir
                        # else:
                        #     if os.path.isfile(local_item_path): print(f"  Debug: Skipping file in video dir: {local_item_path}")
                        #     elif os.path.isdir(local_item_path): print(f"  Debug: Skipping dir in video dir: {local_item_path}")

                except OSError as e:
                     print(f"Warning: Could not list items in '{potential_video_dir}': {e}")

            else:
                # Log items skipped in the base directory (e.g., .DS_Store)
                skipped_items.append(item_name)

    except OSError as e:
        print(f"Error listing base directory '{local_base_dir}': {e}")
        return

    scan_end_time = time.time()
    print(f"Scan complete. Found {len(upload_tasks)} files to upload from {processed_dirs_count} directories in {scan_end_time - scan_start_time:.2f} seconds.")
    if skipped_items:
        print(f"Skipped non-directory items in base folder: {', '.join(skipped_items)}")
    if not upload_tasks:
        print("No files found to upload.")
        return

    # --- Phase 2: Execute uploads concurrently ---
    print("-" * 30)
    print(f"Starting concurrent upload of {len(upload_tasks)} files...")
    upload_start_time = time.time()
    success_count = 0
    failure_count = 0
    failed_keys = []

    try:
        # Initialize S3 client (can be shared across threads)
        s3_client = boto3.client('s3', region_name=os.getenv("AWS_REGION"))
        # Optional: Verify connection once before starting pool
        print("Attempting to verify AWS credentials and region...")
        s3_client.list_buckets()
        print("AWS credentials and region verified.")

        futures = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            for task in upload_tasks:
                futures.append(executor.submit(
                    _upload_single_file,
                    s3_client,
                    task['local_path'],
                    bucket_name,
                    task['s3_key'],
                    task['content_type']
                ))

            # Process results as they complete
            for future in concurrent.futures.as_completed(futures):
                try:
                    success, s3_key = future.result()
                    if success:
                        success_count += 1
                    else:
                        failure_count += 1
                        failed_keys.append(s3_key)
                except Exception as exc:
                    # Catch errors raised from within the thread task itself (if not caught by _upload_single_file)
                    print(f"!! Internal error processing upload result: {exc}")
                    failure_count += 1
                    # Attempt to find the associated task's key (might be difficult if error is early)
                    # This part is complex, rely on logging within _upload_single_file primarily

    except NoCredentialsError:
        print("ERROR: AWS credentials not found. Configure via ~/.aws/credentials, env vars, or IAM role.")
        return # Cannot proceed without credentials
    except ClientError as e:
         # Handle errors during initial client setup/verification
         error_code = e.response.get('Error', {}).get('Code')
         if error_code == 'AccessDenied':
             print(f"ERROR: Access Denied verifying credentials (check IAM permissions).")
         elif error_code == 'InvalidAccessKeyId':
              print(f"ERROR: Invalid AWS Access Key ID.")
         elif error_code == 'SignatureDoesNotMatch':
              print(f"ERROR: AWS Signature mismatch (check Secret Key and region).")
         else:
             print(f"AWS ClientError during setup/verification: {e}")
         return # Cannot proceed if setup fails
    except Exception as e:
        # Catch other unexpected errors during setup
        print(f"An unexpected error occurred during initialization: {e}")
        import traceback
        traceback.print_exc()
        return

    # --- Phase 3: Report summary ---
    upload_end_time = time.time()
    overall_end_time = time.time()
    print("-" * 30)
    print(f"Concurrent upload finished.")
    print(f"  Attempted: {len(upload_tasks)} files")
    print(f"  Successful: {success_count}")
    print(f"  Failed: {failure_count}")
    if failed_keys:
        print(f"  Failed S3 keys (see logs above for details):")
        for key in failed_keys:
            print(f"    - {key}")
    print(f"  Upload phase duration: {upload_end_time - upload_start_time:.2f} seconds.")
    print(f"  Total script duration: {overall_end_time - overall_start_time:.2f} seconds.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python dist_s3_upload_all_video_data.py <path_to_local_PROCESSED_VIDEOS_base_dir>")
        print("Example: python dist_s3_upload_all_video_data.py ./video-data")
        print(f"Configure concurrency with MAX_UPLOAD_WORKERS environment variable (default: {DEFAULT_MAX_WORKERS}).")
        sys.exit(1)

    local_dir = sys.argv[1]
    bucket = os.getenv("S3_BUCKET_NAME")
    s3_prefix = os.getenv("S3_TARGET_PREFIX", "video-data/") # Allow overriding prefix via env var

    if not bucket:
         print("Error: S3_BUCKET_NAME environment variable not set.")
         sys.exit(1)
    if not s3_prefix.endswith('/'):
        print("Warning: S3_TARGET_PREFIX should end with '/'. Appending it.")
        s3_prefix += '/'


    upload_all_processed_concurrent(local_dir, bucket, s3_prefix) 