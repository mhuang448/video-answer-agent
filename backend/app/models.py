# app/models.py
from pydantic import BaseModel, Field
from typing import List, Optional

# --- Request Models ---

class QueryRequest(BaseModel):
    video_id: str = Field(..., description="The unique identifier of the processed video.")
    user_query: str = Field(..., description="The question asked by the user.")

class ProcessRequest(BaseModel):
    video_url: str = Field(..., description="The URL of the new TikTok video to process.")
    user_query: str = Field(..., description="The question asked by the user about the new video.")

# --- Response Models ---

class VideoInfo(BaseModel):
    video_id: str
    video_url: str # Publicly accessible S3 URL

class ProcessingStartedResponse(BaseModel):
    status: str = "Query processing started" # Or "Full video processing..."
    video_id: str
    interaction_id: str # Unique ID for this specific Q&A interaction

class Interaction(BaseModel):
    interaction_id: str
    user_query: str
    query_timestamp: str # ISO 8601 format string
    status: str # e.g., 'processing', 'completed', 'failed'
    ai_answer: Optional[str] = None # Answer is None until status is 'completed'
    answer_timestamp: Optional[str] = None # ISO 8601 format string

class StatusResponse(BaseModel):
    video_id: Optional[str] = None
    processing_status: Optional[str] = None # Overall status of the video ingestion
    interactions: List[Interaction] = []

# --- Data Models (Matching S3 JSON structure) ---
# These aren't directly used in API responses but help internally

class ChunkMetadata(BaseModel):
    chunk_name: str
    start_timestamp: str
    end_timestamp: str
    chunk_number: int
    chunk_duration_seconds: float
    normalized_start_time: float
    normalized_end_time: float
    caption: str

class VideoMetadata(BaseModel):
    video_id: str
    source_url: Optional[str] = None
    overall_summary: Optional[str] = None
    key_themes: Optional[str] = None
    total_duration_seconds: Optional[float] = None
    chunks: List[ChunkMetadata] = []
    processing_status: Optional[str] = None
    # interactions: List[Interaction] = [] # interactions are in a separate S3 JSON file

