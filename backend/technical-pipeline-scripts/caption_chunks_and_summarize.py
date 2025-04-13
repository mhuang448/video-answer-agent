import base64
import os
import time
import json
from google import genai
from google.genai import types
from google.api_core import exceptions as google_exceptions # Added for specific exceptions
from dotenv import load_dotenv
from pathlib import Path
import concurrent.futures
import random # Added for jitter in backoff
from httpx import WriteTimeout, ReadTimeout # Added ReadTimeout

# Configuration
# TARGET_DIRECTORY = Path("videos/jadewellz-7485227592648248622/chunks")
# TARGET_DIRECTORY = Path("videos/mauricioislasoficial-7484114461347941687/chunks")
# TARGET_DIRECTORY = Path("videos/maxpreps-7489213523369774366/chunks")
# TARGET_DIRECTORY = Path("videos/petfunnyrecording507-7457352740675620139/chunks")
# TARGET_DIRECTORY = Path("videos/scare.prank.us66-7437112939582180640/chunks")
# TARGET_DIRECTORY = Path("videos/aichifan33-7486040114695507242/chunks")
# TARGET_DIRECTORY = Path("videos/zachchoicook6-7485701580923145494/chunks")
TARGET_DIRECTORY = Path("videos/brad_podray-7488978108121500958/chunks")

MODEL_NAME = "gemini-2.5-pro-preview-03-25" # "gemini-2.5-pro-exp-03-25" # Using gemini 2.5 pro for best multimodal support
MAX_WORKERS = 8 # Max concurrent API calls
MAX_RETRIES = 5 # Maximum number of retries for processing a chunk
INITIAL_BACKOFF_SECONDS = 2 # Initial delay for retries



dotenv_path = ".env.local"
load_dotenv(dotenv_path)
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY not found in environment variables or .env.local")

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY not found in environment variables or .env.local")

# --- Helper function to handle API interaction for a single file ---
def process_single_chunk(client, chunk_path: Path):
    """Uploads, processes, captions, and deletes a single video chunk with retries."""
    print(f"--- Processing chunk: {chunk_path.name} ---")
    uploaded_file = None
    last_exception = None
    attempts_made = 0 # Counter for actual attempts

    for attempt in range(MAX_RETRIES):
        attempts_made = attempt + 1 # Track the current attempt number
        uploaded_file = None # Ensure uploaded_file is reset for each attempt
        try:
            # --- Debug: Wrap upload ---
            try:
                print(f"[{attempts_made}/{MAX_RETRIES}] Uploading {chunk_path.name}...")
                uploaded_file = client.files.upload(file=chunk_path)
                print(f"Uploaded: {uploaded_file.name} ({uploaded_file.display_name}) - Attempt {attempts_made}")
            except Exception as upload_err:
                print(f"\nDEBUG: Error during client.files.upload on attempt {attempts_made}: {upload_err}")
                last_exception = upload_err # Store exception before re-raising
                raise # Re-raise the exception to be caught by the outer handler
            # --- End Debug ---

            # --- Debug: Wrap status polling ---
            try:
                print(f"Waiting for file processing...")
                polling_interval = 2 # Start with 2 seconds
                max_polling_time = 300 # 5 minutes max wait
                elapsed_time = 0
                while uploaded_file.state.name == "PROCESSING":
                    print(".", end="", flush=True)
                    time.sleep(polling_interval)
                    elapsed_time += polling_interval
                    # --- Debug: Wrap file.get ---
                    try:
                        uploaded_file = client.files.get(name=uploaded_file.name)
                    except Exception as get_err:
                        print(f"\nDEBUG: Error during client.files.get on attempt {attempts_made}: {get_err}")
                        last_exception = get_err # Store exception before re-raising
                        raise # Re-raise
                    # --- End Debug ---
                    if elapsed_time > max_polling_time:
                         # Store TimeoutError before raising
                         last_exception = TimeoutError(f"File {uploaded_file.name} processing timed out after {max_polling_time}s.")
                         raise last_exception
            except Exception as poll_err:
                print(f"\nDEBUG: Error during status polling loop on attempt {attempts_made}: {poll_err}")
                # Exception already stored if it came from inner try/excepts
                if last_exception is None: last_exception = poll_err
                raise # Re-raise
            # --- End Debug ---


            if uploaded_file.state.name == "FAILED":
                print(f"\nFile processing failed: {uploaded_file.state.name}")
                # Don't return immediately, let finally block handle cleanup
                last_exception = Exception(f"File processing failed with state: {uploaded_file.state.name}")
                break # Exit the loop, will go to finally then the failure message outside loop

            elif uploaded_file.state.name != "ACTIVE":
                 print(f"\nFile {uploaded_file.name} is not ACTIVE. Current state: {uploaded_file.state.name}")
                 # Don't return immediately, let finally block handle cleanup
                 last_exception = Exception(f"File is not ACTIVE. State: {uploaded_file.state.name}")
                 break # Exit the loop, will go to finally then the failure message outside loop

            print(f"\nFile {uploaded_file.name} is ACTIVE.")

            # --- Debug: Wrap caption generation ---
            caption = None
            try:
                print("Generating caption...")
                contents = [
                    types.Content(
                        role="user",
                        parts=[
                            types.Part.from_uri(
                                file_uri=uploaded_file.uri,
                                mime_type=uploaded_file.mime_type,
                            ),
                        ],
                    ),
                    types.Content(
                        role="user",
                        parts=[
                            types.Part.from_text(text="""Analyze the provided video clip. Generate a single block of highly descriptive text, specifically crafted as an accessible caption for blind or visually impaired users.

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
"""),
                        ],
                    )
                ]
                generate_content_config = types.GenerateContentConfig(
                    response_mime_type="text/plain",
                )

                response_chunks = client.models.generate_content_stream(
                    model=MODEL_NAME,
                    contents=contents,
                    config=generate_content_config,
                )

                caption_parts = []
                for chunk in response_chunks:
                    if hasattr(chunk, 'text') and chunk.text is not None:
                        caption_parts.append(chunk.text)
                    else:
                        print(f"\nWarning: Received unexpected chunk structure or None text for {chunk_path.name}. Safety block?")
                        if hasattr(chunk, 'prompt_feedback') and chunk.prompt_feedback:
                            print(f"Prompt Feedback: {chunk.prompt_feedback}")
                caption = "".join(caption_parts)

                if not caption:
                    print(f"\nWarning: Caption generation resulted in empty string for {chunk_path.name}.")
                    last_exception = ValueError("Caption generation resulted in empty string.")
                    continue # Go to next retry iteration (if any remain)

            except (TypeError, google_exceptions.GoogleAPICallError) as gen_err:
                 print(f"\nDEBUG: Error during caption generation section on attempt {attempts_made} (TypeError or API Call Error): {gen_err}")
                 last_exception = gen_err
                 # No need to delete file here, let finally block handle it
                 raise # Re-raise to be caught by the main retry logic below
            # --- End Debug ---

            print("Caption generated successfully.") # Changed message slightly for clarity
            # SUCCESS! Let finally block handle cleanup.
            return chunk_path, caption

        # --- Main Exception Handling for Retries ---
        # Consolidated handler for all known retryable exceptions
        except (google_exceptions.RetryError,
                google_exceptions.DeadlineExceeded,
                google_exceptions.ServiceUnavailable,
                google_exceptions.ServerError, # Includes 503 Service Unavailable
                google_exceptions.ResourceExhausted, # Specific 429 error
                google_exceptions.ClientError, # General 4xx errors (catches 429 if not caught by ResourceExhausted)
                TimeoutError, # Includes polling timeout
                WriteTimeout, # httpx timeout during upload
                ReadTimeout, # httpx timeout during response reading
                KeyError # Includes the observed 'x-goog-upload-status' error
                ) as e:
            # Log that this specific, retryable block was entered
            print(f"\nDEBUG: Caught by consolidated retryable exception handler on attempt {attempts_made}: {type(e).__name__}")
            last_exception = e
            print(f"Retrying ({attempts_made}/{MAX_RETRIES}) for {chunk_path.name} due to retryable error: {type(e).__name__} - {e}")
            # Backoff logic...
            backoff_time = INITIAL_BACKOFF_SECONDS * (2 ** attempt) + random.uniform(0, 1)
            print(f"Waiting {backoff_time:.2f} seconds before next attempt...")
            time.sleep(backoff_time)
            # Loop continues to next attempt automatically

        except Exception as e:
            # Log that the generic block was entered
            print(f"\nDEBUG: Caught by generic Exception handler on attempt {attempts_made}: {type(e).__name__}")
            last_exception = e
            print(f"Caught unhandled/non-retryable exception on attempt {attempts_made} for {chunk_path.name}: {type(e).__name__} - {e}")
            break # Exit retry loop for non-retryable errors

        # The finally block handles cleanup after each attempt's try/except block completes OR if loop breaks/returns
        finally:
            # Delete only if the file object exists and has a name
            if uploaded_file and uploaded_file.name:
                # --- Debug: Wrap delete ---
                try:
                    print(f"Deleting uploaded file in finally block: {uploaded_file.name} (after attempt {attempts_made})")
                    client.files.delete(name=uploaded_file.name)
                    print("File deleted in finally block.")
                    uploaded_file = None # Ensure it's marked as deleted
                except Exception as delete_error:
                    # Log warning if deletion fails, but don't prevent script completion
                    print(f"\nWARNING: Error during client.files.delete in finally block for {uploaded_file.name}: {delete_error}")
                # --- End Debug ---

    # If the loop finished without returning successfully (either exhausted retries or broke early)
    # Use the actual number of attempts made
    print(f"\nFailed to process {chunk_path.name} after {attempts_made} attempt(s). Last error: {type(last_exception).__name__} - {last_exception}")
    return chunk_path, None

# --- Helper function to get JSON path from chunks directory ---
def get_video_json_path(chunks_directory):
    """
    Get the path to the JSON file for a video based on its chunks directory.
    
    Args:
        chunks_directory: Path object to the directory containing video chunks
        
    Returns:
        Path object to the JSON file or None if not found
    """
    if not chunks_directory or not chunks_directory.parent:
        return None
        
    parent_directory = chunks_directory.parent
    json_filename = f"{parent_directory.name}.json"
    json_path = parent_directory / json_filename
    
    return json_path if json_path.is_file() else None

# --- Video Summarization Function ---
def generate_video_summary(json_path):
    """
    Generate an overall summary of the video from all of its caption chunks.
    
    Args:
        json_path: Path to the JSON file containing video metadata and captions.
    """
    start_time = time.monotonic() # Record start time
    print(f"\n--- Generating overall video summary from captions ---")
    
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"Error: JSON file not found at {json_path}")
        return
    except json.JSONDecodeError as e:
        print(f"Error decoding JSON from {json_path}: {e}")
        return

    # Check if we already have a summary to avoid duplicate work
    if "overall_summary" in data and data["overall_summary"]:
        print(f"Video already has a summary. Skipping summarization.")
        return
        
    # --- Concatenate Captions ---
    concatenated_captions = ""
    # Sort chunks by chunk_number to ensure chronological order
    sorted_chunks = sorted(data.get("chunks", []), key=lambda x: x.get("chunk_number", 0))
    
    for chunk in sorted_chunks:
        caption = chunk.get("caption")
        if not caption:
            continue  # Skip chunks without captions
            
        start_ts = chunk.get("start_timestamp", "00:00.000")
        end_ts = chunk.get("end_timestamp", "00:00.000")
        concatenated_captions += f"[{start_ts} - {end_ts}]\n{caption}\n---\n"

    if not concatenated_captions:
        print("No captions found in JSON to generate summary.")
        data["overall_summary"] = "Error: No captions available for summarization."
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return

    print(f"Concatenated captions start:\n{concatenated_captions[:200]}")
    print(f"Concatenated captions end:\n{concatenated_captions[-200:]}")

    # --- Initialize OpenAI client ---
    try:
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY)
    except ImportError:
        print("Error: OpenAI package not installed. Run: pip install openai")
        return
    except Exception as e:
        print(f"Error initializing OpenAI client: {e}")
        return

    # --- Prepare LLM Prompt ---
    final_prompt = f"""
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
    # --- Call LLM API ---
    summarization_model = "gpt-4o-mini"  # Efficient model with sufficient context window
    
    # Define functions for each API call
    def generate_summary(prompt):
        try:
            print(f"Generating summary with {summarization_model}...")
            response = client.chat.completions.create(
                model=summarization_model,
                messages=[
                    {"role": "system", "content": "You are a helpful assistant skilled at summarizing video content from timed captions."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.5,  # Balanced between creativity and accuracy
                max_tokens=500    # Reasonable length for a summary
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            print(f"Error calling OpenAI API for summary: {e}")
            return f"Error: Could not generate summary - {e}"

    def extract_themes(captions):
        try:
            themes_prompt = f"""
Based on the following video captions, identify 3-5 key themes or topics covered in the video.
Return ONLY a comma-separated list of themes/topics, with no numbering, explanations, or preamble.

Example good output: "friendship, betrayal, redemption"

Captions:
{captions}
"""
            print("Extracting key themes and topics...")
            response = client.chat.completions.create(
                model=summarization_model,
                messages=[
                    {"role": "system", "content": "You extract key themes and topics from video content."},
                    {"role": "user", "content": themes_prompt}
                ],
                temperature=0.3,  # Lower temperature for more consistent results
                max_tokens=100    # Themes should be concise
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            print(f"Error extracting themes: {e}")
            return ""

    # Execute both API calls concurrently
    summary = ""
    themes = ""
    
    print(f"Sending {len(concatenated_captions)} characters of caption text to API...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        # Submit both tasks
        summary_future = executor.submit(generate_summary, final_prompt)
        themes_future = executor.submit(extract_themes, concatenated_captions)
        
        # Wait for both to complete and get results
        for future in concurrent.futures.as_completed([summary_future, themes_future]):
            try:
                if future == summary_future:
                    summary = future.result()
                    print("Summary generated successfully.")
                elif future == themes_future:
                    themes = future.result()
                    if themes:
                        print("Themes extracted successfully.")
            except Exception as e:
                print(f"Error in concurrent API call: {e}")

    # --- Update and Save JSON ---
    data["overall_summary"] = summary
    if themes:
        data["key_themes"] = themes
        
    # Add timestamp of when summary was generated
    from datetime import datetime
    data["summary_generated_at"] = datetime.now().isoformat()

    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"JSON file {json_path} updated with overall summary and themes.")
    
    # Print a preview of the summary
    print("\nGenerated Summary Preview:")
    print("-------------------------")
    print(summary[:300] + "..." if len(summary) > 300 else summary)
    print("-------------------------")
    end_time = time.monotonic() # Record end time
    total_time = end_time - start_time
    print(f"--- Video summary and theme extraction finished in {total_time:.2f} seconds ---")

# --- Main generation function ---
def generate():
    start_time = time.monotonic() # Record start time


    client = genai.Client(api_key=GEMINI_API_KEY)

    video_chunks = list(TARGET_DIRECTORY.glob("*.mp4"))
    total_chunks_found = len(video_chunks) # Renamed for clarity
    if not video_chunks:
        print(f"No .mp4 files found in directory: {TARGET_DIRECTORY}")
        return

    print(f"Found {total_chunks_found} MP4 chunks in {TARGET_DIRECTORY}")

    # --- Determine and read the target JSON file ---
    json_path = get_video_json_path(TARGET_DIRECTORY)
    if not json_path:
        print(f"Error: Target JSON file not found for {TARGET_DIRECTORY}")
        return

    print(f"Reading existing data from {json_path}...")
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (IOError, json.JSONDecodeError) as e:
        print(f"Error reading or parsing JSON file {json_path}: {e}")
        return

    # Validate basic structure
    if "chunks" not in data or not isinstance(data.get("chunks"), list):
         print(f"Error: JSON file {json_path} does not contain a 'chunks' list.")
         return
    # --- End JSON reading ---

    # Use a dictionary to map chunk names to captions
    caption_map = {}
    processed_chunk_paths = set() # Keep track of chunks submitted for processing

    # Use ThreadPoolExecutor for concurrency
    future_to_chunk = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        # Submit all jobs to the executor
        for chunk_path in video_chunks:
            future = executor.submit(process_single_chunk, client, chunk_path)
            future_to_chunk[future] = chunk_path # Map future back to chunk_path
            processed_chunk_paths.add(chunk_path.name) # Track submitted chunks

        print(f"Submitted {total_chunks_found} chunks for processing with up to {MAX_WORKERS} workers...")

        # Process results as they complete
        successful_captions = 0
        failed_chunks = []
        for future in concurrent.futures.as_completed(future_to_chunk):
            chunk_path = future_to_chunk[future]
            try:
                original_chunk_path, caption = future.result() # Get result (chunk_path, caption or None)
                # Store the result in the map, even if None (indicates processing attempt)
                caption_map[original_chunk_path.name] = caption
                if caption is not None:
                    print(f"Successfully processed: {original_chunk_path.name}")
                    successful_captions += 1
                else:
                    # This log now happens *after* the detailed failure log from process_single_chunk
                    print(f"Marking {original_chunk_path.name} as failed in summary.")
                    failed_chunks.append(original_chunk_path.name)
            except Exception as exc:
                # Catch exceptions raised within the thread OR potentially from future.result() itself if task failed badly
                print(f"Chunk {chunk_path.name} generated an unhandled exception during future processing: {exc}")
                failed_chunks.append(chunk_path.name) # Count exceptions from future.result() as failures
                caption_map[chunk_path.name] = None # Mark as failed in the map
            # No finally block needed here as future_to_chunk mapping is handled by as_completed

    # --- Enrich the loaded JSON data ---
    print("Enriching JSON data with generated captions...")
    json_chunks_updated = 0
    json_chunks_missing_caption = []
    json_chunks_not_processed = [] # Chunks in JSON file but not found on disk in the chunks directory

    if "chunks" in data and isinstance(data["chunks"], list):
        for chunk_data in data["chunks"]:
            chunk_name = chunk_data.get("chunk_name")
            if chunk_name:
                 if chunk_name in caption_map:
                     caption = caption_map[chunk_name]
                     chunk_data["caption"] = caption # Add/update the caption field
                     if caption is not None:
                         json_chunks_updated += 1
                     else:
                         json_chunks_missing_caption.append(chunk_name)
                 elif chunk_name in processed_chunk_paths:
                      # This case means it was processed but somehow didn't end up in caption_map (shouldn't happen often)
                      print(f"Warning: Chunk {chunk_name} was processed but has no caption result recorded.")
                      chunk_data["caption"] = None # Mark as attempted but failed
                      json_chunks_missing_caption.append(chunk_name)
                 else:
                      # Chunk exists in JSON but wasn't found in the chunks directory
                      print(f"Warning: Chunk {chunk_name} found in JSON but not processed (file likely missing).")
                      chunk_data["caption"] = None # Mark as not processed
                      json_chunks_not_processed.append(chunk_name)
            else:
                 print("Warning: Found chunk entry in JSON without a 'chunk_name'. Skipping.")
    # --- End Enrichment ---


    # Write updated results back to the original JSON file
    try:
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False) # Using indent=2 for consistency with common JSON formats
        print(f"Successfully updated JSON file: {json_path.resolve()}")
    except IOError as e:
        print(f"Error writing updated data to JSON file {json_path}: {e}")

    end_time = time.monotonic() # Record end time
    total_time = end_time - start_time

    # --- Updated Summary ---
    print("--- Processing Summary ---")
    print(f"Target JSON: {json_path.name}")
    print(f"Found and attempted to process: {total_chunks_found} chunk files.")
    print(f"Successfully generated captions for: {successful_captions} chunks.")
    failed_count = len(failed_chunks) # Based on processing attempts
    print(f"Failed to generate captions for: {failed_count} chunks (due to errors or retries exhausted).")
    if failed_chunks:
        print("  Failed chunk processing names:")
        failed_chunks.sort()
        for name in failed_chunks:
            print(f"    - {name}")

    print("--- JSON Enrichment Summary ---")
    print(f"Total chunks in JSON: {len(data.get('chunks', []))}")
    print(f"Chunks in JSON updated with a caption: {json_chunks_updated}")
    print(f"Chunks in JSON where caption generation failed: {len(json_chunks_missing_caption)}")
    if json_chunks_missing_caption:
         print("  Chunks missing captions (marked as null/None):")
         json_chunks_missing_caption.sort()
         for name in json_chunks_missing_caption:
             print(f"    - {name}")
    print(f"Chunks in JSON not found/processed on disk: {len(json_chunks_not_processed)}")
    if json_chunks_not_processed:
        print("  Chunks in JSON not processed (marked as null/None):")
        json_chunks_not_processed.sort()
        for name in json_chunks_not_processed:
             print(f"    - {name}")
    # -------------

    print(f"--- Caption generation finished in {total_time:.2f} seconds ---")
    
    # Generate summary after captions are processed
    return json_path  # Return the JSON path for potential further processing

if __name__ == "__main__":
    start_time = time.monotonic() # Record start time
    json_path = generate()
    
    # Generate video summary if captions were successfully processed
    if json_path:
        generate_video_summary(json_path)
    else:
        print("Skipping video summarization as caption generation was not successful.")
    end_time = time.monotonic() # Record end time
    total_time = end_time - start_time
    print(f"--- Script finished in {total_time:.2f} seconds ---")
