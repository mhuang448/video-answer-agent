# process_video_pipeline.py
"""
Monolithic script combining the full RAG video Q&A pipeline stages.
"""

# Standard Library Imports
import asyncio
import os
import time
import subprocess # Added for NVENC check
import re
import math
import json
import random # Added for jitter in backoff & discovery
import concurrent.futures # Added for indexing
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from datetime import datetime
import argparse # Added for command-line arguments

# Third-Party Imports
import yt_dlp
from scenedetect import open_video, SceneManager, ContentDetector
from scenedetect.video_splitter import split_video_ffmpeg, DEFAULT_FFMPEG_ARGS
from scenedetect.frame_timecode import FrameTimecode
from dotenv import load_dotenv, set_key # Added set_key
from google import genai
from google.genai import types as google_types
from google.api_core import exceptions as google_exceptions
from openai import OpenAI
from httpx import WriteTimeout, ReadTimeout # Added ReadTimeout
from pinecone.grpc import PineconeGRPC as Pinecone # Added for indexing
from pinecone import ServerlessSpec # Added for indexing

# loading environment variables
load_dotenv() # Looks for '.env' in current or parent directories by default

ms_token = os.environ.get("ms_token", None) # For TikTokApi; currently not used since we're using headless browser
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
PINECONE_API_KEY = os.environ.get("PINECONE_API_KEY") # Added for indexing
PINECONE_INDEX_HOST = os.environ.get("PINECONE_INDEX_HOST") # Added for indexing

# Check essential keys immediately
if not GEMINI_API_KEY:
    print("FATAL ERROR: GEMINI_API_KEY not found in environment or .env.local")
if not OPENAI_API_KEY:
    print("FATAL ERROR: OPENAI_API_KEY not found in environment or .env.local")
if not PINECONE_API_KEY:
    print("FATAL ERROR: PINECONE_API_KEY not found in environment or .env.local")
# PINECONE_INDEX_HOST is checked within initialize_clients

# Configuration for captioning stage
CAPTION_MODEL_NAME = "gemini-2.5-pro-preview-03-25"
CAPTION_MAX_WORKERS = 8 # Max concurrent Gemini API calls
CAPTION_MAX_RETRIES = 5
CAPTION_INITIAL_BACKOFF_SECONDS = 2
SUMMARY_MODEL_NAME = "gpt-4o-mini" # For summary/themes

# Configuration for indexing stage (from index_and_retrieve.py)
INDEX_NAME = "video-captions-index"
EMBED_MODEL_NAME = "text-embedding-ada-002"
EMBED_DIM = 1536
INDEXING_BATCH_SIZE = 100
INDEXING_MAX_EMBEDDING_WORKERS = 8 # Max concurrent OpenAI embedding calls

# Global API Clients (initialized later)
openai_client = None
pc = None
pinecone_index = None


# --- Stage 1: Video Download ---

def download_video_from_url(url, base_download_path):
    """
    Downloads a video from the given URL using yt-dlp.

    Creates a subdirectory based on the username and video ID, saves the
    video file, and creates an initial JSON metadata file.
    Skips download if the video file already exists.

    Args:
        url (str): The URL of the video to download.
        base_download_path (str): The base directory path where the 'video-data'
                                 folder and subsequent subfolders will be created.

    Returns:
        Tuple[str | None, str | None, str | None]:
            - Full path to the downloaded video file (or existing file).
            - Extracted video_id (username-tiktokid).
            - Full path to the created/existing JSON metadata file.
            Returns (None, None, None) on failure.
    """
    print("\n--- Stage 1: Downloading Video ---")
    print(f"  Input URL: {url}")

    if not url:
        print("  Error: No URL provided for download.")
        return None, None, None

    # Extract username and video ID from URL using regex
    match = re.search(r"@(?P<username>[^/]+)/video/(?P<video_id>\d+)", url)
    if not match:
        print(f"  Error: Could not extract username and video ID from URL: {url}")
        return None, None, None

    username = match.group("username")
    tiktok_video_id = match.group("video_id")
    video_id = f"{username}-{tiktok_video_id}" # video_id format (no extension)

    # Construct the specific download directory path: ./video-data/username-videoid
    download_subdir = video_id
    specific_download_path = os.path.join(base_download_path, download_subdir)

    # Create the specific subdirectory if it doesn't exist
    try:
        os.makedirs(specific_download_path, exist_ok=True)
        print(f"  Ensured download directory exists: {specific_download_path}")
    except OSError as e:
        print(f"  Error creating directory {specific_download_path}: {e}")
        return None, None, None

    # Define the output filename template and expected final path
    output_filename_template = f"{video_id}.%(ext)s" # yt-dlp needs extension placeholder
    output_template = os.path.join(specific_download_path, output_filename_template)
    # Use .mp4 as the target extension
    expected_video_path = os.path.join(specific_download_path, f"{video_id}.mp4")
    expected_json_path = os.path.join(specific_download_path, f"{video_id}.json")

    # Check if file already exists to potentially skip download
    if os.path.exists(expected_video_path):
        print(f"  Video already exists at {expected_video_path}. Skipping download.")
        # Ensure JSON also exists or create it if missing
        if not os.path.exists(expected_json_path):
            print(f"  JSON file missing for existing video. Creating {expected_json_path}...")
            initial_json_data = {
                "video_id": video_id,
                "processing_status": "PROCESSING" # Set initial status
            }
            try:
                with open(expected_json_path, 'w', encoding='utf-8') as f:
                    json.dump(initial_json_data, f, indent=2)
                print(f"  Successfully created initial JSON: {expected_json_path}")
            except Exception as e:
                print(f"  Error creating JSON file {expected_json_path}: {e}")
                return expected_video_path, video_id, None # Return video path but None for JSON
        else:
             # If JSON exists, ensure status is PROCESSING if it's not FINISHED?
             # For simplicity, let's just load and check. If it's already FINISHED, maybe leave it.
             # Or overwrite to PROCESSING if we want to re-process? Let's stick to setting it only if creating.
             print(f"  Existing JSON file found: {expected_json_path}")

        print(f"  -> Stage 1 Result: Video Path={expected_video_path}, Video ID={video_id}, JSON Path={expected_json_path}")
        return expected_video_path, video_id, expected_json_path

    # Options for yt-dlp
    ydl_opts = {
        # Prefer mp4 format, fall back to best video/audio merge if necessary
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/mp4/bestvideo+bestaudio/best',
        'outtmpl': output_template,
        'quiet': True, # Suppress non-error messages from yt-dlp
        'warning': True, # Show warnings
        'noplaylist': True, # Ensure only the single video is downloaded
        'merge_output_format': 'mp4', # Try to ensure final output is mp4 if merging occurs
    }

    print(f"  Attempting download via yt-dlp...")
    download_successful = False
    final_video_path = None # Keep track of the actual final path

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        # Check if the specifically requested mp4 file exists
        if os.path.exists(expected_video_path):
             print(f"  Download successful: {expected_video_path}")
             final_video_path = expected_video_path
             download_successful = True
        else:
             # If the mp4 wasn't created directly, check for other files matching the pattern
             found_alt = False
             if os.path.exists(specific_download_path):
                 for filename in os.listdir(specific_download_path):
                     if filename.startswith(f"{video_id}."):
                         actual_path = os.path.join(specific_download_path, filename)
                         # Check if it's the expected mp4 (maybe renamed slightly) or another format
                         if actual_path.endswith(".mp4"):
                             print(f"  Download process finished. MP4 file found: {actual_path}")
                             final_video_path = actual_path
                             download_successful = True
                             found_alt = True
                         else:
                             # Log other formats but don't break yet, hoping for mp4
                             print(f"  Download process finished. Non-MP4 file found: {actual_path}")
                             if not final_video_path: # Keep first found as fallback
                                 final_video_path = actual_path
                                 download_successful = True # Mark as successful even if not mp4

                 if not found_alt:
                      print(f"  Download process finished, but no file found matching pattern '{video_id}.*' in {specific_download_path}.")
             else:
                 print(f"  Download directory {specific_download_path} does not exist after download attempt.")

    except yt_dlp.utils.DownloadError as e:
        # Specifically catch yt-dlp download errors
        print(f"  yt-dlp download error for {url}: {e}")
    except Exception as e:
        # Catch other unexpected errors during download process
        print(f"  Unexpected error during download for {url}: {e}")

    # Create JSON file AFTER successful download
    final_json_path = None
    if download_successful and final_video_path:
        initial_json_data = {
            "video_id": video_id,
            "processing_status": "PROCESSING" # Set initial status
        }
        try:
            with open(expected_json_path, 'w', encoding='utf-8') as f:
                json.dump(initial_json_data, f, indent=2)
            final_json_path = expected_json_path
            print(f"  Successfully created initial JSON: {final_json_path}")
        except Exception as e:
            print(f"  Error creating JSON file {expected_json_path}: {e}")
            # Download succeeded but JSON failed, return None for JSON path

        print(f"  -> Stage 1 Result: Video Path={final_video_path}, Video ID={video_id}, JSON Path={final_json_path}")
        return final_video_path, video_id, final_json_path
    else:
        print(f"  -> Stage 1 Result: Failed")
        return None, None, None

# --- Stage 2: Video Chunking & Metadata Generation ---

def is_nvenc_available():
    """Checks if NVENC hardware acceleration is available via ffmpeg."""
    try:
        result = subprocess.run(
            ['ffmpeg', '-hide_banner', '-encoders'],
            capture_output=True, text=True, check=True
        )
        return 'h264_nvenc' in result.stdout
    except FileNotFoundError:
        print("    ffmpeg not found. Cannot check for NVENC.")
        return False
    except subprocess.CalledProcessError as e:
        print(f"    Error running ffmpeg to check encoders: {e}")
        return False
    except Exception as e:
        print(f"    Unexpected error checking for NVENC: {e}")
        return False

def chunk_video_and_generate_metadata(video_path, video_id, metadata_json_path, fixed_chunk_duration=4.0):
    """
    Detects scenes or creates fixed-length chunks, saves chunks, and updates
    the provided JSON metadata file with chunk details.

    Args:
        video_path (str): Path to the input video file.
        video_id (str): Unique identifier for the video (e.g., "username-tiktokid").
        metadata_json_path (str): Path to the existing JSON metadata file to update.
        fixed_chunk_duration (float): Duration (in seconds) for fixed-length chunks fallback.

    Returns:
        str: The path to the updated JSON metadata file if successful, otherwise None.
    """
    print("\n--- Stage 2: Chunking Video & Generating Metadata ---")
    print(f"  Input Video Path: {video_path}")
    print(f"  Video ID: {video_id}")
    print(f"  Input JSON Path: {metadata_json_path}")

    if not all([video_path, os.path.exists(video_path), video_id, metadata_json_path, os.path.exists(metadata_json_path)]):
        print("  Error: Invalid or non-existent video path, video_id, or metadata_json_path provided.")
        return None

    # Determine output directory for chunks based on JSON path location
    video_dir = os.path.dirname(metadata_json_path)
    output_dir = os.path.join(video_dir, 'chunks')

    # Create output directory if it doesn't exist
    try:
        os.makedirs(output_dir, exist_ok=True)
        print(f"  Ensured chunk directory exists: {output_dir}")
    except OSError as e:
        print(f"  Error creating chunk directory {output_dir}: {e}")
        return None

    video = None # Initialize video object

    try:
        # Read existing JSON data
        print(f"  Reading existing metadata from {metadata_json_path}...")
        with open(metadata_json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        # Ensure video_id matches
        if data.get("video_id") != video_id:
             print(f"  Error: video_id in JSON ({data.get('video_id')}) does not match provided video_id ({video_id}).")
             return None

        # Check if chunking was already done (e.g., based on presence of chunks, keep status check simple for now)
        if data.get("chunks"): # Simpler check: if chunks exist, assume completed for this stage
             print("  Chunking appears to be already completed based on JSON content. Skipping chunking.")
             print(f"  -> Stage 2 Result: {metadata_json_path} (Skipped)")
             return metadata_json_path

        # Open video
        video = open_video(video_path)
        frame_rate = video.frame_rate
        duration_frames = video.duration.get_frames()
        total_duration_seconds = video.duration.get_seconds()

        print(f"  Video Info: {os.path.basename(video_path)}")
        print(f"    - FPS: {frame_rate:.2f}")
        print(f"    - Total Frames: {duration_frames}")
        print(f"    - Total Duration: {total_duration_seconds:.3f} seconds")

        # Configure detector
        detector = ContentDetector(
            threshold=27.0, # Default recommended threshold
            min_scene_len=int(frame_rate * 0.5) # Minimum scene length = 0.5 seconds
        )

        # Use SceneManager
        scene_manager = SceneManager()
        scene_manager.add_detector(detector)

        print("  Detecting scenes (this may take a moment)...")
        detect_start_time = time.time()
        scene_manager.detect_scenes(video, show_progress=True)
        detect_end_time = time.time()
        print(f"  Scene detection attempt took: {detect_end_time - detect_start_time:.2f} seconds")

        detection_method = "Scene Detection"
        scene_list = scene_manager.get_scene_list()

        # --- Fallback Logic ---
        if len(scene_list) <= 1:
            print(f"  Scene detection found {len(scene_list)} scene(s). Falling back to fixed {fixed_chunk_duration}s chunks.")
            detection_method = f"Fixed {fixed_chunk_duration}s Chunking"
            chunk_len_frames = int(fixed_chunk_duration * frame_rate)
            num_fixed_chunks = math.ceil(duration_frames / chunk_len_frames)
            scene_list = []
            for i in range(num_fixed_chunks):
                start_frame = i * chunk_len_frames
                end_frame = min((i + 1) * chunk_len_frames, duration_frames)
                if start_frame >= end_frame: continue
                start_tc = FrameTimecode(timecode=start_frame, fps=frame_rate)
                end_tc = FrameTimecode(timecode=end_frame, fps=frame_rate)
                scene_list.append((start_tc, end_tc))
            print(f"  Generated {len(scene_list)} fixed-length chunks.")
        else:
            print(f"  Scene detection found {len(scene_list)} scenes.")
        # --- End Fallback Logic ---

        if not scene_list:
            print("  Error: No scenes detected or fixed chunks generated. Cannot proceed.")
            # Remove status update here
            # data["processing_status"] = "CHUNKING_FAILED_NO_SCENES"
            # ... (json write removed) ...
            return None

        # --- Prepare JSON Metadata (Update existing data) ---
        num_chunks = len(scene_list)
        chunks_metadata = []
        # Template for actual files saved by ffmpeg (needs extension)
        output_file_template_ffmpeg = f'{video_id}-Scene-$SCENE_NUMBER.mp4'

        print(f"  Preparing metadata for {num_chunks} chunks...")
        for i, (start_tc, end_tc) in enumerate(scene_list):
            scene_number = i + 1
            # chunk_name for JSON metadata (NO extension)
            chunk_name_metadata = f"{video_id}-Scene-{scene_number:03d}"

            start_seconds = start_tc.get_seconds()
            end_seconds = end_tc.get_seconds()
            if end_seconds <= start_seconds:
                 end_seconds = start_seconds + (1 / frame_rate) # Min 1 frame duration

            start_ts_str = f"{int(start_seconds // 60):02}:{start_seconds % 60:06.3f}"
            end_ts_str = f"{int(end_seconds // 60):02}:{end_seconds % 60:06.3f}"

            normalized_start_time = start_seconds / total_duration_seconds if total_duration_seconds > 0 else 0.0
            normalized_end_time = end_seconds / total_duration_seconds if total_duration_seconds > 0 else 0.0
            chunk_duration = end_seconds - start_seconds

            chunks_metadata.append({
                "chunk_name": chunk_name_metadata, # Use extension-less name for JSON
                "video_id": video_id, # Use video_id key
                "start_timestamp": start_ts_str,
                "end_timestamp": end_ts_str,
                "chunk_number": scene_number,
                "normalized_start_time": round(normalized_start_time, 3),
                "normalized_end_time": round(normalized_end_time, 3),
                "chunk_duration_seconds": round(chunk_duration, 3)
            })

        # Update the main data dictionary read from the file
        data["num_chunks"] = num_chunks
        data["total_duration_seconds"] = round(total_duration_seconds, 3)
        data["detection_method"] = detection_method
        data["chunks"] = chunks_metadata
        # Remove status update here
        # data["processing_status"] = "CHUNKING_IN_PROGRESS"
        # --- End Prepare JSON Metadata ---

        # Determine FFmpeg arguments
        if is_nvenc_available():
            ffmpeg_args = '-map 0:v:0 -map 0:a? -c:v h264_nvenc'
            print("  Using NVENC hardware acceleration for splitting.")
        else:
            ffmpeg_args = DEFAULT_FFMPEG_ARGS
            print("  NVENC not detected. Using default software encoding for splitting.")

        print(f"  Splitting video into {len(scene_list)} chunks using FFmpeg...")
        split_start_time = time.time()
        # Use the ffmpeg template WITH extension
        split_video_ffmpeg(
            video_path,
            scene_list,
            output_dir=output_dir,
            output_file_template=output_file_template_ffmpeg, # Pass template with .mp4
            arg_override=ffmpeg_args,
            show_progress=True
        )
        split_end_time = time.time()
        print(f"  Video splitting took: {split_end_time - split_start_time:.2f} seconds")

        # --- Verification ---
        print(f"  Verifying generated chunks...")
        successful_chunks = 0
        failed_chunks = []
        for i in range(num_chunks):
            scene_number = i + 1
            # Verify against the filename WITH extension
            expected_filename = f"{video_id}-Scene-{scene_number:03d}.mp4"
            expected_filepath = os.path.join(output_dir, expected_filename)

            if os.path.exists(expected_filepath) and os.path.getsize(expected_filepath) > 0:
                successful_chunks += 1
            else:
                failed_chunks.append(expected_filename)

        if failed_chunks:
            print("    --- Missing/Empty Chunks Detected ---")
            for filename in failed_chunks:
                print(f"    WARNING: {filename}")
            print("    ----------------------------------")
        print(f"  Verification complete: {successful_chunks}/{num_chunks} chunks OK.")
        # --- End Verification ---

        # --- Save Updated JSON Metadata ---
        print(f"  Updating metadata in {metadata_json_path}...")
        # Remove status update here
        # data["processing_status"] = "CHUNKING_COMPLETED"
        if successful_chunks != num_chunks:
             data["chunking_warnings"] = f"Only {successful_chunks}/{num_chunks} chunks verified successfully."

        with open(metadata_json_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        print(f"  Successfully updated metadata.")
        print(f"  -> Stage 2 Result: {metadata_json_path}")
        return metadata_json_path
        # --- End Save JSON Metadata ---

    except Exception as e:
        print(f"  Error during chunking/metadata generation: {e}")
        import traceback
        traceback.print_exc()
        # Attempt to update JSON with error status - keep simple error message maybe?
        try:
            with open(metadata_json_path, 'r', encoding='utf-8') as f: data = json.load(f) # Reload just in case
            # Remove status update here
            # data["processing_status"] = "CHUNKING_FAILED"
            data["error_message"] = f"Chunking failed: {str(e)}" # Store error msg
            with open(metadata_json_path, 'w', encoding='utf-8') as f: json.dump(data, f, indent=2)
            print(f"  Updated JSON with error message in {metadata_json_path}")
        except Exception as json_e:
             print(f"  Additionally failed to update JSON status after error: {json_e}")

        print(f"  -> Stage 2 Result: Failed")
        return None
    # Video object closing handled by context manager if open_video was used in `try`

# --- Stage 3: Caption Generation & Video Summarization ---

def _process_single_chunk_for_captioning(client, chunk_path: Path):
    """
    Internal helper: Uploads, processes, captions, and deletes a single video chunk with retries.

    Args:
        client: Initialized Gemini API client.
        chunk_path: Path object for the video chunk file.

    Returns:
        Tuple[Path, str | None]: The original chunk path and the generated caption (or None on failure).
    """
    print(f"    Processing chunk: {chunk_path.name}...")
    uploaded_file = None
    last_exception = None
    attempts_made = 0

    for attempt in range(CAPTION_MAX_RETRIES):
        attempts_made = attempt + 1
        uploaded_file = None # Reset for each attempt
        try:
            # --- 1. Upload ---
            # print(f"      [{attempts_made}/{CAPTION_MAX_RETRIES}] Uploading...")
            upload_start = time.monotonic()
            uploaded_file = client.files.upload(file=chunk_path)
            upload_end = time.monotonic()
            # print(f"        Upload took {upload_end - upload_start:.2f}s")

            # --- 2. Wait for Processing ---
            # print(f"      Waiting for processing...")
            polling_interval = 2
            max_polling_time = 300
            elapsed_time = 0
            wait_start = time.monotonic()
            while uploaded_file.state.name == "PROCESSING":
                time.sleep(polling_interval)
                elapsed_time += polling_interval
                try:
                     uploaded_file = client.files.get(name=uploaded_file.name)
                except Exception as get_err: # Catch error during polling specifically
                     print(f"\n      Polling error getting file state for {uploaded_file.name}: {get_err}")
                     raise # Re-raise to be caught by the main attempt's exception handler

                if elapsed_time > max_polling_time:
                    raise TimeoutError(f"File {uploaded_file.name} processing timed out.")

            if uploaded_file.state.name == "FAILED":
                raise Exception(f"File processing failed state: {uploaded_file.state.name}")
            elif uploaded_file.state.name != "ACTIVE":
                raise Exception(f"File not ACTIVE. State: {uploaded_file.state.name}")
            wait_end = time.monotonic()
            # print(f"        Processing wait took {wait_end - wait_start:.2f}s")

            # --- 3. Generate Caption ---
            # print("      Generating caption...")
            gen_start = time.monotonic()
            contents = [
                google_types.Content(
                    role="user", parts=[google_types.Part.from_uri(file_uri=uploaded_file.uri, mime_type=uploaded_file.mime_type)]
                ),
                google_types.Content(
                    role="user", parts=[google_types.Part.from_text(text="""Analyze the provided video clip. Generate a single block of highly descriptive text, specifically crafted as an accessible caption for blind or visually impaired users.

Your generated caption must comprehensively cover the following aspects:

- **Scene Description:** Clearly describe the setting, environment, and overall context depicted in the video clip.
- **Character Details:** Provide detailed observations of all visible characters. Include their appearance, notable clothing, facial expressions, body language, gestures, and any interactions between them.
- **Sequential Narration:** Offer a clear, step-by-step account of the events, actions, and significant movements as they unfold within the clip. Narrate what is happening in the order it occurs.
- **Auditory Cues:** Describe any discernible dialogue, important sound effects (e.g., a door slamming, a phone ringing, laughter), or significant background music, noting its style or mood if possible.
- **Sentiment Analysis:** Identify and convey the overall emotional tone or mood of the video segment (e.g., humorous, tense, calm, joyful, somber). Integrate this understanding based on both visual cues (expressions, actions) and auditory information (tone of voice, music).

**Crucial Output Formatting Constraints:**

- **Plain Text Output:** The output must be a single block of plain text, suitable for natural language processing.
- **Paragraph Breaks Allowed:** You _may_ use double newlines (`\n\n`) to separate distinct paragraphs or logical shifts in the description (e.g., moving from scene setup to character actions). This helps structure the text for better processing. Avoid using single newlines (`\n`).
- **No Timestamps:** Ensure the generated text contains absolutely _no_ timestamps, time ranges, or time references (e.g., "[00:10:05]", "(0:08-0:11)", "at 15 seconds", "0:00"). The narration should be sequential but without explicit time markers.
- **No Special Formatting Characters:** Strictly avoid using technical or markdown formatting characters like triple backticks (```), hash symbols (#), or single backticks (`).
- **Emphasis Allowed:** You _may_ use asterisks (*) or underscores (_) for emphasizing words or phrases where appropriate for clarity or conveying emotion, but use them sparingly.

The goal is to produce a rich, detailed narrative description that captures the factual content and emotional tone of the video clip in a format optimized for indexing into embedding models and semantic vector databases (facilitating effective chunking and retrieval) for Retrieval Augmented Generation (RAG) pipelines.
""")]
                )
            ]
            generate_content_config = google_types.GenerateContentConfig(response_mime_type="text/plain")

            response_chunks = client.models.generate_content_stream(
                model=CAPTION_MODEL_NAME, contents=contents, config=generate_content_config
            )
            caption = "".join(chunk.text for chunk in response_chunks if hasattr(chunk, 'text') and chunk.text is not None)

            if not caption:
                raise ValueError("Caption generation resulted in empty string.") # Treat empty caption as an error

            gen_end = time.monotonic()
            # print(f"        Caption generation took {gen_end - gen_start:.2f}s")
            # --- SUCCESS --- If we reach here, everything worked in this attempt
            print(f"      Caption generated successfully for {chunk_path.name}.")
            return chunk_path, caption

        # --- Exception Handling for the current attempt --- ##
        except (google_exceptions.RetryError, google_exceptions.DeadlineExceeded,
                google_exceptions.ServiceUnavailable, google_exceptions.ServerError,
                google_exceptions.ResourceExhausted, google_exceptions.ClientError,
                TimeoutError, WriteTimeout, ReadTimeout, KeyError, ValueError) as e:
            # These are considered potentially retryable errors
            last_exception = e
            if attempt < CAPTION_MAX_RETRIES - 1: # Adjusted condition for retry
                 backoff_time = CAPTION_INITIAL_BACKOFF_SECONDS * (2 ** attempt) + random.uniform(0, 1) # Adjusted exponent and attempt number
                 print(f"      Retryable error ({type(e).__name__}) on attempt {attempts_made}/{CAPTION_MAX_RETRIES}. Retrying after {backoff_time:.2f}s...")
                 time.sleep(backoff_time)
                 # No explicit continue needed, loop will proceed to next iteration
            else:
                 # Max retries reached for a retryable error
                 print(f"      Max retries ({CAPTION_MAX_RETRIES}) reached for {chunk_path.name} after retryable error: {type(e).__name__}.")
                 break # Exit the loop, failure will be handled after the loop

        except Exception as e:
            # These are considered non-retryable errors
            last_exception = e
            print(f"      Non-retryable error on attempt {attempts_made} for {chunk_path.name}: {type(e).__name__} - {e}")
            break # Exit the loop immediately, failure will be handled after the loop

        # The finally block executes *after* the try or *after* an except block completes (before loop continues/breaks)
        finally:
            if uploaded_file and uploaded_file.name: # Cleanup after each attempt
                try:
                    # print(f"      Deleting uploaded file: {uploaded_file.name} (in finally)")
                    delete_start = time.monotonic()
                    client.files.delete(name=uploaded_file.name)
                    delete_end = time.monotonic()
                    # print(f"        File deletion took {delete_end - delete_start:.2f}s")
                except Exception as delete_error:
                    print(f"      WARNING: Error deleting file {uploaded_file.name} in finally block: {delete_error}")
            uploaded_file = None # Ensure reference is cleared

    # --- After the Loop --- ##
    # This section is reached if the loop completes normally (all retries failed) or if it broke early
    if last_exception: # Check if an exception was the reason for exiting
        print(f"    Failed to process {chunk_path.name} after {attempts_made} attempts. Last error: {type(last_exception).__name__}")
    else:
         # This case should theoretically not be reached if success returns early
         print(f"    Failed to process {chunk_path.name} after {attempts_made} attempts. Reason unknown (loop finished unexpectedly).")
    return chunk_path, None # Return None for caption on failure

def _generate_video_summary(openai_client, concatenated_captions):
    """Internal helper to generate summary and themes using OpenAI."""
    summary = f"Error: Summarization failed."
    themes = ""

    summary_prompt = f"""
**Objective:** Generate a concise, accurate, and informative overall summary of a video based on a sequence of timed text captions derived from its chunks.

**Input:** You will receive a single block of text containing concatenated captions. Each caption describes a sequential segment of the video and is preceded by its start and end timestamps (e.g., "[00:12.345 - 00:16.789]").

**Task:**
1. Read through the entire sequence of timed captions to understand the video's content flow.
2. Synthesize this information into a single, coherent paragraph summarizing the **entire video**.
3. Focus on identifying:
    * The main subject(s) or characters.
    * The primary actions, events, or topics discussed.
    * The overall narrative arc or progression (beginning, middle, end developments).
    * The central theme, message, or purpose of the video, if discernible.
4. The summary must be **concise** and capture the most crucial information.
5. **Ignore minor repetitive details** mentioned across consecutive captions if they don't represent significant changes or progression. Focus on the essence of what happened.
6. The final output should be **only the summary paragraph**, suitable for providing high-level context when answering user questions about the video. Do not include preamble or explanation.

**Input Captions:**
{concatenated_captions}

**Output Summary:**
"""
    themes_prompt = f"""
Based on the following video captions, identify 3-5 key themes or topics covered in the video.
Return ONLY a comma-separated list of themes/topics, with no numbering, explanations, or preamble.

Example good output: "friendship, betrayal, redemption"

Captions:
{concatenated_captions}
"""

    def call_openai(prompt, max_tok, temp):
        try:
            response = openai_client.chat.completions.create(
                model=SUMMARY_MODEL_NAME,
                messages=[{"role": "user", "content": prompt}],
                temperature=temp, max_tokens=max_tok
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            print(f"      Error calling OpenAI for summarization/themes: {e}")
            return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        summary_future = executor.submit(call_openai, summary_prompt, 500, 0.5)
        themes_future = executor.submit(call_openai, themes_prompt, 100, 0.3)
        summary_res = summary_future.result()
        themes_res = themes_future.result()

    if summary_res: summary = summary_res
    if themes_res: themes = themes_res

    return summary, themes

def generate_captions_and_summary(metadata_json_path):
    """
    Generates captions using Gemini, updates the JSON, generates summary/themes
    using OpenAI, and updates the JSON again.

    Args:
        metadata_json_path (str): Path to the JSON file containing chunk metadata.

    Returns:
        str: The path to the updated JSON metadata file if successful, otherwise None.
    """
    print("\n--- Stage 3: Generating Captions & Summary ---")
    print(f"  Input JSON Path: {metadata_json_path}")

    if not metadata_json_path or not os.path.exists(metadata_json_path):
        print("  Error: Invalid or non-existent metadata JSON path provided.")
        return None

    if not GEMINI_API_KEY or not OPENAI_API_KEY:
         print("  Error: Missing GEMINI_API_KEY or OPENAI_API_KEY. Cannot proceed.")
         return None

    # Initialize clients
    global openai_client # Use the global client if initialized
    try:
        gemini_client = genai.Client(api_key=GEMINI_API_KEY)
        if not openai_client:
            openai_client = OpenAI(api_key=OPENAI_API_KEY)
            print("  Initialized OpenAI client for summarization.")
    except Exception as e:
         print(f"  Error initializing API clients: {e}")
         return None

    # Read JSON data
    try:
        with open(metadata_json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (IOError, json.JSONDecodeError) as e:
        print(f"  Error reading or parsing JSON file {metadata_json_path}: {e}")
        return None

    if "chunks" not in data or not isinstance(data.get("chunks"), list):
         print(f"  Error: JSON file {metadata_json_path} missing or invalid 'chunks' list.")
         # Remove status update here
         # data["processing_status"] = "CAPTIONING_FAILED_BAD_JSON"
         # ... (json write removed) ...
         return None

    # Check current status - simplified: check if captions already exist
    all_chunks_have_caption = False
    if data.get("chunks"):
        all_chunks_have_caption = all('caption' in chunk for chunk in data["chunks"])

    if all_chunks_have_caption and data.get("overall_summary"):
         print("  Captions and summary appear to be already completed. Skipping generation.")
         # Remove status update here
         return metadata_json_path # Return success path
    # else: # Proceed with captioning/summary if needed

    # Determine chunk directory
    json_dir = os.path.dirname(metadata_json_path)
    chunks_dir = Path(json_dir) / "chunks"
    if not chunks_dir.is_dir():
         print(f"  Error: Chunks directory not found at {chunks_dir}")
         # Remove status update here
         # data["processing_status"] = "CAPTIONING_FAILED_NO_CHUNK_DIR"
         # ... (json write removed) ...
         return None

    # --- Caption Generation ---
    # Only run if captions seem incomplete
    run_captioning = not all_chunks_have_caption
    if run_captioning:
        print(f"  Starting caption generation for chunks in {chunks_dir}...")
        caption_start_time = time.monotonic()
        # Remove status update here
        # data["processing_status"] = "CAPTIONING_IN_PROGRESS"
        # ... (immediate write removed) ...

        chunks_to_process = []
        # Use a map for efficient update lookup: chunk_name -> chunk_dict
        json_chunk_map = {chunk.get('chunk_name'): chunk for chunk in data.get('chunks', []) if chunk.get('chunk_name')}

        # Identify chunks needing captions (missing or empty caption field)
        missing_chunk_files = []
        for chunk_name, chunk_meta in json_chunk_map.items():
            if 'caption' not in chunk_meta or not chunk_meta.get('caption'):
                # Construct filename WITH extension for file check
                chunk_filename_with_ext = f"{chunk_name}.mp4"
                chunk_path = chunks_dir / chunk_filename_with_ext
                if chunk_path.is_file():
                    chunks_to_process.append(chunk_path)
                else:
                    print(f"    Warning: Chunk file {chunk_filename_with_ext} listed in JSON but not found at {chunk_path}. Marking caption as null.")
                    chunk_meta['caption'] = None # Mark as missing/failed in the map
                    missing_chunk_files.append(chunk_filename_with_ext)

        if missing_chunk_files:
             data["captioning_warnings"] = data.get("captioning_warnings","") + f" Missing chunk files: {', '.join(missing_chunk_files)};"

        if not chunks_to_process:
             print("  No chunks require captioning (all have captions or files are missing).")
             # Remove complex status updates here
        else:
            print(f"  Found {len(chunks_to_process)} chunks requiring captions.")
            caption_map = {} # Store results: chunk_name_no_ext -> caption
            future_to_chunk = {}

            with ThreadPoolExecutor(max_workers=CAPTION_MAX_WORKERS) as executor:
                for chunk_path in chunks_to_process:
                    future = executor.submit(_process_single_chunk_for_captioning, gemini_client, chunk_path)
                    future_to_chunk[future] = chunk_path

                print(f"    Submitted {len(chunks_to_process)} chunks for captioning...")
                successful_captions = 0
                failed_captions = 0
                completed_count = 0
                total_chunks = len(chunks_to_process)
                for future in as_completed(future_to_chunk):
                    chunk_path = future_to_chunk[future]
                    chunk_name_no_ext = chunk_path.stem # Get name without extension
                    completed_count += 1
                    try:
                        _, caption = future.result()
                        caption_map[chunk_name_no_ext] = caption # Store caption (or None if failed)
                        if caption is not None:
                            successful_captions += 1
                            print(f"    Progress: {completed_count}/{total_chunks} chunks processed (Success: {chunk_path.name})")
                        else:
                            failed_captions += 1
                            print(f"    Progress: {completed_count}/{total_chunks} chunks processed (Failed: {chunk_path.name})")

                    except Exception as exc:
                        failed_captions += 1
                        print(f"    Chunk {chunk_path.name} generated an exception: {exc}")
                        caption_map[chunk_name_no_ext] = None # Mark as failed
                        print(f"    Progress: {completed_count}/{total_chunks} chunks processed (Exception: {chunk_path.name})")


            # Update JSON data in memory with captions
            print("    Updating JSON data with generated captions...")
            for chunk_name_no_ext, caption in caption_map.items():
                 if chunk_name_no_ext in json_chunk_map:
                     json_chunk_map[chunk_name_no_ext]['caption'] = caption
                 else:
                     print(f"    Warning: Processed chunk {chunk_name_no_ext} not found in initial JSON map. Ignoring result.")

            # Ensure all initially identified chunks have a caption status (even if None)
            processed_chunk_names_no_ext = {p.stem for p in chunks_to_process}
            for chunk_name_no_ext, chunk_meta in json_chunk_map.items():
                 if chunk_name_no_ext in processed_chunk_names_no_ext and chunk_name_no_ext not in caption_map:
                     if 'caption' not in chunk_meta or chunk_meta['caption'] is None:
                         print(f"    Warning: Chunk {chunk_name_no_ext} was submitted but has no final caption result. Marking as null.")
                         chunk_meta['caption'] = None


            print(f"    Caption generation completed. Success: {successful_captions}, Failed: {failed_captions}.")
            # Remove complex status updates here
            if failed_captions > 0 or missing_chunk_files:
                 # Store errors if needed, but don't change processing_status
                 if failed_captions > 0:
                      data["captioning_errors"] = data.get("captioning_errors", "") + f"{failed_captions} chunk(s) failed caption generation;"

        caption_end_time = time.monotonic()
        print(f"  Caption generation phase took: {caption_end_time - caption_start_time:.2f} seconds.")
    else:
        print("  Skipping caption generation as all chunks seem to have captions.")

    # --- Summarization ---
    # Only run if summary doesn't exist or is an error
    run_summary = "overall_summary" not in data or not data.get("overall_summary") or "Error:" in data.get("overall_summary","")

    if run_summary:
        print("\n  Starting video summary and theme generation...")
        summary_start_time = time.monotonic()
        # Remove status update here
        # data["processing_status"] = data.get("processing_status", "").replace("_SUMMARY_SKIPPED", "") + "_SUMMARY_IN_PROGRESS"
        # ... (immediate write removed) ...

        # Concatenate available captions chronologically
        concatenated_captions = ""
        # Sort based on the chunk_number from the updated data
        sorted_chunks = sorted(data.get("chunks", []), key=lambda x: x.get("chunk_number", float('inf'))) # Sort Nones last
        captions_available_count = 0
        for chunk in sorted_chunks:
            caption = chunk.get("caption")
            if caption and isinstance(caption, str): # Only include non-empty string captions
                start_ts = chunk.get("start_timestamp", "00:00.000")
                end_ts = chunk.get("end_timestamp", "00:00.000")
                concatenated_captions += f"[{start_ts} - {end_ts}]\n{caption}\n---\n"
                captions_available_count += 1

        if captions_available_count > 0:
            print(f"    Concatenated {captions_available_count} available captions for summarization.")
            summary, themes = _generate_video_summary(openai_client, concatenated_captions)
            data["overall_summary"] = summary
            data["key_themes"] = themes if themes else "Error: Theme generation failed."
            data["summary_generated_at"] = datetime.now().isoformat()
            print("    Summary and themes generated.")
            # Remove status update here
            # data["processing_status"] = data.get("processing_status", "").replace("_SUMMARY_IN_PROGRESS", "") + "_SUMMARY_COMPLETED"
            # if "Error:" in summary or "Error:" in themes:
            #      data["processing_status"] += "_WITH_ERRORS"

        else:
             print("    No valid captions available in JSON to generate summary.")
             data["overall_summary"] = "Error: No valid captions available for summarization."
             data["key_themes"] = ""
             data["summary_generated_at"] = datetime.now().isoformat()
             # Remove status update here
             # data["processing_status"] = data.get("processing_status", "").replace("_SUMMARY_IN_PROGRESS", "") + "_SUMMARY_FAILED_NO_CAPTIONS"

        summary_end_time = time.monotonic()
        print(f"  Summarization phase took: {summary_end_time - summary_start_time:.2f} seconds.")
    else:
        print("  Skipping summary generation as it already exists.")
        # Remove status update here
        # data["processing_status"] = data.get("processing_status", "") + "_SUMMARY_SKIPPED"


    # --- Save Final JSON for Stage 3 ---
    try:
        with open(metadata_json_path, 'w', encoding='utf-8') as f:
             json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"  Successfully saved enriched metadata to {metadata_json_path}")
        print(f"  -> Stage 3 Result: {metadata_json_path}")
        return metadata_json_path
    except IOError as e:
        print(f"  Error writing final JSON data to {metadata_json_path}: {e}")
        print(f"  -> Stage 3 Result: Failed")
        return None

# --- Stage 4: Indexing Captions ---

def initialize_clients():
    """Initialize API clients for OpenAI and Pinecone."""
    global openai_client, pc, pinecone_index, PINECONE_INDEX_HOST # Ensure global variable modification

    # Initialize OpenAI client (if not already done by summary stage)
    if not openai_client:
        if not OPENAI_API_KEY:
            print("ERROR: OPENAI_API_KEY not found for client initialization.")
            raise EnvironmentError("OPENAI_API_KEY is required.")
        try:
            openai_client = OpenAI(api_key=OPENAI_API_KEY)
            print("  Initialized OpenAI client for indexing.")
        except Exception as e:
            print(f"  Error initializing OpenAI client: {e}")
            raise
    else:
        print("  OpenAI client already initialized.")


    # Initialize Pinecone client
    if not pc:
        if not PINECONE_API_KEY:
            print("ERROR: PINECONE_API_KEY not found for client initialization.")
            raise EnvironmentError("PINECONE_API_KEY is required.")
        try:
            pc = Pinecone(api_key=PINECONE_API_KEY)
            print("  Initialized Pinecone client.")
        except Exception as e:
            print(f"  Error initializing Pinecone client: {e}")
            raise
    else:
         print("  Pinecone client already initialized.")

    # Handle Pinecone index host setup and connection
    if not pinecone_index:
        if not PINECONE_INDEX_HOST:
            print("  PINECONE_INDEX_HOST environment variable not set.")
            print("  Checking index status and determining host...")

            # Check if index exists
            print("    Checking existing indexes...")
            start_list_indexes = time.time()
            existing_indexes = pc.list_indexes().names
            end_list_indexes = time.time()
            print(f"    pc.list_indexes().names call took: {end_list_indexes - start_list_indexes:.4f} seconds")

            if INDEX_NAME not in existing_indexes:
                print(f"    Creating index '{INDEX_NAME}'...")
                start_create_index = time.time()
                # Create Pinecone index if it doesn't exist
                pc.create_index(
                    name=INDEX_NAME,
                    dimension=EMBED_DIM,
                    metric="cosine",
                    spec=ServerlessSpec(
                        cloud="aws",
                        region="us-east-1"
                    )
                )
                end_create_index = time.time()
                print(f"    pc.create_index() call took: {end_create_index - start_create_index:.4f} seconds")
                print(f"    Index '{INDEX_NAME}' created. Waiting for it to be ready...")

                # Wait for the index to be ready
                # time.sleep(5) # Initial sleep removed, describe_index handles wait
                max_wait_time = 120
                wait_start_time = time.time()
                while True:
                    if time.time() - wait_start_time > max_wait_time:
                         raise TimeoutError(f"Index '{INDEX_NAME}' did not become ready within {max_wait_time} seconds.")
                    try:
                        start_describe_loop = time.time()
                        index_description = pc.describe_index(INDEX_NAME)
                        end_describe_loop = time.time()
                        # print(f"      (describe_index in loop took: {end_describe_loop - start_describe_loop:.4f}s)")
                        if index_description.status['ready']:
                            print(f"    Index '{INDEX_NAME}' is ready.")
                            break
                        else:
                             print(f"    Index status: {index_description.status}. Waiting...")

                    except Exception as e:
                        print(f"      Waiting for index... (Error describing: {e})")

                    print("    Waiting 5 seconds before next check...")
                    time.sleep(5)
            else:
                print(f"    Index '{INDEX_NAME}' already exists.")

            # Get the index host
            print(f"    Describing index '{INDEX_NAME}' to get its host...")
            start_describe_final = time.time()
            index_description = pc.describe_index(INDEX_NAME)
            end_describe_final = time.time()
            print(f"    pc.describe_index() took: {end_describe_final - start_describe_final:.4f} seconds")
            PINECONE_INDEX_HOST = index_description.host # Update global var
            print(f"    Determined index host: {PINECONE_INDEX_HOST}")

            # Set environment variable for the current process
            os.environ['PINECONE_INDEX_HOST'] = PINECONE_INDEX_HOST
            print(f"      Set os.environ['PINECONE_INDEX_HOST'] for the current process.")

            # Update .env.local file
            try:
                set_key(dotenv_path, "PINECONE_INDEX_HOST", PINECONE_INDEX_HOST)
                print(f"      Updated PINECONE_INDEX_HOST in {dotenv_path.name} for local persistence.")
            except Exception as e:
                print(f"      Warning: Could not update {dotenv_path.name}: {e}")
                print(f"      You may need to set PINECONE_INDEX_HOST manually in this file for future runs.")
        else:
            print(f"  Using existing PINECONE_INDEX_HOST from environment: {PINECONE_INDEX_HOST}")

        # Connect to the index
        print(f"  Connecting to Pinecone index '{INDEX_NAME}' via host: {PINECONE_INDEX_HOST}")
        try:
            pinecone_index = pc.Index(host=PINECONE_INDEX_HOST)
            # Perform a quick operation to confirm connection
            pinecone_index.describe_index_stats()
            print(f"  Successfully connected to index '{INDEX_NAME}'.")
        except Exception as e:
            print(f"  Error connecting to Pinecone index '{INDEX_NAME}': {e}")
            raise
    else:
        print("  Pinecone index connection already established.")


def get_embedding(caption_text: str, model_name: str) -> list[float]:
    """Helper function to get embedding for a caption text using the global client."""
    global openai_client
    if not openai_client:
        raise RuntimeError("OpenAI client is not initialized. Call initialize_clients first.")
    try:
        response = openai_client.embeddings.create(
            input=caption_text,
            model=model_name
        )
        # print(f"    Embedding created for caption snippet: {caption_text[:50]}...")
        return response.data[0].embedding
    except Exception as e:
        print(f"    ERROR getting embedding for caption: {caption_text[:50]}... Error: {e}")
        # Consider logging the full caption text here for debugging if needed
        raise RuntimeError(f"Failed to get embedding for caption: {caption_text[:50]}...") from e

def index_captions_in_pinecone(enriched_metadata_json_path: str) -> str | None:
    """
    Processes captions from the enriched JSON, generates embeddings, indexes
    them into Pinecone, and updates the JSON status.

    Args:
        enriched_metadata_json_path (str): Path to the JSON file enriched
                                           with captions and summary.

    Returns:
        str: The path to the JSON metadata file if indexing was successful
             or skipped, otherwise None.
    """
    print("\n--- Stage 4: Indexing Captions in Pinecone ---")
    print(f"  Input JSON Path: {enriched_metadata_json_path}")

    global openai_client, pc, pinecone_index # Use global clients

    # Initialize clients if not already done
    try:
        initialize_clients()
    except Exception as e:
        print(f"  Failed to initialize API clients: {e}")
        # Remove status update here
        # try: ... data["processing_status"] = "INDEXING_FAILED_CLIENT_INIT" ...
        return None

    if not openai_client or not pc or not pinecone_index:
        print("  Error: API clients could not be initialized or connected.")
        # Remove status update here
        # try: ... data["processing_status"] = "INDEXING_FAILED_CLIENT_CONNECT" ...
        return None

    json_file_path = Path(enriched_metadata_json_path)
    start_time = time.time()

    # Load JSON data
    try:
        with open(json_file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print(f"  Error reading/decoding JSON {json_file_path}: {e}")
        return None

    # Remove overall status update here
    # final_caption_summary_status = data.get("processing_status", "") # No longer needed

    # Check if already indexed (using the specific indexing_status)
    if data.get("indexing_status") == "COMPLETED":
        print(f"  Indexing status is already COMPLETED for {json_file_path.name}. Skipping.")
        # If skipping, still mark overall processing as FINISHED at the end
    elif data.get("indexing_status") == "SKIPPED_NO_CAPTIONS":
        print(f"  Indexing status is SKIPPED_NO_CAPTIONS for {json_file_path.name}. Skipping.")
        # If skipping, still mark overall processing as FINISHED at the end
    elif data.get("indexing_status") == "SKIPPED_ALREADY_INDEXED":
        print(f"  Indexing status is SKIPPED_ALREADY_INDEXED for {json_file_path.name}. Skipping.")
        # If skipping, still mark overall processing as FINISHED at the end
    else:
        # Proceed with indexing logic only if not already completed/skipped

        # Set indexing_status to IN_PROGRESS
        data["indexing_status"] = "IN_PROGRESS"
        try: # Write status update immediately
            with open(json_file_path, 'w', encoding='utf-8') as f: json.dump(data, f, indent=2)
        except Exception as e: print(f"  Warning: Failed to update JSON status for indexing start: {e}")

        # Extract required data (video_id, chunks)
        video_id = data.get("video_id")
        if not video_id:
            print(f"  Error: No valid 'video_id' found in {json_file_path}.")
            data["indexing_status"] = "FAILED_NO_VIDEO_ID"
            try:
                with open(json_file_path, 'w', encoding='utf-8') as f: json.dump(data, f, indent=2)
            except Exception as e: print(f"  Warning: Failed to update JSON status: {e}")
            return None # Critical error, stop pipeline

        chunks = data.get("chunks") or []
        if not isinstance(chunks, list):
            print(f"  Error: No valid 'chunks' list found in {json_file_path}.")
            data["indexing_status"] = "FAILED_NO_CHUNKS"
            try:
                with open(json_file_path, 'w', encoding='utf-8') as f: json.dump(data, f, indent=2)
            except Exception as e: print(f"  Warning: Failed to update JSON status: {e}")
            return None # Critical error, stop pipeline

        print(f"  Loaded {len(chunks)} chunks from {json_file_path.name} for video_id: {video_id}")

        # Filter chunks that have valid captions and chunk_name
        chunks_with_captions = [chunk for chunk in chunks if chunk.get("caption") and isinstance(chunk.get("caption"), str) and chunk.get("chunk_name")]
        if not chunks_with_captions:
            print("  No chunks with valid captions found to index. Skipping Pinecone operations.")
            data["indexing_status"] = "SKIPPED_NO_CAPTIONS" # Update specific status
            data["indexing_completed_at"] = datetime.now().isoformat()
            # Proceed to final update section to mark overall as FINISHED
        else:
            # Determine new vectors to process by checking existing IDs in Pinecone
            # Use the extension-less chunk_name from JSON as the ID
            potential_ids = [chunk["chunk_name"] for chunk in chunks_with_captions]
            existing_ids = set()
            chunks_to_process = [] # Only chunks that are new AND have captions
            fetch_failed = False # Added flag

            if not potential_ids:
                print("  No valid chunk_names found in chunks with captions. Skipping check for existing IDs.") # Should not happen if chunks_with_captions is not empty
            else:
                print(f"  Checking existence of {len(potential_ids)} potential IDs in Pinecone for video_id '{video_id}'...")
                ids_to_fetch = list(potential_ids)
                try:
                    # Batch fetching if necessary (Pinecone fetch limit is 1000)
                    fetched_vectors = {}
                    fetch_batch_size = 1000
                    for i in range(0, len(ids_to_fetch), fetch_batch_size):
                         batch_ids = ids_to_fetch[i:i + fetch_batch_size]
                         print(f"    Fetching batch {i // fetch_batch_size + 1}...")
                         fetch_start = time.time()
                         fetch_response = pinecone_index.fetch(ids=batch_ids)
                         fetch_end = time.time()
                         fetched_vectors.update(fetch_response.vectors)
                         print(f"      Batch fetch took: {fetch_end - fetch_start:.4f} seconds, got {len(fetch_response.vectors)} vectors.")


                    existing_ids = set(fetched_vectors.keys())
                    count_of_existing_ids = len(existing_ids)
                    # Correct calculation for new IDs
                    # count_of_new_ids = len(potential_ids) - count_of_existing_ids
                    chunks_to_process = [chunk for chunk in chunks_with_captions if chunk["chunk_name"] not in existing_ids]
                    count_of_new_ids = len(chunks_to_process) # Count of chunks *not* found

                    print(f"    Found {count_of_existing_ids} existing IDs among the potential {len(potential_ids)} for this video.")
                    print(f"    Expecting to add {count_of_new_ids} new vectors.")

                    # chunks_to_process = [chunk for chunk in chunks_with_captions if chunk["chunk_name"] not in existing_ids] # Already done above
                    print(f"    Identified {len(chunks_to_process)} new chunks with captions to process and index.")

                except Exception as e:
                    fetch_failed = True
                    print(f"  Warning: Could not fetch existing IDs from Pinecone: {e}")
                    print("    Proceeding assuming all chunks with captions might be new (will attempt upsert).")
                    chunks_to_process = chunks_with_captions
                    count_of_new_ids = len(chunks_to_process)
                    data["indexing_warnings"] = data.get("indexing_warnings", "") + f"Failed to fetch existing IDs: {e};"


            # Process and index new chunks
            total_upserted_count = 0
            indexing_errors = [] # Changed variable name
            upsert_failed = False # Added flag
            embedding_failed = False # Added flag

            if chunks_to_process:
                print(f"\n  Processing {len(chunks_to_process)} new chunks for indexing...")
                vectors_to_upsert = []

                start_embedding_time = time.time()
                captions_to_embed = [chunk['caption'] for chunk in chunks_to_process]
                embeddings = {} # Map: {caption_text: embedding_vector}

                print(f"    Requesting embeddings for {len(captions_to_embed)} captions...")
                try:
                    with concurrent.futures.ThreadPoolExecutor(max_workers=INDEXING_MAX_EMBEDDING_WORKERS) as executor:
                        future_to_caption = {executor.submit(get_embedding, caption, EMBED_MODEL_NAME): caption for caption in captions_to_embed}
                        results_count = 0 # Added for progress
                        total_to_embed = len(future_to_caption) # Added for progress
                        for future in concurrent.futures.as_completed(future_to_caption):
                            caption_text = future_to_caption[future]
                            results_count += 1 # Added for progress
                            try:
                                embedding_vector = future.result()
                                embeddings[caption_text] = embedding_vector # Store result in map
                                # print(f"      Embedding progress: {results_count}/{total_to_embed} ({caption_text[:30]}...)") # Optional verbose log
                            except Exception as exc:
                                print(f"      ERROR processing caption embedding: {caption_text[:50]}... Exception: {exc}")
                                indexing_errors.append(f"Embedding failed for caption starting: {caption_text[:50]}")
                                embedding_failed = True # Mark failure, but continue processing others
                                # Optionally store the failed caption to mark in JSON later?
                            print(f"    Retrieved {len(embeddings)} embeddings (may include failures).")

                except Exception as e: # Catch errors during thread pool setup/management
                    print(f"  An error occurred during concurrent embedding setup: {e}")
                    embedding_failed = True
                    indexing_errors.append(f"Embedding thread pool error: {e}")

                embedding_complete_time = time.time()
                print(f"    Concurrent embedding took: {embedding_complete_time - start_embedding_time:.4f} seconds.")

                if embedding_failed:
                     print("    One or more embedding tasks failed. Proceeding with successful embeddings.")
                     # Remove status update here: data["indexing_status"] = "IN_PROGRESS_EMBEDDING_ERRORS"

                # Prepare vectors for upsert, skipping those without embeddings
                print("    Preparing vectors for Pinecone upsert...")
                prepare_start_time = time.time()
                vectors_to_upsert = []
                embedding_lookup_failures = 0
                for chunk in chunks_to_process:
                    chunk_name = chunk.get("chunk_name") # Extension-less ID
                    caption = chunk.get("caption")
                    vector = embeddings.get(caption) # Look up using the caption text

                    if vector is None:
                         # This chunk's embedding failed or was missing
                         if caption: # Only log if caption existed
                             print(f"    Warning: Embedding not found for chunk '{chunk_name}'. Skipping upsert.")
                             embedding_lookup_failures += 1
                         continue

                    if not chunk_name: continue # Should not happen

                    # Prepare metadata for Pinecone
                    metadata = {
                        "caption": caption,
                        "start_timestamp": chunk.get("start_timestamp", "Unknown"),
                        "end_timestamp": chunk.get("end_timestamp", "Unknown"),
                        "chunk_name": chunk_name, # Store the extension-less name
                        "video_id": video_id,
                        "normalized_start_time": chunk.get("normalized_start_time"),
                        "normalized_end_time": chunk.get("normalized_end_time"),
                        "chunk_duration_seconds": chunk.get("chunk_duration_seconds"),
                        "chunk_number": chunk.get("chunk_number")
                    }
                    metadata = {k: v for k, v in metadata.items() if v is not None}

                    vectors_to_upsert.append({
                        "id": chunk_name, # Use extension-less name as Pinecone ID
                        "values": vector,
                        "metadata": metadata
                    })

                prepare_end_time = time.time()
                print(f"      Vector preparation took: {prepare_end_time - prepare_start_time:.4f} seconds.")
                if embedding_lookup_failures > 0:
                     print(f"      Skipped {embedding_lookup_failures} vectors due to missing embeddings.")
                     data["indexing_warnings"] = data.get("indexing_warnings", "") + f"{embedding_lookup_failures} chunks skipped due to embedding errors;"

                # Upsert batches
                if vectors_to_upsert:
                     upsert_batch_start_time = time.time()
                     num_batches = math.ceil(len(vectors_to_upsert) / INDEXING_BATCH_SIZE)
                     print(f"    Starting upsert of {len(vectors_to_upsert)} vectors in {num_batches} batches...")

                     for i in range(0, len(vectors_to_upsert), INDEXING_BATCH_SIZE):
                         batch_num = (i // INDEXING_BATCH_SIZE) + 1
                         batch_vectors = vectors_to_upsert[i : i + INDEXING_BATCH_SIZE]
                         if not batch_vectors: continue

                         print(f"      Upserting batch {batch_num}/{num_batches} ({len(batch_vectors)} vectors)...")
                         try:
                             start_upsert_batch = time.time()
                             upsert_response = pinecone_index.upsert(vectors=batch_vectors)
                             end_upsert_batch = time.time()
                             batch_duration = end_upsert_batch - start_upsert_batch # Define batch_duration
                             upserted_in_batch = upsert_response.upserted_count
                             total_upserted_count += upserted_in_batch or 0 # Handle None case
                             print(f"        Batch {batch_num} upsert took: {batch_duration:.4f} seconds. Upserted: {upserted_in_batch} vectors.")
                             if upserted_in_batch != len(batch_vectors):
                                  print(f"        WARNING: Upsert count mismatch in batch {batch_num}. Expected {len(batch_vectors)}, got {upserted_in_batch}.")
                                  indexing_errors.append(f"Upsert count mismatch in batch {batch_num}")
                                  upsert_failed = True # Mark as partial failure
                         except Exception as e:
                             print(f"      Error upserting batch {batch_num} to Pinecone: {e}")
                             indexing_errors.append(f"Upsert failed for batch {batch_num}: {e}")
                             upsert_failed = True # Mark failure, but continue to next batch? Or stop? Let's stop for now.
                             break # Stop upserting if a batch fails

                     upsert_batch_end_time = time.time()
                     print(f"    Finished upserting. Total upserted in this run: {total_upserted_count} vectors in {upsert_batch_end_time - upsert_batch_start_time:.4f} seconds.")
                     data["vectors_indexed_count"] = data.get("vectors_indexed_count", 0) + total_upserted_count
                else:
                    print("    No vectors prepared for upsert (likely due to embedding failures or no new chunks).")


                # Update specific indexing status based on outcomes
                if upsert_failed or embedding_failed or fetch_failed:
                    data["indexing_status"] = "COMPLETED_WITH_ERRORS"
                    data["indexing_errors"] = indexing_errors
                else:
                     # If no errors occurred during this run
                     if chunks_to_process or fetch_failed: # If we attempted processing or fetch failed
                         data["indexing_status"] = "COMPLETED"
                     else: # If fetch succeeded and chunks_to_process was empty
                         data["indexing_status"] = "SKIPPED_ALREADY_INDEXED"

                data["indexing_completed_at"] = datetime.now().isoformat()

        # --- Final Update Section for Stage 4 ---
        # This section is reached if indexing completed, was skipped, or finished with errors
        print(f"  Attempting final update for {json_file_path.name}...")
        try:
            # Re-read data just in case it was modified by another process (though unlikely here)
            # Or just use the 'data' dictionary we've been modifying
            with open(json_file_path, 'r', encoding='utf-8') as f:
                current_data = json.load(f)

            # Update the main processing_status to FINISHED
            current_data["processing_status"] = "FINISHED"

            # Merge any specific indexing status updates we determined above
            if "indexing_status" in data: # If indexing logic ran and set a status
                current_data["indexing_status"] = data["indexing_status"]
            if "indexing_completed_at" in data:
                current_data["indexing_completed_at"] = data["indexing_completed_at"]
            if "indexing_errors" in data:
                current_data["indexing_errors"] = data["indexing_errors"]
            if "indexing_warnings" in data:
                 current_data["indexing_warnings"] = data.get("indexing_warnings","") + data["indexing_warnings"] # Append warnings
            if "vectors_indexed_count" in data:
                current_data["vectors_indexed_count"] = data["vectors_indexed_count"]


            # Write the final updates
            with open(json_file_path, "w", encoding="utf-8") as f:
                 json.dump(current_data, f, indent=2, ensure_ascii=False)
            print(f"  Successfully updated final status to 'FINISHED' in {json_file_path.name}")

        except Exception as e:
            print(f"  Warning: Could not update JSON file {json_file_path.name} with final status: {e}")
            return None # Indicate JSON write failure


        end_time = time.time()
        print(f"  Caption indexing stage completed or skipped in {end_time - start_time:.2f} seconds")
        print(f"  -> Stage 4 Result: {enriched_metadata_json_path}")
        return enriched_metadata_json_path # Return path indicating success or skip completion

# --- Main Execution Block ---
def main_pipeline(tiktok_url): # Changed to accept URL directly
    """Runs the main technical pipeline for a given TikTok URL."""
    pipeline_start_time = time.monotonic()
    print("--- Starting Technical Pipeline ---")
    print(f"Processing URL: {tiktok_url}")

    # Define base path for downloads relative to the script location
    script_dir = os.path.dirname(__file__) if "__file__" in locals() else os.getcwd() # Handle interactive use
    videos_base_folder = os.path.join(script_dir, "video-data")
    try:
        os.makedirs(videos_base_folder, exist_ok=True) # Ensure base folder exists
        print(f"Ensured base video directory exists: {videos_base_folder}")
    except OSError as e:
        print(f"Fatal Error: Could not create base video directory {videos_base_folder}: {e}")
        return # Stop execution if base directory can't be created

    # === Stage 0: URL Input === (Renamed from Stage 1)
    discovered_url = tiktok_url # Use the URL passed as argument
    print("Stage 0 (URL Input): Using provided URL.")

    # === Stage 1: Download Video ===
    downloaded_video_path = None
    video_id = None
    initial_json_path = None
    if discovered_url:
        downloaded_video_path, video_id, initial_json_path = download_video_from_url(discovered_url, videos_base_folder)
        print(f"Stage 1 (download_video_from_url) result: VideoPath={downloaded_video_path}, VideoID={video_id}, JsonPath={initial_json_path}")
    else:
        print("\nError: No URL provided to pipeline.")
        return

    # === Stage 2: Chunk Video & Generate Metadata ===
    updated_json_path_stage2 = None # Renamed variable
    if downloaded_video_path and video_id and initial_json_path:
        updated_json_path_stage2 = chunk_video_and_generate_metadata(downloaded_video_path, video_id, initial_json_path)
        print(f"Stage 2 (chunk_video_and_generate_metadata) result: Updated JSON Path={updated_json_path_stage2}")
    else:
        print("\nSkipping Stage 2 & subsequent stages: Download or initial JSON creation failed in Stage 1.")
        return

    # === Stage 3: Generate Captions & Summary ===
    updated_json_path_stage3 = None # Renamed variable
    if updated_json_path_stage2: # Use path from stage 2
         updated_json_path_stage3 = generate_captions_and_summary(updated_json_path_stage2)
         print(f"Stage 3 (generate_captions_and_summary) result: Updated JSON Path={updated_json_path_stage3}")
    else:
         print("\nSkipping Stage 3 & subsequent stages: Chunking/Metadata update failed in Stage 2.")
         return

    # === Stage 4: Index Captions ===
    final_json_path_after_indexing = None
    if updated_json_path_stage3: # Use path from stage 3
        final_json_path_after_indexing = index_captions_in_pinecone(updated_json_path_stage3)
        print(f"Stage 4 (index_captions_in_pinecone) result: Final JSON Path={final_json_path_after_indexing}")
    else:
        print("\nSkipping Stage 4: Captioning/Summarization failed in Stage 3.")
        return

    # --- Pipeline End ---
    pipeline_end_time = time.monotonic()
    elapsed_time = pipeline_end_time - pipeline_start_time
    print(f"\n--- Technical Pipeline finished in {elapsed_time:.2f} seconds ---")
    if final_json_path_after_indexing:
         print(f"Final JSON artifact: {final_json_path_after_indexing}")
         # You might want to print the final status from the JSON here
         try:
             with open(final_json_path_after_indexing, 'r') as f:
                 final_data = json.load(f)
             print(f"  Final Processing Status: {final_data.get('processing_status', 'N/A')}")
             print(f"  Final Indexing Status: {final_data.get('indexing_status', 'N/A')}")
         except Exception as e:
             print(f"  Could not read final JSON status: {e}")
    else:
         print("Pipeline finished, but final JSON path is not available (likely due to a failure in the pipeline).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Process TikTok video URL for RAG Q&A pipeline.")
    parser.add_argument("tiktok_url", help="The full URL of the TikTok video to process.")
    args = parser.parse_args()

    # Run the main pipeline function directly
    main_pipeline(args.tiktok_url)