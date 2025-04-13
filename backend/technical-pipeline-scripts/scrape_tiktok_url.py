import random
from TikTokApi import TikTokApi
import asyncio
import os
import time

# Get ms_token from environment variables (optional but recommended)
# You can get this from your browser cookies on tiktok.com
ms_token = os.environ.get("ms_token", None)

async def get_random_comedy_video(max_duration=50, min_views=3000000):
    """
    Searches for videos under the 'funny' hashtag that meet duration and view count criteria.
    Retries fetching videos up to 3 times, creating a new session each time, if the initial attempt yields none.
    Processes only the *first* video found in each attempt.
    If no videos meet the criteria after all attempts, returns the URL of the *shortest* video among those processed.
    Returns a randomly selected matching video URL, the shortest video URL as fallback, or None.
    Uses async/await as required by the TikTokApi library.
    """
    matching_urls = []
    shortest_duration = float('inf') # Initialize with infinity
    shortest_video_url = None        # URL of the shortest video found
    max_retries = 3
    attempt = 0
    processed_a_video = False # Flag to check if at least one video was ever processed

    while attempt < max_retries:
        attempt += 1
        print(f"\n--- Attempt {attempt}/{max_retries} ---")
        try:
            async with TikTokApi() as api:
                print("Creating new TikTok session...")
                # Setup session, required for the async version
                await api.create_sessions(ms_tokens=[ms_token], num_sessions=1, sleep_after=1, headless=False, browser='webkit')

                # print(f"Attempting to fetch hashtag info for #funny...")
                # try:
                #     hashtag = api.hashtag(name="funny")
                #     hashtag_info = await hashtag.info() # Might throw if hashtag not found or blocked
                #     print(f"Successfully fetched hashtag info: {hashtag_info.get('challengeInfo', {}).get('stats', '{}')}")
                # except Exception as e:
                #     print(f"Error fetching hashtag info in attempt {attempt}: {e}")
                #     if attempt < max_retries:
                #         print("Retrying after delay...")
                #         await asyncio.sleep(2) # Wait before next attempt
                #         continue # Skip to next attempt
                #     else:
                #         print("Max retries reached for fetching hashtag info.")
                #         break # Exit the while loop

                # print(f"Fetching videos for hashtag #funny (count=1 expected)...")
                # # The count parameter seems unreliable; we fetch and break after the first.
                # videos = hashtag.videos(count=1)

                # tag = api.hashtag(name="funny")

                found_any_videos_this_attempt = False
                print("Starting video processing loop for this attempt...")

                # async for video in tag.videos(count=5): # Use async for to iterate
                async for video in api.trending.videos(count=5):
                    found_any_videos_this_attempt = True # Mark that we found a video from the API
                    try:
                        video_info = video.as_dict
                        duration = video_info.get("video", {}).get("duration", 0)
                        play_count = video_info.get("stats", {}).get("playCount", 0)
                        author_id = video_info.get("author", {}).get("uniqueId")
                        video_id = video_info.get("id")
                        constructed_url = None
                        if author_id and video_id:
                            constructed_url = f"https://www.tiktok.com/@{author_id}/video/{video_id}"

                        print(f"\nProcessing Video {video_id}:")
                        print(f"  Duration: {duration} (Condition: < {max_duration})")
                        print(f"  Play Count: {play_count} (Condition: >= {min_views})")
                        print(f"  Constructed URL: {constructed_url} (Condition: exists)")

                        if duration < max_duration and play_count >= min_views and constructed_url:
                            print("  -> MATCH FOUND!")
                            matching_urls.append(constructed_url)
                            # If we find a match, we can potentially stop early,
                            # but let's continue processing this single video for shortest duration logic
                        else:
                            reasons = []
                            if not (duration < max_duration):
                                reasons.append(f"duration ({duration}) !< {max_duration}")
                            if not (play_count >= min_views):
                                reasons.append(f"play_count ({play_count}) !>= {min_views}")
                            if not constructed_url:
                                reasons.append("author_id or video_id missing")
                            print(f"  -> NO MATCH: {', '.join(reasons)}")

                        # --- Track shortest video (independent of matching criteria) ---
                        if constructed_url and duration < shortest_duration:
                            print(f"  -> New shortest duration: {duration} (Previously: {shortest_duration if shortest_duration != float('inf') else 'N/A'})")
                            shortest_duration = duration
                            shortest_video_url = constructed_url

                        processed_a_video = True # Mark that we have processed at least one video overall

                    except Exception as e:
                        print(f"Could not process video info for video ID {video.id if hasattr(video, 'id') else 'Unknown'}: {e}")

                    # --- IMPORTANT: Break after processing the first video ---
                    print("Processed the first video yielded by the API for this attempt.")
                    break # Exit the inner async for loop

                # --- After the inner loop (which processes max 1 video) ---
                if found_any_videos_this_attempt:
                    print(f"Finished video processing for attempt {attempt}.")
                    # If a match was found, we can exit the main retry loop
                    if matching_urls:
                       print("Match found, exiting retry loop.")
                       break
                    # Otherwise, continue to the next attempt (unless max retries reached)
                    # No need for explicit continue here, loop will iterate
                    if processed_a_video:
                        print("No match found, but we processed at least one video. Exiting retry loop.")
                        break

                # --- If API yielded no videos this attempt ---
                else: # if not found_any_videos_this_attempt:
                    print(f"API yielded no videos in attempt {attempt}.")
                    # Fall through to retry or exit based on `attempt < max_retries`

        except Exception as e:
            print(f"An error occurred creating TikTok session or during API interaction in attempt {attempt}: {e}")
            # Decide if error is fatal or retryable
            # For now, we'll just log and let the loop retry if attempts remain

        # --- Wait before next attempt if needed ---
        if attempt < max_retries and not matching_urls: # Only delay if no match found yet and retries remain
             print(f"Waiting before next attempt ({attempt+1}/{max_retries})...")
             await asyncio.sleep(1) # Wait a bit longer before full session restart

    # --- Final Return Logic ---
    if matching_urls:
        print(f"\nFound {len(matching_urls)} video(s) matching criteria. Returning random one.")
        return random.choice(matching_urls)
    # Check the overall flag *before* falling back to shortest video
    elif processed_a_video and shortest_video_url:
        print(f"\nNo videos matched criteria, but videos were processed. Returning video with shortest duration ({shortest_duration}s) as fallback.")
        return shortest_video_url
    else: # No matches and no videos processed successfully
        print("\nNo matching videos found and no fallback video available after all attempts.")
        return None

if __name__ == '__main__':
    start_time = time.monotonic()
    # Run the async function using asyncio
    async def main():
        video_url = await get_random_comedy_video(max_duration=100, min_views=500000)
        if video_url:
            print("Random tiktok video URL found:")
            print(video_url)
        else:
            print("No tiktok video found.")

    asyncio.run(main())

    end_time = time.monotonic()
    elapsed_time = end_time - start_time
    print(f"\n--- Script finished in {elapsed_time:.2f} seconds ---")
