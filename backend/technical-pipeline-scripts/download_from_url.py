import time
import yt_dlp
import os
import re # Import the re module for URL parsing
import json # Import the json module

def download_tiktok_video(url, base_download_path):
    # Extract username and video ID from URL using regex
    match = re.search(r"@(?P<username>[^/]+)/video/(?P<video_id>\d+)", url)
    if not match:
        print(f"Error: Could not extract username and video ID from URL: {url}")
        return

    username = match.group("username")
    tiktok_video_id = match.group("video_id")
    video_id = f"{username}-{tiktok_video_id}"

    # Construct the specific download directory path: ./videos/username-videoid
    download_subdir = f"{username}-{tiktok_video_id}"
    specific_download_path = os.path.join(base_download_path, download_subdir)

    # Create the specific subdirectory if it doesn't exist
    os.makedirs(specific_download_path, exist_ok=True)

    # Define the output filename template: username-videoid.mp4
    output_filename = f"{username}-{tiktok_video_id}.%(ext)s"
    output_template = os.path.join(specific_download_path, output_filename)

    # Options for yt-dlp:
    # - 'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/mp4' aims for best mp4, might need ffmpeg.
    #             Using 'mp4' directly might get lower quality sometimes. Let's stick to 'mp4' for simplicity as originally used.
    # - 'outtmpl': specifies the output file template.
    ydl_opts = {
        'format': 'mp4',
        'outtmpl': output_template, # Use the new template
    }

    print(f"Attempting to download video to: {specific_download_path}")
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            ydl.download([url])
            # Construct the expected final path for the success message
            final_file_path = os.path.join(specific_download_path, f"{video_id}.mp4")
            # Check if the file actually exists after download before confirming
            if os.path.exists(final_file_path):
                 print(f"Download successful: {final_file_path}")

                 # Create the JSON file
                 json_filename = f"{video_id}.json"
                 json_filepath = os.path.join(specific_download_path, json_filename)
                 json_data = {
                     "video_id": video_id,
                     "processing_status": "PROCESSING"
                 }

                 try:
                     with open(json_filepath, 'w') as f:
                         json.dump(json_data, f, indent=4)
                     print(f"Successfully created JSON metadata file: {json_filepath}")
                 except Exception as e:
                     print(f"Error creating JSON file {json_filepath}: {e}")

            else:
                 # yt-dlp might save with a different extension if mp4 wasn't available, although we requested mp4.
                 # Listing the directory content could help diagnose.
                 actual_files = os.listdir(specific_download_path)
                 print(f"Download process finished, but expected file not found at {final_file_path}. Files in directory: {actual_files}")

        except Exception as e:
            print(f"Error during download for {url}: {e}")


if __name__ == '__main__':
    start_time = time.time()
    # Hardcoded TikTok URL – replace with your desired URL.
    # tiktok_url = "https://www.tiktok.com/@maxpreps/video/7489213523369774366"
    # tiktok_url = "https://www.tiktok.com/@petfunnyrecording507/video/7457352740675620139"
    # tiktok_url = "https://www.tiktok.com/@scare.prank.us66/video/7437112939582180640"
    # tiktok_url = "https://www.tiktok.com/@jadewellz/video/7485227592648248622"
    # tiktok_url = "https://www.tiktok.com/@mauricioislasoficial/video/7484114461347941687"
    # tiktok_url = "https://www.tiktok.com/@tiyonaaa1/video/7488793321310113066"
    tiktok_url = "https://www.tiktok.com/@brad_podray/video/7488978108121500958"

    videos_base_folder = os.path.expanduser("./videos")
    
    # Ensure the base video directory exists
    os.makedirs(videos_base_folder, exist_ok=True)

    
    
    # Download the TikTok video using the modified function.
    # Pass the base folder, the function now handles the subfolder.
    download_tiktok_video(tiktok_url, videos_base_folder)
    
    end_time = time.time()
    print(f"Total execution time: {end_time - start_time:.2f} seconds")
