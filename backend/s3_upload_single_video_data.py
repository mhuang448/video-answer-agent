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
    (Identical to the function in dist_s3_upload_all_video_data.py)

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


def upload_single_video_concurrent(single_video_dir_path, bucket_name, s3_target_prefix="video-data/"):
    """
    Scans a single video directory and uploads its contents (.mp4, .json, chunks/*)
    concurrently to S3 using a ThreadPoolExecutor.
    """
    overall_start_time = time.time()

    if not os.path.isdir(single_video_dir_path):
        print(f"Error: Target video directory '{single_video_dir_path}' not found or is not a directory.")
        return

    video_id = os.path.basename(single_video_dir_path) # Extract video ID from directory name
    s3_video_prefix = f"{s3_target_prefix}{video_id}/"

    print(f"Starting concurrent upload for video '{video_id}' from '{single_video_dir_path}'")
    print(f"Target S3 location: 's3://{bucket_name}/{s3_video_prefix}'")
    print(f"Using up to {MAX_WORKERS} concurrent worker threads.")

    upload_tasks = []
    files_found_count = 0

    # --- Phase 1: Scan the specific directory and collect upload tasks ---
    print("Scanning directory and collecting file upload tasks...")
    scan_start_time = time.time()

    try:
        # Check for main MP4
        local_mp4_path = os.path.join(single_video_dir_path, f"{video_id}.mp4")
        if os.path.isfile(local_mp4_path):
            s3_key = f"{s3_video_prefix}{video_id}.mp4"
            upload_tasks.append({'local_path': local_mp4_path, 's3_key': s3_key, 'content_type': 'video/mp4'})
            files_found_count += 1
        else:
             print(f"Warning: Main video file not found: '{local_mp4_path}'")

        # Check for main JSON
        local_json_path = os.path.join(single_video_dir_path, f"{video_id}.json")
        if os.path.isfile(local_json_path):
            s3_key = f"{s3_video_prefix}{video_id}.json"
            upload_tasks.append({'local_path': local_json_path, 's3_key': s3_key, 'content_type': 'application/json'})
            files_found_count += 1
        else:
            print(f"Warning: Main JSON file not found: '{local_json_path}'")

        # Check for chunks directory
        local_chunks_dir = os.path.join(single_video_dir_path, "chunks")
        if os.path.isdir(local_chunks_dir):
            chunks_s3_prefix = f"{s3_video_prefix}chunks/"
            try:
                for chunk_filename in os.listdir(local_chunks_dir):
                    local_chunk_path = os.path.join(local_chunks_dir, chunk_filename)
                    if os.path.isfile(local_chunk_path) and chunk_filename.lower().endswith('.mp4'):
                        chunk_s3_key = f"{chunks_s3_prefix}{chunk_filename}"
                        upload_tasks.append({
                            'local_path': local_chunk_path, 's3_key': chunk_s3_key, 'content_type': 'video/mp4'
                        })
                        files_found_count += 1
                    # Optionally log skipped files within chunks
            except OSError as e:
                 print(f"Warning: Could not list chunks in '{local_chunks_dir}': {e}")
        else:
             print(f"Warning: Chunks directory not found: '{local_chunks_dir}'")

    except OSError as e:
        print(f"Error accessing video directory '{single_video_dir_path}': {e}")
        return

    scan_end_time = time.time()
    print(f"Scan complete. Found {files_found_count} files ({len(upload_tasks)} tasks generated) in {scan_end_time - scan_start_time:.2f} seconds.")

    if not upload_tasks:
        print("No files found to upload for this video ID.")
        return

    # --- Phase 2: Execute uploads concurrently ---
    print("-" * 30)
    print(f"Starting concurrent upload of {len(upload_tasks)} files...")
    upload_start_time = time.time()
    success_count = 0
    failure_count = 0
    failed_keys = []

    try:
        # Initialize S3 client
        s3_client = boto3.client('s3', region_name=os.getenv("AWS_REGION"))
        print("Attempting to verify AWS credentials and region...")
        s3_client.list_buckets() # Verify connection
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
                    print(f"!! Internal error processing upload result: {exc}")
                    failure_count += 1
                    # Rely on logging within _upload_single_file for failed key details

    except NoCredentialsError:
        print("ERROR: AWS credentials not found. Configure via ~/.aws/credentials, env vars, or IAM role.")
        return
    except ClientError as e:
         error_code = e.response.get('Error', {}).get('Code')
         if error_code == 'AccessDenied':
             print(f"ERROR: Access Denied verifying credentials (check IAM permissions).")
         elif error_code == 'InvalidAccessKeyId':
              print(f"ERROR: Invalid AWS Access Key ID.")
         elif error_code == 'SignatureDoesNotMatch':
              print(f"ERROR: AWS Signature mismatch (check Secret Key and region).")
         else:
             print(f"AWS ClientError during setup/verification: {e}")
         return
    except Exception as e:
        print(f"An unexpected error occurred during initialization: {e}")
        import traceback
        traceback.print_exc()
        return

    # --- Phase 3: Report summary ---
    upload_end_time = time.time()
    overall_end_time = time.time()
    print("-" * 30)
    print(f"Concurrent upload finished for video '{video_id}'.")
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
        print("Usage: python dist_s3_upload_single_video_data.py <path_to_single_video_dir>")
        print("Example: python dist_s3_upload_single_video_data.py ./video-data/your_video_id")
        print("Environment variables required:")
        print("  - S3_BUCKET_NAME: Target S3 bucket")
        print("  - AWS_REGION: AWS region for the bucket")
        print("Optional environment variables:")
        print(f"  - MAX_UPLOAD_WORKERS: Max concurrent uploads (default: {DEFAULT_MAX_WORKERS})")
        print("  - S3_TARGET_PREFIX: S3 prefix before video ID (default: video-data/)")
        sys.exit(1)

    single_video_dir = sys.argv[1]
    bucket = os.getenv("S3_BUCKET_NAME")
    s3_prefix = os.getenv("S3_TARGET_PREFIX", "video-data/") # Allow overriding prefix

    if not bucket:
         print("Error: S3_BUCKET_NAME environment variable not set.")
         sys.exit(1)
    if not os.getenv("AWS_REGION"):
         print("Error: AWS_REGION environment variable not set.")
         sys.exit(1)

    # Ensure the prefix ends with '/' for clean path joining
    if s3_prefix and not s3_prefix.endswith('/'):
        print("Warning: S3_TARGET_PREFIX should end with '/'. Appending it.")
        s3_prefix += '/'

    upload_single_video_concurrent(single_video_dir, bucket, s3_prefix) 