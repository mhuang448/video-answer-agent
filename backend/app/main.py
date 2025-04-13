# app/main.py
from fastapi import FastAPI, BackgroundTasks, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
import random
import uuid
import boto3
import json
from botocore.exceptions import ClientError
from datetime import datetime, timezone

# Import models, utils, and pipeline logic
from .models import (
    QueryRequest, ProcessRequest, VideoInfo,
    ProcessingStartedResponse, StatusResponse
)
from .utils import (
    CONFIG, determine_if_processed, get_s3_json_path, get_s3_interactions_path,
    generate_unique_video_id, get_s3_video_base_path
)
from .pipeline_logic import (
    run_query_pipeline_async, run_full_pipeline_async,
    get_video_metadata_from_s3, get_interactions_from_s3,
    # Assume this helper exists to list preprocessed video IDs
    # get_list_of_preprocessed_video_ids
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

# Helper function to list processed videos from S3
def get_list_of_processed_video_ids():
    """
    Retrieve list of processed video IDs from S3 by scanning the video-data/ prefix 
    and checking the processing_status in each video's JSON metadata file.
    """
    try:
        s3_client = boto3.client('s3', 
                                region_name=CONFIG['aws_region'],
                                aws_access_key_id=CONFIG.get('aws_access_key_id'),
                                aws_secret_access_key=CONFIG.get('aws_secret_access_key'))
        
        # List all objects with prefix video-data/
        paginator = s3_client.get_paginator('list_objects_v2')
        pages = paginator.paginate(
            Bucket=CONFIG['s3_bucket_name'],
            Prefix='video-data/',
            Delimiter='/'
        )
        
        # Extract video IDs from common prefixes (folders)
        video_ids = []
        for page in pages:
            if 'CommonPrefixes' in page:
                for prefix in page['CommonPrefixes']:
                    # Extract video_id from the prefix path
                    prefix_path = prefix['Prefix']  # e.g., 'video-data/username-videoId/'
                    video_id = prefix_path.strip('/').split('/')[-1]  # Get 'username-videoId'
                    
                    # Check if this video has a JSON file with FINISHED status
                    json_key = f"video-data/{video_id}/{video_id}.json"
                    try:
                        response = s3_client.get_object(
                            Bucket=CONFIG['s3_bucket_name'],
                            Key=json_key
                        )
                        metadata = json.loads(response['Body'].read().decode('utf-8'))
                        
                        # Only include videos with FINISHED processing status
                        if metadata.get('processing_status') == "FINISHED":
                            video_ids.append(video_id)
                    except ClientError as e:
                        print(f"Error reading JSON for {video_id}: {e}")
                        continue
        
        return video_ids
    except Exception as e:
        print(f"Error listing processed videos: {e}")
        return []


# --- API Endpoints ---

@app.get("/", tags=["Health Check"])
async def read_root():
    """Basic health check endpoint."""
    return {"status": "ok", "message": "Welcome to the Video Q&A AI Agent API!"}


@app.get("/api/videos/foryou", response_model=list[VideoInfo], tags=["Videos"])
async def get_for_you_videos():
    """Returns a list of 3 random pre-processed video IDs and their public S3 URLs."""
    try:
        # Get videos with FINISHED processing status
        all_processed_ids = get_list_of_processed_video_ids()
        if not all_processed_ids:
            return []

        # Get a random sample of up to 3 videos
        sample_size = min(len(all_processed_ids), 3)
        selected_ids = random.sample(all_processed_ids, sample_size)

        s3_bucket = CONFIG["s3_bucket_name"]
        aws_region = CONFIG["aws_region"]
        
        videos = []
        for video_id in selected_ids:
            # Construct direct public S3 URL (since bucket policy allows public read for MP4s)
            video_url = f"https://{s3_bucket}.s3.{aws_region}.amazonaws.com/video-data/{video_id}/{video_id}.mp4"
            videos.append(VideoInfo(video_id=video_id, video_url=video_url))

        return videos
    except Exception as e:
        print(f"Error in /api/videos/foryou: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve videos.")


@app.post("/api/query/async", response_model=ProcessingStartedResponse, status_code=202, tags=["Query"])
async def query_processed_video(query: QueryRequest, background_tasks: BackgroundTasks):
    """Triggers async query processing for a processed video."""
    print(f"Received query for processed video {query.video_id}: {query.user_query}")

    interaction_id = str(uuid.uuid4())
    query_timestamp = datetime.now(timezone.utc).isoformat()
    s3_json_path = get_s3_json_path(query.video_id)
    s3_interactions_path = get_s3_interactions_path(query.video_id)
    s3_bucket = CONFIG["s3_bucket_name"]

    # Create the interaction data structure
    interaction = {
        "interaction_id": interaction_id,
        "user_query": query.user_query,
        "query_timestamp": query_timestamp,
        "status": "processing"
    }

    background_tasks.add_task(
        run_query_pipeline_async,
        query.video_id,
        query.user_query,
        interaction_id,
        query_timestamp,
        s3_json_path,
        s3_interactions_path,
        s3_bucket
    )

    return ProcessingStartedResponse(
        status="Query processing started",
        video_id=query.video_id,
        interaction_id=interaction_id
    )


@app.post("/api/process_and_query/async", response_model=ProcessingStartedResponse, status_code=202, tags=["Query"])
async def process_new_video_and_query(process_req: ProcessRequest, background_tasks: BackgroundTasks):
    """Triggers async FULL pipeline (download to answer) for a NEW video URL."""
    print(f"Received request for new video {process_req.video_url} with query: {process_req.user_query}")

    video_id = generate_unique_video_id(process_req.video_url)
    interaction_id = str(uuid.uuid4())
    query_timestamp = datetime.now(timezone.utc).isoformat()

    s3_json_path = get_s3_json_path(video_id)
    s3_interactions_path = get_s3_interactions_path(video_id)
    s3_video_base_path = get_s3_video_base_path(video_id)
    s3_bucket = CONFIG["s3_bucket_name"]

    # Create the interaction data structure
    interaction = {
        "interaction_id": interaction_id,
        "user_query": process_req.user_query,
        "query_timestamp": query_timestamp,
        "status": "processing"
    }

    background_tasks.add_task(
        run_full_pipeline_async,
        process_req.video_url,
        process_req.user_query,
        video_id,
        s3_video_base_path,
        s3_json_path,
        s3_interactions_path,
        s3_bucket,
        interaction_id,
        query_timestamp
    )

    return ProcessingStartedResponse(
        status="Full video processing and query started",
        video_id=video_id,
        interaction_id=interaction_id
    )


@app.get("/api/query/status/{video_id}", response_model=StatusResponse, tags=["Query"])
async def get_query_status(video_id: str):
    """Pollable endpoint to check status and get all interactions from S3 JSON."""
    print(f"Checking status for video_id: {video_id}")
    s3_bucket = CONFIG["s3_bucket_name"]

    # Get paths for both files
    s3_json_path = get_s3_json_path(video_id)
    s3_interactions_path = get_s3_interactions_path(video_id)
    
    try:
        # Get video metadata for processing_status
        video_metadata = get_processing_status_from_s3(s3_bucket, s3_json_path)
        processing_status = video_metadata.get("processing_status")
        
        # Get interactions (may not exist yet)
        try:
            interactions = get_interactions_from_s3(s3_bucket, s3_interactions_path)
        except Exception as e:
            print(f"Note: Could not retrieve interactions (might not exist yet): {e}")
            interactions = []
        
        # Ensure response matches the Pydantic model
        return StatusResponse(
            video_id=video_id,
            processing_status=processing_status,
            interactions=interactions
        )
    except FileNotFoundError:
        print(f"Metadata file not found for {video_id} at {s3_json_path}")
        raise HTTPException(status_code=404, detail=f"Status not available for video {video_id}. Processing may not have started or completed initial steps.")
    except Exception as e:
        print(f"Error getting status for {video_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve status.")

# --- Optional: Run directly for local testing (though `uvicorn main:app --reload` is better) ---
# if __name__ == "__main__":
#     import uvicorn
#     uvicorn.run(app, host="0.0.0.0", port=8000)
