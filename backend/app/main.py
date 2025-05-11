# app/main.py
from fastapi import FastAPI, BackgroundTasks, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
import random
import uuid
import boto3
import json
from botocore.exceptions import ClientError, ReadTimeoutError
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

# Import models, utils, and pipeline logic
from .models import (
    QueryRequest, ProcessRequest, VideoInfo,
    ProcessingStartedResponse, StatusResponse, LikeResponse
)
from .utils import (
    CONFIG, get_s3_json_path, get_s3_interactions_path, get_video_metadata_from_s3, get_interactions_from_s3
)
from .pipeline_logic import (
    run_query_pipeline_async,
)

# --- FastAPI App Setup ---
app = FastAPI(
    title="Video Q&A AI Agent API",
    description="API for processing videos and answering questions using RAG+MCP.",
    version="0.1.0"
)

# --- CORS Configuration ---
# Define allowed origins (replace with your actual frontend URLs)
origins = [
    "http://localhost:3000", # Local Next.js frontend
    # Add your Vercel deployment URL(s) here after deployment
    CONFIG['production_frontend_url'], # Production frontend domain
    # e.g., "https://your-frontend-app-name.vercel.app",
    # "*" # Allow all origins (less secure, use specific origins in production)
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"], # Allows GET, POST, etc.
    allow_headers=["*"],
)

# Helper function to list processed video details from S3
def get_processed_video_details() -> List[Dict[str, Any]]:
    """
    Retrieve list of video details (id, like_count, uploader_name) for videos
    with processing_status 'FINISHED' from S3 metadata files.
    """
    video_details = []
    try:
        s3_client = boto3.client('s3',
                                region_name=CONFIG['aws_region'],
                                aws_access_key_id=CONFIG.get('aws_access_key_id'),
                                aws_secret_access_key=CONFIG.get('aws_secret_access_key'),
                                config=boto3.session.Config(read_timeout=10)) # Add timeout

        paginator = s3_client.get_paginator('list_objects_v2')
        pages = paginator.paginate(
            Bucket=CONFIG['s3_bucket_name'],
            Prefix='video-data/',
            Delimiter='/'
        )

        for page in pages:
            if 'CommonPrefixes' in page:
                for prefix in page['CommonPrefixes']:
                    prefix_path = prefix['Prefix']
                    video_id = prefix_path.strip('/').split('/')[-1]
                    json_key = f"video-data/{video_id}/{video_id}.json"

                    try:
                        response = s3_client.get_object(
                            Bucket=CONFIG['s3_bucket_name'],
                            Key=json_key
                        )
                        metadata = json.loads(response['Body'].read().decode('utf-8'))

                        if metadata.get('processing_status') == "FINISHED":
                            details = {
                                "video_id": video_id,
                                "like_count": metadata.get('like_count', random.randint(50000, 5000000)), # Default to random number between 50k and 5M
                                "uploader_name": metadata.get('uploader_name') # Can be None
                            }
                            video_details.append(details)
                    except ClientError as e:
                        # Log error reading specific JSON but continue
                        if e.response['Error']['Code'] == 'NoSuchKey':
                             print(f"Metadata JSON not found for {video_id}, skipping.")
                        else:
                             print(f"Error reading JSON for {video_id}: {e}")
                        continue
                    except ReadTimeoutError:
                         print(f"Read timed out for {video_id} JSON, skipping.")
                         continue
                    except json.JSONDecodeError:
                         print(f"Error decoding JSON for {video_id}, skipping.")
                         continue

        return video_details
    except (ClientError, ReadTimeoutError) as e:
        print(f"Error listing or accessing S3 prefixes: {e}")
        return [] # Return empty list on broader S3 access errors
    except Exception as e:
        print(f"Unexpected error listing processed videos: {e}")
        return []


# --- API Endpoints ---

@app.get("/", tags=["Health Check"])
async def read_root():
    """Basic health check endpoint."""
    return {"status": "ok", "message": "Welcome to the Video Q&A AI Agent API!"}


@app.get("/api/videos/foryou", response_model=list[VideoInfo], tags=["Videos"])
async def get_for_you_videos():
    """Returns a list of up to 3 random pre-processed videos with details."""
    try:
        all_processed_details = get_processed_video_details()
        if not all_processed_details:
            print("No processed video details found.")
            return []

        sample_size = min(len(all_processed_details), 3)
        selected_details = random.sample(all_processed_details, sample_size)

        print(f"Selected video IDs: {[details['video_id'] for details in selected_details]}")

        s3_bucket = CONFIG["s3_bucket_name"]
        aws_region = CONFIG["aws_region"]

        videos = []
        for details in selected_details:
            video_id = details["video_id"]
            like_count = details["like_count"]
            if not like_count:
                like_count = random.randint(50000, 5000000)
            video_url = f"https://{s3_bucket}.s3.{aws_region}.amazonaws.com/video-data/{video_id}/{video_id}.mp4"
            videos.append(VideoInfo(
                video_id=video_id,
                video_url=video_url,
                like_count=like_count,
                uploader_name=details["uploader_name"]
            ))

        print(f"Returning {len(videos)} videos for For You feed.")
        return videos
    except Exception as e:
        print(f"Error in /api/videos/foryou: {e}")
        # Avoid raising HTTPException here to prevent frontend errors if S3 is slow/unavailable
        # Instead, return an empty list, frontend should handle this gracefully.
        return []


@app.post("/api/query/async", response_model=ProcessingStartedResponse, status_code=202, tags=["Query"])
async def query_processed_video(query: QueryRequest, background_tasks: BackgroundTasks):
    """Triggers async query processing for a processed video, including username."""
    print(f"Received query for processed video {query.video_id} by user '{query.user_name}': {query.user_query}") # Log username

    interaction_id = str(uuid.uuid4())
    query_timestamp = datetime.now(timezone.utc).isoformat()
    s3_json_path = get_s3_json_path(query.video_id)
    s3_interactions_path = get_s3_interactions_path(query.video_id)
    s3_bucket = CONFIG["s3_bucket_name"]

    # Create the interaction data structure including username
    interaction = {
        "interaction_id": interaction_id,
        "user_name": query.user_name, # Added username
        "user_query": query.user_query,
        "query_timestamp": query_timestamp,
        "status": "processing",
        "ai_answer": None, # Initialize optional fields
        "answer_timestamp": None
    }

    # Add the task to run in the background
    background_tasks.add_task(
        run_query_pipeline_async,
        video_id=query.video_id,
        user_query=query.user_query,
        user_name=query.user_name, # Pass username
        interaction_id=interaction_id,
        s3_json_path=s3_json_path,
        s3_interactions_path=s3_interactions_path,
        s3_bucket=s3_bucket,
        interaction_data=interaction # Pass the whole initial dict
    )

    return ProcessingStartedResponse(
        status="Query processing started",
        video_id=query.video_id,
        interaction_id=interaction_id
    )


@app.get("/api/query/status/{video_id}", response_model=StatusResponse, tags=["Query"])
async def get_query_status(video_id: str):
    """Pollable endpoint to check video status and get all interactions."""
    print(f"Checking status for video_id: {video_id}")
    s3_bucket = CONFIG["s3_bucket_name"]
    aws_region = CONFIG["aws_region"]
    s3_json_path = get_s3_json_path(video_id)
    s3_interactions_path = get_s3_interactions_path(video_id)

    video_metadata: Optional[Dict[str, Any]] = None
    interactions: List[Dict[str, Any]] = []
    processing_status: Optional[str] = None
    like_count: Optional[int] = None
    uploader_name: Optional[str] = None
    video_url: Optional[str] = None

    # --- Get Video Metadata ---
    try:
        video_metadata = get_video_metadata_from_s3(s3_bucket, s3_json_path)
        processing_status = video_metadata.get("processing_status")
        like_count = video_metadata.get("like_count", 0) # Default to 0
        uploader_name = video_metadata.get("uploader_name")
        # Construct public URL only if metadata is successfully retrieved
        video_url = f"https://{s3_bucket}.s3.{aws_region}.amazonaws.com/video-data/{video_id}/{video_id}.mp4"
        print(f"Retrieved metadata for {video_id}: status={processing_status}, likes={like_count}")

    except FileNotFoundError:
        # Metadata doesn't exist (yet or failed very early). This is common for new submissions.
        print(f"Metadata file not found for {video_id} at {s3_json_path}. Assuming 'processing' or not yet started.")
        processing_status = "PROCESSING"
    except Exception as e:
        # Handle other errors fetching metadata (permissions, S3 issues)
        print(f"Error getting video metadata for {video_id}: {e}")
        # Don't raise 500, let the frontend handle potentially incomplete data
        processing_status = "ERROR_FETCHING_METADATA"


    # --- Get Interactions ---
    try:
        # Only attempt to get interactions if metadata retrieval didn't raise FileNotFoundError immediately,
        # or even if it did, maybe interactions exist. Let's always try.
        interactions = get_interactions_from_s3(s3_bucket, s3_interactions_path)
        print(f"Retrieved {len(interactions)} interactions for {video_id}")
    except FileNotFoundError:
         # It's normal for interactions file not to exist initially.
        print(f"Interactions file not found for {video_id} at {s3_interactions_path}. Returning empty list.")
        interactions = []
    except Exception as e:
        print(f"Error getting interactions for {video_id}: {e}")
        # Return empty interactions but don't fail the whole request
        interactions = [] # Ensure it's an empty list on error


    # --- Construct and Return Response ---
    # Use the StatusResponse model structure
    return StatusResponse(
        processing_status=processing_status,
        video_url=video_url, # Will be None if metadata wasn't fetched
        like_count=like_count, # Will be None if metadata wasn't fetched
        uploader_name=uploader_name, # Will be None if metadata wasn't fetched
        interactions=interactions # Will be empty list if not found or error
    )

# --- Optional: Run directly (uvicorn recommended) ---
# if __name__ == "__main__":
#     import uvicorn
#     uvicorn.run(app, host="0.0.0.0", port=8000)
