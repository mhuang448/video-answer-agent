from scenedetect import AdaptiveDetector, split_video_ffmpeg
from scenedetect import ContentDetector
from scenedetect import open_video, SceneManager
from scenedetect.video_splitter import DEFAULT_FFMPEG_ARGS  # Import default args
from scenedetect.frame_timecode import FrameTimecode
import os
import time
from concurrent.futures import ThreadPoolExecutor
import math 
import json # Added import

# PySceneDetect Docs: https://www.scenedetect.com/docs/latest/api/detectors.html#module-scenedetect.detectors.content_detector

start_time = time.time()

def detect_and_split(video_path, output_dir=None, fixed_chunk_duration=4.0):
    """
    Optimized scene detection with fixed-length chunk fallback.
    
    Attempts to detect scenes first. If 0 or 1 scene is detected,
    it falls back to splitting the video into fixed-duration chunks.
    
    Args:
        video_path: Path to the video file.
        output_dir: Directory to save chunks. If None, creates a 'chunks' folder in the video's directory.
        fixed_chunk_duration: Duration (in seconds) for fixed-length chunks fallback.
    """
    # Determine output directory if not specified
    if output_dir is None:
        # Get the directory containing the video
        video_dir = os.path.dirname(video_path)
        # Create a 'chunks' folder within that directory
        output_dir = os.path.join(video_dir, 'chunks')
    
    # Create output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)
    
    # Open video and configure detector
    video = open_video(video_path)
    frame_rate = video.frame_rate
    duration_frames = video.duration.get_frames()
    print(f"Video Info: {os.path.basename(video_path)}")
    print(f"  - FPS: {frame_rate:.2f}")
    print(f"  - Total Frames: {duration_frames}")
    
    # Configure detector
    # detector = AdaptiveDetector(
    #     adaptive_threshold=3.0,
    #     min_scene_len=15, # Still use a minimum for scene detection attempt
    #     window_width=2
    # )
    detector = ContentDetector(
        threshold=27.0, # Default recommended threshold, may need tuning
        min_scene_len=30 # Minimum length in frames (0.5s @ 30fps)
        # min_scene_len=15 # Minimum length in frames (0.5s @ 30fps) created 30 chunks for the spider prank video
    )
    
    # Use SceneManager for more control
    scene_manager = SceneManager()
    scene_manager.add_detector(detector)
    
    detect_start_time = time.time()
    # Detect all scenes in video
    scene_manager.detect_scenes(video, show_progress=True)
    detect_end_time = time.time()
    print(f"Scene detection attempt took: {detect_end_time - detect_start_time:.2f} seconds")
    
    # Get the list of scenes
    detection_method = "Scene Detection"
    scene_list = scene_manager.get_scene_list()
    
    # --- Fallback Logic ---
    if len(scene_list) <= 1:
        print(f"Scene detection found {len(scene_list)} scenes.\nFalling back to fixed {fixed_chunk_duration}s chunks.")
        detection_method = f"Fixed {fixed_chunk_duration}s Chunking"
        
        # Calculate video duration in frames
        # duration_frames = video.duration.get_frames() # Moved calculation earlier
        
        chunk_len_frames = int(fixed_chunk_duration * frame_rate)
        num_chunks = math.ceil(duration_frames / chunk_len_frames)
        
        scene_list = []
        for i in range(num_chunks):
            start_frame = i * chunk_len_frames
            end_frame = min((i + 1) * chunk_len_frames, duration_frames)
            
            # Ensure start_frame is less than end_frame
            if start_frame >= end_frame:
                continue # Skip if the chunk would have zero or negative length

            start_tc = FrameTimecode(timecode=start_frame, fps=frame_rate)
            end_tc = FrameTimecode(timecode=end_frame, fps=frame_rate)
            
            # PySceneDetect expects end timecodes to be exclusive for splitting,
            # but inclusive for scene lists. Since split_video_ffmpeg uses the list,
            # we provide the exact end frame.
            scene_list.append((start_tc, end_tc))
            
        print(f"Generated {len(scene_list)} fixed-length chunks.")
    else:
        print(f"Scene detection found {len(scene_list)} scenes.")
    # --- End Fallback Logic ---

    # Check if any scenes/chunks were generated
    if not scene_list:
        print("No scenes detected or chunks generated. Skipping splitting.")
        return [] # Return empty list if nothing to split

    # --- Start: Prepare JSON Metadata ---
    video_dir = os.path.dirname(video_path)
    video_basename = os.path.basename(video_path)
    video_id = os.path.splitext(video_basename)[0]

    json_output_path = os.path.join(video_dir, f"{video_id}.json")
    
    num_chunks = len(scene_list)
    chunks_metadata = []
    output_template = '$VIDEO_ID-Scene-$SCENE_NUMBER.mp4' # Default template
    
    # Calculate total video duration in seconds for normalization
    total_duration_seconds = video.duration.get_seconds()
    print(f"Total video duration: {total_duration_seconds:.3f} seconds")

    print(f"Preparing metadata for {num_chunks} chunks...")
    for i, (start_tc, end_tc) in enumerate(scene_list):
        scene_number = i + 1
        chunk_name = output_template.replace('$VIDEO_ID', video_id)\
                                    .replace('$SCENE_NUMBER', f'{scene_number:03d}')

        # Format timestamps as MM:SS.nnn
        start_seconds = start_tc.get_seconds()
        start_minutes = int(start_seconds // 60)
        start_secs_remainder = start_seconds % 60
        start_ts_str = f"{start_minutes:02}:{start_secs_remainder:06.3f}"

        end_seconds = end_tc.get_seconds()
        end_minutes = int(end_seconds // 60)
        end_secs_remainder = end_seconds % 60
        # Ensure end time is strictly greater than start time for display, clip if necessary
        # Although FrameTimecode should handle this, add a small epsilon check for robustness in formatting
        if end_seconds <= start_seconds:
             end_seconds = start_seconds + (1 / frame_rate) # Add minimal duration (1 frame) if end <= start
             end_minutes = int(end_seconds // 60)
             end_secs_remainder = end_seconds % 60
             
        end_ts_str = f"{end_minutes:02}:{end_secs_remainder:06.3f}"
        
        # Calculate normalized start and end times (0.0 to 1.0)
        normalized_start_time = start_seconds / total_duration_seconds if total_duration_seconds > 0 else 0.0
        normalized_end_time = end_seconds / total_duration_seconds if total_duration_seconds > 0 else 0.0
        
        # Calculate chunk duration in seconds
        chunk_duration = end_seconds - start_seconds

        chunks_metadata.append({
            "chunk_name": chunk_name,
            "video_id": video_id,
            "start_timestamp": start_ts_str,
            "end_timestamp": end_ts_str,
            "chunk_number": scene_number,  # 1-based index of the chunk
            "normalized_start_time": round(normalized_start_time, 3),  # Rounded to 3 decimal places
            "normalized_end_time": round(normalized_end_time, 3),  # Rounded to 3 decimal places
            "chunk_duration_seconds": round(chunk_duration, 3)  # Duration in seconds, rounded to 3 decimal places
        })

    json_data = {
        "num_chunks": num_chunks,
        "total_duration_seconds": total_duration_seconds,  # Add total duration to top level
        "chunks": chunks_metadata
    }
    # --- End: Prepare JSON Metadata ---

    # Determine FFmpeg arguments based on NVENC availability
    if is_nvenc_available():
        # Use NVENC hardware acceleration and map video/audio streams
        ffmpeg_args = '-map 0:v:0 -map 0:a? -c:v h264_nvenc'
        print("Using NVENC hardware acceleration.")
    else:
        # Use default software encoding arguments
        ffmpeg_args = DEFAULT_FFMPEG_ARGS
        print("NVENC not available, using default software encoding.")

    print(f"Chunking video {os.path.basename(video_path)} into {len(scene_list)} chunks...")
    split_start_time = time.time()
    # Split using FFmpeg with the determined arguments
    try:
        split_video_ffmpeg(
            video_path,
            scene_list,
            output_dir=output_dir,
            arg_override=ffmpeg_args
        )
        split_end_time = time.time()
        print(f"Video chunking took: {split_end_time - split_start_time:.2f} seconds")
    except Exception as e:
        print(f"Error during video chunking: {e}")
        # Even if chunking fails, attempt verification for potentially partially created files
        split_end_time = time.time() 
        print(f"Video chunking attempt took: {split_end_time - split_start_time:.2f} seconds before error.")

    # --- Start: Modified logging for saved chunks ---
    print(f"Verifying chunks for {os.path.basename(video_path)}...") 
    video_id = os.path.splitext(os.path.basename(video_path))[0]
    # Adjust template based on detection method? No, keep standard naming.
    # $VIDEO_ID-Scene-$SCENE_NUMBER.mp4 is the default template used by split_video_ffmpeg
    output_template = '$VIDEO_ID-Scene-$SCENE_NUMBER.mp4' 
    successful_chunks = 0 
    failed_chunks = [] 

    # Determine total expected chunks based on scene_list length
    total_expected_chunks = len(scene_list) 

    # Check for existing files matching the pattern
    # We iterate up to the expected number based on scene_list len
    for i in range(total_expected_chunks): 
        scene_number = i + 1 
        expected_filename = output_template\
            .replace('$VIDEO_ID', video_id)\
            .replace('$SCENE_NUMBER', f'{scene_number:03d}') 

        expected_filepath = os.path.join(output_dir, expected_filename)

        if os.path.exists(expected_filepath) and os.path.getsize(expected_filepath) > 0: # Also check if file is not empty
            successful_chunks += 1
        else:
            failed_chunks.append(expected_filename)

    # Print warnings only for chunks that failed
    if failed_chunks:
        print("  --- Missing/Empty Chunks ---")
        for filename in failed_chunks:
            print(f"  WARNING: Expected chunk file missing or empty: {filename}")
        print("  -------------------------")

    # Print final summary
    print(f"Successfully saved {successful_chunks} out of {total_expected_chunks} expected chunks to {output_dir} (Method: {detection_method})")
    # --- End: Modified logging for saved chunks ---

    # --- Start: Save JSON Metadata File ---
    try:
        # Check if JSON file already exists and read its contents
        existing_data = {}
        if os.path.exists(json_output_path):
            try:
                with open(json_output_path, 'r') as f:
                    existing_data = json.load(f)
                print(f"Reading existing metadata from {json_output_path}")
            except json.JSONDecodeError:
                print(f"Warning: Existing file {json_output_path} has invalid JSON format. Creating new file.")
            except Exception as e:
                print(f"Warning: Could not read existing file {json_output_path}: {e}. Creating new file.")
        
        # Update existing data with new metadata
        # If keys already exist, they will be updated
        for key, value in json_data.items():
            existing_data[key] = value
        
        # Write the combined data back to the file
        with open(json_output_path, 'w') as f:
            json.dump(existing_data, f, indent=2)
        print(f"Successfully saved metadata to {json_output_path}")
    except Exception as e:
        print(f"Error saving metadata to {json_output_path}: {e}")
    # --- End: Save JSON Metadata File ---

    return scene_list # Return the actual list used for splitting

def is_nvenc_available():
    """Check if NVENC is available on the system"""
    try:
        import subprocess
        result = subprocess.run(
            ['ffmpeg', '-hide_banner', '-encoders'],
            capture_output=True, text=True
        )
        return 'h264_nvenc' in result.stdout
    except:
        return False

def batch_process(video_paths, max_workers=4):
    """Process multiple videos in parallel
    
    Args:
        video_paths: List of paths to video files
        max_workers: Maximum number of parallel workers
    """
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {}
        for video_path in video_paths:
            # Each video gets its own chunks folder in its directory
            futures[executor.submit(detect_and_split, video_path)] = video_path
        
        for future in futures:
            video_path = futures[future]
            try:
                scenes = future.result()
                print(f"Processed {video_path}: {len(scenes)} scenes detected")
            except Exception as e:
                print(f"Error processing {video_path}: {str(e)}")

# Example usage
if __name__ == "__main__":
    # Single video usage - specify the path to your video
    # video_path = 'videos/maxpreps-7489213523369774366/maxpreps-7489213523369774366.mp4'
    # video_path = 'videos/petfunnyrecording507-7457352740675620139/petfunnyrecording507-7457352740675620139.mp4'
    # video_path = 'videos/scare.prank.us66-7437112939582180640/scare.prank.us66-7437112939582180640.mp4'
    # video_path = 'videos/jadewellz-7485227592648248622/jadewellz-7485227592648248622.mp4'
    # video_path = 'videos/mauricioislasoficial-7484114461347941687/mauricioislasoficial-7484114461347941687.mp4'
    # video_path = 'videos/tiyonaaa1-7488793321310113066/tiyonaaa1-7488793321310113066.mp4'
    video_path = 'videos/brad_podray-7488978108121500958/brad_podray-7488978108121500958.mp4'

    detect_and_split(video_path)
    
    # Multiple videos example (commented out)
    """
    video_dir = 'videos'
    video_paths = []
    
    # Find all video folders and their mp4 files
    for folder in os.listdir(video_dir):
        folder_path = os.path.join(video_dir, folder)
        if os.path.isdir(folder_path):
            for file in os.listdir(folder_path):
                if file.endswith('.mp4'):
                    video_paths.append(os.path.join(folder_path, file))
    
    batch_process(video_paths)
    """
    
    end_time = time.time()
    print(f"Total execution time: {end_time - start_time:.2f} seconds")

'''
Takes about 10 seconds for a 1 min video
'''