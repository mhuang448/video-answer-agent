#!/usr/bin/env python

# utility script to clear all interactions.json files from S3, to prevent cluttering the bucket

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
MAX_WORKERS = int(os.getenv('MAX_DELETE_WORKERS', DEFAULT_MAX_WORKERS))
if MAX_WORKERS <= 0:
    print(f"Warning: MAX_DELETE_WORKERS must be positive. Falling back to default: {DEFAULT_MAX_WORKERS}")
    MAX_WORKERS = DEFAULT_MAX_WORKERS

def _delete_single_file(s3_client, bucket_name, s3_key):
    """
    Deletes a single file from S3. Designed to be called concurrently.

    Args:
        s3_client: Initialized boto3 S3 client.
        bucket_name (str): Target S3 bucket name.
        s3_key (str): S3 object key to delete.

    Returns:
        tuple: (bool, str) indicating (success_status, s3_key)
    """
    thread_id = threading.get_ident()
    print(f"[Thread-{thread_id}] Deleting 's3://{bucket_name}/{s3_key}'...")
    try:
        s3_client.delete_object(
            Bucket=bucket_name,
            Key=s3_key
        )
        print(f"[Thread-{thread_id}] SUCCESS: Deleted 's3://{bucket_name}/{s3_key}'")
        return True, s3_key
    except ClientError as e:
        print(f"[Thread-{thread_id}] ERROR deleting 's3://{bucket_name}/{s3_key}': {e}")
        return False, s3_key
    except Exception as e:
        # Catch unexpected errors during deletion
        print(f"[Thread-{thread_id}] UNEXPECTED ERROR deleting 's3://{bucket_name}/{s3_key}': {e}")
        import traceback
        traceback.print_exc()  # Print full traceback for unexpected errors
        return False, s3_key

def find_interaction_files(s3_client, bucket_name, s3_target_prefix="video-data/"):
    """
    Lists all interaction.json files in the S3 bucket under the specified prefix.
    
    Args:
        s3_client: Initialized boto3 S3 client
        bucket_name (str): S3 bucket name
        s3_target_prefix (str): Prefix to search under
        
    Returns:
        list: List of S3 keys for interaction.json files
    """
    print(f"Scanning for interaction.json files under 's3://{bucket_name}/{s3_target_prefix}'...")
    interaction_keys = []
    
    try:
        # List common prefixes (directories) under the target prefix
        paginator = s3_client.get_paginator('list_objects_v2')
        dir_iterator = paginator.paginate(
            Bucket=bucket_name,
            Prefix=s3_target_prefix,
            Delimiter='/'
        )
        
        # For each "directory" (common prefix), check for an interactions.json file
        for dir_page in dir_iterator:
            common_prefixes = dir_page.get('CommonPrefixes', [])
            for prefix in common_prefixes:
                video_prefix = prefix.get('Prefix')
                if video_prefix:
                    interaction_key = f"{video_prefix}interactions.json"
                    
                    # Check if this file exists
                    try:
                        s3_client.head_object(Bucket=bucket_name, Key=interaction_key)
                        interaction_keys.append(interaction_key)
                        print(f"Found: s3://{bucket_name}/{interaction_key}")
                    except ClientError as e:
                        # Object doesn't exist or access denied - silently skip
                        if e.response['Error']['Code'] in ('404', '403'):
                            continue
                        else:
                            print(f"Error checking s3://{bucket_name}/{interaction_key}: {e}")
        
        return interaction_keys
    
    except ClientError as e:
        print(f"Error listing objects in bucket '{bucket_name}': {e}")
        return []
    except Exception as e:
        print(f"Unexpected error scanning bucket: {e}")
        import traceback
        traceback.print_exc()
        return []

def clear_interactions_concurrent(bucket_name, s3_target_prefix="video-data/", dry_run=False):
    """
    Scans the S3 bucket for interactions.json files and deletes them concurrently.
    If dry_run is True, only lists the files that would be deleted without actually deleting them.
    """
    overall_start_time = time.time()
    print(f"Starting scan for interactions.json files in 's3://{bucket_name}/{s3_target_prefix}'")
    
    if dry_run:
        print("DRY RUN MODE: Files will be listed but not actually deleted.")
    
    # --- Phase 1: Scan S3 and collect interaction.json files to delete ---
    scan_start_time = time.time()
    
    try:
        # Initialize S3 client
        s3_client = boto3.client('s3', 
                                region_name=os.getenv("AWS_REGION"),
                                aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
                                aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"))
        
        # Verify bucket exists and we have access
        try:
            s3_client.head_bucket(Bucket=bucket_name)
            print(f"Successfully connected to bucket: {bucket_name}")
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code')
            if error_code == '404':
                print(f"ERROR: Bucket '{bucket_name}' does not exist.")
            elif error_code == '403':
                print(f"ERROR: Access denied to bucket '{bucket_name}'. Check permissions.")
            else:
                print(f"ERROR accessing bucket '{bucket_name}': {e}")
            return
        
        # Find all interactions.json files
        interaction_keys = find_interaction_files(s3_client, bucket_name, s3_target_prefix)
        
        scan_end_time = time.time()
        print(f"Scan complete. Found {len(interaction_keys)} interactions.json files in {scan_end_time - scan_start_time:.2f} seconds.")
        
        if not interaction_keys:
            print("No interaction.json files found. Nothing to delete.")
            return
            
        # If dry run, just output the files and exit
        if dry_run:
            print("DRY RUN SUMMARY: The following files would be deleted:")
            for key in interaction_keys:
                print(f"  s3://{bucket_name}/{key}")
            print(f"Total: {len(interaction_keys)} files")
            return
    
        # --- Phase 2: Execute deletions concurrently ---
        print("-" * 30)
        print(f"Starting concurrent deletion of {len(interaction_keys)} files using up to {MAX_WORKERS} worker threads...")
        
        delete_start_time = time.time()
        success_count = 0
        failure_count = 0
        failed_keys = []
        
        futures = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            for key in interaction_keys:
                futures.append(executor.submit(
                    _delete_single_file,
                    s3_client,
                    bucket_name,
                    key
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
                    print(f"!! Internal error processing deletion result: {exc}")
                    failure_count += 1
        
        # --- Phase 3: Report summary ---
        delete_end_time = time.time()
        overall_end_time = time.time()
        print("-" * 30)
        print(f"Concurrent deletion finished.")
        print(f"  Attempted: {len(interaction_keys)} files")
        print(f"  Successfully deleted: {success_count}")
        print(f"  Failed: {failure_count}")
        if failed_keys:
            print(f"  Failed S3 keys (see logs above for details):")
            for key in failed_keys:
                print(f"    - {key}")
        print(f"  Deletion phase duration: {delete_end_time - delete_start_time:.2f} seconds.")
        print(f"  Total script duration: {overall_end_time - overall_start_time:.2f} seconds.")
            
    except NoCredentialsError:
        print("ERROR: AWS credentials not found. Configure via ~/.aws/credentials, env vars, or IAM role.")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    # Parse command line arguments
    import argparse
    parser = argparse.ArgumentParser(description='Clear all interactions.json files from S3 bucket.')
    parser.add_argument('--dry-run', action='store_true', help='List files but do not delete them')
    parser.add_argument('--prefix', type=str, default=os.getenv("S3_TARGET_PREFIX", "video-data/"),
                        help='S3 prefix to scan under (default: "video-data/" or S3_TARGET_PREFIX env var)')
    
    args = parser.parse_args()
    
    bucket = os.getenv("S3_BUCKET_NAME")
    if not bucket:
        print("Error: S3_BUCKET_NAME environment variable not set.")
        sys.exit(1)
        
    prefix = args.prefix
    if not prefix.endswith('/'):
        print("Warning: S3 prefix should end with '/'. Appending it.")
        prefix += '/'
    
    # Ask for confirmation unless in dry run mode
    if not args.dry_run:
        confirm = input(f"This will DELETE ALL interactions.json files in s3://{bucket}/{prefix}*. Are you sure? (y/N): ")
        if confirm.lower() not in ('y', 'yes'):
            print("Operation cancelled.")
            sys.exit(0)
    
    clear_interactions_concurrent(bucket, prefix, dry_run=args.dry_run)
