import os
import json
import time
import math  # For ceiling division in batching progress
import concurrent.futures
from pinecone.grpc import PineconeGRPC as Pinecone
from pinecone import ServerlessSpec 
from openai import OpenAI
from pathlib import Path
from dotenv import load_dotenv, set_key
from typing import List, Dict, Any, Optional, Tuple

# --- Global variables and Environment Setup ---
dotenv_path = Path(".env.local")
load_dotenv(dotenv_path=dotenv_path)

# API Keys and Configuration
openai_api_key = os.environ.get("OPENAI_API_KEY")
pinecone_api_key = os.environ.get("PINECONE_API_KEY")
pinecone_index_host = os.environ.get("PINECONE_INDEX_HOST")
index_name = "video-captions-index"
embed_model_name = "text-embedding-ada-002" 
embed_dim = 1536
batch_size = 100

json_file_path = Path("videos/tiyonaaa1-7488793321310113066/tiyonaaa1-7488793321310113066.json")
# json_file_path = Path("videos/aichifan33-7486040114695507242/aichifan33-7486040114695507242.json")
# json_file_path = Path("videos/jadewellz-7485227592648248622/jadewellz-7485227592648248622.json")
# json_file_path = Path("videos/petfunnyrecording507-7457352740675620139/petfunnyrecording507-7457352740675620139.json")
# json_file_path = Path("videos/zachchoicook6-7485701580923145494/zachchoicook6-7485701580923145494.json")
# json_file_path = Path("videos/brad_podray-7488978108121500958/brad_podray-7488978108121500958.json")

TEST_QUERY = "Who's the kid in the video? What TV show is this from?"
# Initialize global clients
openai_client = None
pc = None
pinecone_index = None

def initialize_clients():
    """Initialize API clients for OpenAI and Pinecone."""
    global openai_client, pc, pinecone_index, pinecone_index_host
    
    if not openai_api_key or not pinecone_api_key:
        raise EnvironmentError("Please set OPENAI_API_KEY and PINECONE_API_KEY environment variables.")

    # Initialize OpenAI client
    try:
        openai_client = OpenAI(api_key=openai_api_key)
    except Exception as e:
        print(f"Error initializing OpenAI client: {e}")
        raise

    # Initialize Pinecone client
    try:
        pc = Pinecone(api_key=pinecone_api_key)
    except Exception as e:
        print(f"Error initializing Pinecone client: {e}")
        raise

    # Handle Pinecone index host setup
    if not pinecone_index_host:
        print("PINECONE_INDEX_HOST environment variable not set.")
        print("Checking index status and determining host...")
        
        # Check if index exists
        print("  Checking existing indexes...")
        start_list_indexes = time.time()
        existing_indexes = pc.list_indexes().names()
        end_list_indexes = time.time()
        print(f"  pc.list_indexes().names() call took: {end_list_indexes - start_list_indexes:.4f} seconds")

        if index_name not in existing_indexes:
            print(f"  Creating index '{index_name}'...")
            start_create_index = time.time()
            # Create Pinecone index if it doesn't exist
            pc.create_index(
                name=index_name,
                dimension=embed_dim,
                metric="cosine",
                spec=ServerlessSpec(
                    cloud="aws",
                    region="us-east-1"
                )
            )
            end_create_index = time.time()
            print(f"  pc.create_index() call took: {end_create_index - start_create_index:.4f} seconds")
            print(f"  Index '{index_name}' created. Waiting for it to be ready...")
            
            # Wait for the index to be ready
            time.sleep(5)
            max_wait_time = 120
            wait_start_time = time.time()
            while True:
                try:
                    start_describe_loop = time.time()
                    index_description = pc.describe_index(index_name)
                    end_describe_loop = time.time()
                    print(f"    (describe_index in loop took: {end_describe_loop - start_describe_loop:.4f}s)")
                    if index_description.status['ready']:
                        print(f"  Index '{index_name}' is ready.")
                        break
                except Exception as e:
                    print(f"    Waiting for index... (Error describing: {e})")
                    pass
                
                if time.time() - wait_start_time > max_wait_time:
                    raise TimeoutError(f"Index '{index_name}' did not become ready within {max_wait_time} seconds.")
                
                print("    Index not ready yet, waiting...")
                time.sleep(5)
        else:
            print(f"  Index '{index_name}' already exists.")

        # Get the index host
        print(f"  Describing index '{index_name}' to get its host...")
        start_describe_final = time.time()
        index_description = pc.describe_index(index_name)
        end_describe_final = time.time()
        print(f"  pc.describe_index() took: {end_describe_final - start_describe_final:.4f} seconds")
        pinecone_index_host = index_description.host
        print(f"  Determined index host: {pinecone_index_host}")
        
        # Set environment variable
        os.environ['PINECONE_INDEX_HOST'] = pinecone_index_host
        print(f"    Set os.environ['PINECONE_INDEX_HOST'] for the current process.")

        # Update .env.local file
        try:
            set_key(dotenv_path, "PINECONE_INDEX_HOST", pinecone_index_host)
            print(f"    Updated PINECONE_INDEX_HOST in {dotenv_path.name} for local persistence.")
        except Exception as e:
            print(f"    Warning: Could not update {dotenv_path.name}: {e}")
            print(f"    You may need to set PINECONE_INDEX_HOST manually in this file.")
    else:
        print(f"Using existing PINECONE_INDEX_HOST: {pinecone_index_host}")
    
    # Connect to the index
    print(f"Connecting to Pinecone index via host: {pinecone_index_host}")
    try:
        pinecone_index = pc.Index(host=pinecone_index_host)
    except Exception as e:
        print(f"Error connecting to Pinecone index: {e}")
        raise

def get_embedding(caption_text, model_name):
    """Helper function to get embedding for a caption text."""
    try:
        response = openai_client.embeddings.create(
            input=caption_text,
            model=model_name
        )
        print(f"    Embedding created for caption snippet: {caption_text[:50]}...")
        return response.data[0].embedding
    except Exception as e:
        print(f"    ERROR getting embedding for caption: {caption_text[:50]}... Error: {e}")
        raise RuntimeError(f"Failed to get embedding for caption: {caption_text[:50]}...") from e

def process_and_index_data(json_file_path: Path):
    """Process JSON data and index it into Pinecone."""
    start_time = time.time()
    
    # Load and validate JSON data
    if not json_file_path.is_file():
        raise FileNotFoundError(f"JSON file not found at: {json_file_path}")

    with open(json_file_path, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as e:
            print(f"Error decoding JSON from {json_file_path}: {e}")
            raise

    # Extract caption chunks
    video_id = data.get("video_id")

    if not video_id:
        raise ValueError(f"No valid 'video_id' found in {json_file_path}.")
    chunks = data.get("chunks") or []
    if not isinstance(chunks, list) or not chunks:
        raise ValueError(f"No valid 'chunks' list found in {json_file_path}.")

    print(f"Loaded {len(chunks)} chunks from {json_file_path.name}")

    # Get initial vector count
    initial_vector_count = 0
    try:
        start_describe_index_stats = time.time()
        initial_stats = pinecone_index.describe_index_stats()
        end_describe_index_stats = time.time()
        print(f"  pinecone_index.describe_index_stats() took: {end_describe_index_stats - start_describe_index_stats:.4f} seconds")

        initial_vector_count = initial_stats.namespaces.get('', {}).get('vector_count', 0)
        print(f"Initial vector count in index: {initial_vector_count}")
    except Exception as e:
        print(f"Warning: Could not get initial index stats: {e}. Assuming initial count is 0.")

    # Determine new vectors to process
    count_of_new_ids = 0
    potential_ids = [chunk.get("chunk_name") for chunk in chunks if chunk.get("chunk_name")]
    existing_ids = set()
    chunks_to_process = []

    if not potential_ids:
        print("No valid chunk_names found in input data. Skipping check for existing IDs.")
        chunks_to_process = []
    else:
        print(f"Checking existence of {len(potential_ids)} potential IDs in Pinecone...")
        try:
            fetch_response = pinecone_index.fetch(ids=potential_ids)
            existing_ids = set(fetch_response.vectors.keys())
            count_of_existing_ids = len(existing_ids)
            count_of_new_ids = len(potential_ids) - count_of_existing_ids

            print(f"  Found {count_of_existing_ids} existing IDs.")
            print(f"  Expecting to add {count_of_new_ids} new vectors.")

            chunks_to_process = [chunk for chunk in chunks if chunk.get("chunk_name") and chunk.get("chunk_name") not in existing_ids]
            print(f"  Found {len(chunks_to_process)} new chunks to process.")
        except Exception as e:
            print(f"Warning: Could not fetch existing IDs: {e}")
            print("  Proceeding assuming all chunks might be new (will attempt upsert).")
            chunks_to_process = [chunk for chunk in chunks if chunk.get("chunk_name")]
            count_of_new_ids = len(chunks_to_process)

    # Process and index new chunks
    if chunks_to_process:
        print(f"\nProcessing {len(chunks_to_process)} new chunks...")
        vectors_to_upsert = []
        processed_count = 0

        start_embedding_time = time.time()

        # Get embeddings concurrently
        captions_to_embed = [chunk['caption'] for chunk in chunks_to_process if chunk.get('caption')]
        embeddings = []
        max_workers = 8
        print(f"  Requesting embeddings for {len(captions_to_embed)} captions using up to {max_workers} workers...")
        
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_caption = {executor.submit(get_embedding, caption, embed_model_name): caption for caption in captions_to_embed}
                
                results = []
                for future in concurrent.futures.as_completed(future_to_caption):
                    caption_text = future_to_caption[future]
                    try:
                        embedding_vector = future.result()
                        results.append(embedding_vector)
                        print(f"    Successfully retrieved embedding for: {caption_text[:50]}...")
                    except Exception as exc:
                        print(f"    ERROR processing caption: {caption_text[:50]}... generated an exception: {exc}")
                        raise RuntimeError("One or more embedding tasks failed.") from exc

                embeddings = list(executor.map(lambda cap: get_embedding(cap, embed_model_name), captions_to_embed))
                print(f"  Successfully retrieved {len(embeddings)} embeddings.")

        except Exception as e:
            print(f"An error occurred during concurrent embedding: {e}")
            raise

        embedding_complete_time = time.time()
        print(f"  Concurrent embedding took: {embedding_complete_time - start_embedding_time:.4f} seconds.")

        # Ensure we got the expected number of embeddings
        if len(embeddings) != len(chunks_to_process):
            raise RuntimeError(f"Mismatch between number of chunks to process ({len(chunks_to_process)}) and embeddings received ({len(embeddings)}). Aborting.")

        # Prepare vectors for upsert
        print("  Preparing vectors for Pinecone upsert...")
        vectors_to_upsert = []
        for i, chunk in enumerate(chunks_to_process):
            chunk_name = chunk.get("chunk_name")
            caption = chunk.get("caption")
            vector = embeddings[i]

            if not chunk_name:
                print(f"Warning: Skipping chunk {i+1} in final preparation due to missing chunk_name.")
                continue

            metadata = {
                "caption": caption,
                "start_timestamp": chunk.get("start_timestamp", "Unknown"),
                "end_timestamp": chunk.get("end_timestamp", "Unknown"),
                "chunk_name": chunk_name,
                "video_id": video_id,
                "normalized_start_time": chunk.get("normalized_start_time", "Unknown"),
                "normalized_end_time": chunk.get("normalized_end_time", "Unknown"),
                "chunk_duration_seconds": chunk.get("chunk_duration_seconds", "Unknown"),
                "chunk_number": chunk.get("chunk_number", "Unknown")
            }

            vector_dict = {
                "id": chunk_name,
                "values": vector,
                "metadata": metadata
            }
            vectors_to_upsert.append(vector_dict)
            processed_count += 1

            # Upsert batches
            if len(vectors_to_upsert) >= batch_size or (i == len(chunks_to_process) - 1 and vectors_to_upsert):
                print(f"    Upserting batch {math.ceil(processed_count / batch_size)} ({len(vectors_to_upsert)} new vectors)...")
                try:
                    start_upsert_batch = time.time()
                    pinecone_index.upsert(vectors=vectors_to_upsert)
                    end_upsert_batch = time.time()
                    print(f"      Batch upsert took: {end_upsert_batch - start_upsert_batch:.4f} seconds")
                    vectors_to_upsert = []
                except Exception as e:
                    print(f"Error upserting batch to Pinecone: {e}")
                    raise RuntimeError("Failed to upsert batch to Pinecone") from e

        # Calculate timing
        upsert_complete_time = time.time()
        print(f"  Vector preparation and batch upserting took: {upsert_complete_time - embedding_complete_time:.4f} seconds.")
        print(f"Finished processing {processed_count} new vectors (embedding + upserting) in {upsert_complete_time - start_embedding_time:.4f} seconds.")

        # Poll for index update
        target_count = initial_vector_count + count_of_new_ids
        print(f"\nPolling Pinecone index stats until vector count reaches {target_count} (Initial: {initial_vector_count}, Expected New: {count_of_new_ids})...")
        polling_start_time = time.time()
        max_polling_wait_seconds = 60
        poll_interval_seconds = 2
        poll_iterations = 1

        while True:
            current_vector_count = -1

            try:
                current_stats = pinecone_index.describe_index_stats()
                current_vector_count = current_stats.get('namespaces', {}).get('', {}).get('vector_count', 0)
                count_reached = (current_vector_count >= target_count)

                print(f"  Poll Iteration {poll_iterations}: Count Check ({current_vector_count}/{target_count}) -> {count_reached}")
                poll_iterations += 1

                if count_reached:
                    print("  Target count reached. Index update confirmed.")
                    break

                if time.time() - polling_start_time > max_polling_wait_seconds:
                    print(f"  Warning: Polling timed out after {max_polling_wait_seconds} seconds waiting for count {target_count}.")
                    print(f"    Current count: {current_vector_count}")
                    print(f"  Proceeding anyway, but query results might be incomplete.")
                    break

            except Exception as e:
                print(f"  Warning: Error polling index stats: {e}")
                if time.time() - polling_start_time > max_polling_wait_seconds:
                     print(f"  Polling timed out after encountering error.")
                     break

            time.sleep(poll_interval_seconds)
            
        # --- Update processing status to FINISHED in JSON file ---
        try:
            print(f"Attempting to update processing status in {json_file_path.name} after upsert...")
            with open(json_file_path, "r+", encoding="utf-8") as f:
                try:
                    data = json.load(f)
                    data["processing_status"] = "FINISHED"
                    f.seek(0)  # Go to the beginning of the file
                    json.dump(data, f, indent=4)
                    f.truncate() # Remove any trailing data if the new content is shorter
                    print(f"Successfully updated processing_status to 'FINISHED' in {json_file_path.name}")
                except json.JSONDecodeError as e:
                    print(f"Error decoding JSON from {json_file_path.name} during status update: {e}")
                except Exception as e:
                    print(f"Error updating JSON file {json_file_path.name}: {e}")
        except FileNotFoundError:
            print(f"Error: Could not find {json_file_path.name} to update status.")
        except Exception as e:
            print(f"Error opening/writing to {json_file_path.name} for status update: {e}")
        # --- End of update block ---
            
    else:
        print("\nNo new chunks to process. All required chunk IDs already exist in the index.")

    # Check final index stats (this can stay outside, useful for verification)
    try:
        final_stats = pinecone_index.describe_index_stats()
        final_count = final_stats.get('namespaces', {}).get('', {}).get('vector_count', 0)
        print(f"Index stats after processing: {final_stats}")
        print(f"Final vector count confirmed: {final_count}")
    except Exception as e:
        print(f"Warning: Could not get final index stats after processing: {e}")
    
    end_time = time.time()
    print(f"Data processing and indexing completed in {end_time - start_time:.2f} seconds")

def timestamp_to_seconds(ts_str):
    """Converts MM:SS.fff timestamp string to seconds."""
    if not isinstance(ts_str, str) or ts_str == "Unknown":
        return 0.0
    try:
        parts = ts_str.split(':')
        if len(parts) == 2:
            minutes, seconds = parts
            return int(minutes) * 60 + float(seconds)
    except ValueError:
        return 0.0
    return 0.0

def query_and_get_context(query: str, top_k: int = 3, json_file_path: Path = json_file_path):
    """
    Query the Pinecone index with a user question and return formatted context.
    
    Args:
        query: The user's question
        top_k: Number of top results to retrieve
        json_file_path: Path to the JSON file containing video data
    
    Returns:
        str: Formatted context string for use in RAG
    """
    start_time = time.time()
    print(f"\n--- Processing Query: '{query}' ---")
    
    # Load video summary and video_id from JSON
    try:
        with open(json_file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            video_summary = data.get("overall_summary", "No summary available for this video.")
            video_id = data.get("video_id", "")
            # Extract TikTok user_name from video_id
            user_name = video_id.split('-')[0] if '-' in video_id else None
            num_chunks = data.get("num_chunks", "")
            if num_chunks: 
                num_chunks = f'/{num_chunks}'
            key_themes = data.get("key_themes", "")
            total_duration = data.get("total_duration_seconds", "")
                
        if not video_id:
            print(f"Warning: No video_id found in {json_file_path}")
            
    except Exception as e:
        print(f"Warning: Could not load video data: {e}")
        video_summary = "No summary available for this video."
        video_id = ""
    
    # Embed the query
    try:
        start_query_embed = time.time()
        response = openai_client.embeddings.create(
            input=[query],
            model=embed_model_name
        )
        query_vector = response.data[0].embedding
        end_query_embed = time.time()
        print(f"Query embedding took: {end_query_embed - start_query_embed:.4f} seconds")
    except Exception as e:
        print(f"Error embedding query: {e}")
        raise RuntimeError("Failed to embed query") from e

    # Query Pinecone with video_id filter
    try:
        print(f"Retrieving top_k={top_k} results from Pinecone for video '{video_id}'...")
        start_retrieve = time.time()
        
        # Create filter to only retrieve chunks from this specific video
        filter_params = {"video_id": video_id}
        # filter_params = {"video_id": {"$eq": video_id}} # example filter with operator
        
        query_results = pinecone_index.query(
            vector=query_vector,
            top_k=top_k,
            include_metadata=True,
            filter=filter_params  # Add filter by video_id
        )
        end_retrieve = time.time()
        print(f"Pinecone query took: {end_retrieve - start_retrieve:.4f} seconds")
        
        retrieved_chunks = query_results.get('matches', [])
        print(f"Retrieved {len(retrieved_chunks)} chunks for video '{video_id}'")
        
        # Sort retrieved chunks by sequence number
        if retrieved_chunks:
            retrieved_chunks.sort(key=lambda x: x.get('metadata', {}).get('chunk_number', float('inf')))
            print("Sorted retrieved chunks by chunk_number metadata field.")
        
        # Assemble the context string
        context_parts = []
        context_parts.append("Video Summary:")
        context_parts.append(video_summary)

        # Add user_name to context
        if user_name:
            context_parts.append(f"\nUsername of TikTok account that posted this video:\n{user_name}")

        if key_themes:
            context_parts.append("\nKey Video Themes:")
            context_parts.append(key_themes)

        if total_duration:
            context_parts.append(f"\nTotal Video Duration: {total_duration:.2f} seconds")

        context_parts.append("\nPotentially Relevant Video Clips (in order):")
        context_parts.append("---")
        
        if not retrieved_chunks:
            context_parts.append("(No specific video clips retrieved based on query)")
        else:
            for i, chunk in enumerate(retrieved_chunks):
                metadata = chunk.get('metadata', {})
                seq_num = metadata.get('chunk_number', '?')
                if isinstance(seq_num, (int, float)):
                    seq_num = int(seq_num)
                start_ts = metadata.get('start_timestamp', '?:??')
                end_ts = metadata.get('end_timestamp', '?:??')
                caption = metadata.get('caption', '(Caption text missing)')
                
                # Add simple relative time hints
                norm_start = metadata.get('normalized_start_time')
                norm_end = metadata.get('normalized_end_time')
                time_hint = ""
                hints = []
                
                # Check if times are valid floats before comparing
                is_valid_start = isinstance(norm_start, (float, int))
                is_valid_end = isinstance(norm_end, (float, int))
                
                if is_valid_start and is_valid_end:
                    # Check start boundary
                    if norm_start <= 0.15:
                        hints.append("near the beginning")
                    
                    # Check end boundary
                    if norm_end >= 0.85:
                        hints.append("near the end")
                    
                    # Optional: Explicitly label middle
                    if not hints and norm_start > 0.15 and norm_end < 0.85:
                        hints.append("around the middle")
                
                # Format the hint string
                if hints:
                    time_hint = f" ({' and '.join(hints)})"
                
                context_parts.append(f"Video Clip {seq_num}{num_chunks} (Time: {start_ts} - {end_ts}){time_hint}:")
                context_parts.append(caption)
                if i < len(retrieved_chunks) - 1:
                    context_parts.append("---")
        
        final_context = "\n".join(context_parts)
        print(f"Final context assembled with {len(retrieved_chunks)} chunks")
        
        print(f"Full context:\n{final_context}")
        
        end_time = time.time()
        print(f"Query processing completed in {end_time - start_time:.2f} seconds")
        
        return final_context
        
    except Exception as e:
        print(f"Error during Pinecone query or processing results: {e}")
        # Return a minimal context with just the video summary
        return f"Video Summary:\n{video_summary}\n\nError retrieving specific video clips: {str(e)}"

# Main execution block
if __name__ == "__main__":
    overall_start_time = time.time()
    
    # Initialize clients
    initialize_clients()
    
    # Process and index data
    process_and_index_data(json_file_path)
    
    context = query_and_get_context(TEST_QUERY)
    
    overall_end_time = time.time()
    print(f"\nTotal script execution time: {overall_end_time - overall_start_time:.2f} seconds")