# Video Processing & Knowledge Base Construction Pipeline

## 1. Overview

This document details the Python script (`process_video_pipeline.py`) responsible for ingesting video content (from TikTok URLs) and transforming it into a structured, high-quality knowledge base. This knowledge base is the foundation for the **RAG portion of our @AskAI agent For Video Q&A**, enabling it to understand and answer user queries about video content accurately and contextually.

The pipeline executes a sequence of automated stages to ensure comprehensive video analysis and prepare the data for efficient retrieval:

1.  **Download:** Acquires the source video .mp4 file.
2.  **Chunking:** Segments the video into semantically meaningful video chunks with the PySceneDetect library.
3.  **Captioning & Summary:** Employs Gemini 2.5 Pro, which has fantastic multimodal understanding capable of understanding videos, to generate rich, descriptive captions for each video chunk. Then, video chunk captions are concatenated and sent to OpenAI's `gpt-4o-mini` model to create an overall video summary and extract key themes, forming the core textual representation of the video.
4.  **Indexing:** Converts the generated captions into vector embeddings (using OpenAI) and stores them within a Pinecone vector database index, making the video's content semantically searchable.

Throughout this workflow, a central JSON metadata file is created and progressively enriched, meticulously tracking the processing and storing all generated data artifacts crucial for the downstream RAG agent.

### Architectural Diagram

![Video Processing & Knowledge Base Creation](../Video_Processing_Pipeline.png)

## 2. Prerequisites

Before running this pipeline, ensure the following components are available and configured:

- **Python:** Version 3.9 or later is recommended.
- **FFmpeg:** This essential command-line tool handles video manipulation for the chunking stage. It **must be installed separately** on your system. Download it from the [official FFmpeg website](https://ffmpeg.org/download.html) and ensure it's accessible via your system's PATH environment variable.
- **API Keys:** Valid access keys for the external services leveraged by the pipeline:
  - Google Gemini API (for high-fidelity video captioning)
  - OpenAI API (for summarization, theme extraction, and text embedding)
  - Pinecone API (for vector storage and retrieval)
- **Environment File (`.env`):** A file named `.env` located in the script's directory (or a parent directory). This file is used to securely manage your API keys. Structure it as follows:

  ```dotenv
  GEMINI_API_KEY="YOUR_GEMINI_API_KEY_HERE"
  OPENAI_API_KEY="YOUR_OPENAI_API_KEY_HERE"
  PINECONE_API_KEY="YOUR_PINECONE_API_KEY_HERE"
  # PINECONE_INDEX_HOST="your-pinecone-host-here" # Optional: Can be left blank; the script will attempt to create/find the index and populate this.
  ```

- **Python Libraries:** The required Python packages specified in the accompanying `requirements.txt` file.

## 3. Setup

1.  **Script Location:** Place `process_video_pipeline.py` within your project structure (e.g., `./data_processing/process_video_pipeline.py`).
2.  **`.env` File:** Create the `.env` file in the script's directory (or a parent) and populate it with your API keys.
3.  **Install FFmpeg:** Follow the official FFmpeg instructions for your operating system. Verify the installation by running `ffmpeg -version` in your terminal.
4.  **Install Python Dependencies:** Navigate to the script's directory in your terminal and execute:
    ```bash
    pip install -r requirements.txt
    ```

## 4. Usage

Run the pipeline from your terminal, providing the target TikTok video URL as a command-line argument:

```bash
python data_processing/process_video_pipeline.py "FULL_TIKTOK_VIDEO_URL"
```

Replace `FULL_TIKTOK_VIDEO_URL` with the actual URL in the standard TikTok format `tiktok.com/@<user_name>/video/<tiktok_id>` (e.g. `tiktok.com/@ridergpt/video/7410486865842703659`). The script logs its progress through each stage to the console.

## 5. Pipeline Stages Breakdown

The script sequentially executes four core stages to process the video:

### Stage 1: Video Download

- **Purpose:** Securely retrieve the video asset and initiate the metadata tracking record.
- **How it Works:**
  - Utilizes the robust `yt-dlp` library for reliable video downloading.
  - Parses the input URL to derive a unique `video_id` (format: `username-tiktokid`).
  - Establishes a standardized directory structure: `./video-data/<video_id>/`.
  - Downloads the video as an MP4 file (`<video_id>.mp4`) into this directory. Includes logic to skip downloading if the target file already exists, ensuring efficiency.
- **Metadata Interaction:**
  - **Creates** the primary JSON metadata file: `./video-data/<video_id>/<video_id>.json`.
  - Initializes this file with the `video_id` and sets the `processing_status` to `"PROCESSING"`, signifying the start of the workflow.

### Stage 2: Video Chunking & Metadata Generation

- **Purpose:** To segment the video into granular units suitable for detailed AI analysis, capturing scene shifts or temporal segments, and recording precise timing information.
- **How it Works:**
  - Employs the `PySceneDetect` library, leveraging its `ContentDetector` to identify natural visual scene changes.
  - Implements a fallback mechanism: If scene detection yields minimal results (<= 1 scene), it defaults to creating **fixed-duration chunks** (e.g., 4 seconds) to guarantee complete video coverage.
  - Orchestrates the external `ffmpeg` tool for the physical video splitting, utilizing NVENC hardware acceleration if detected for enhanced performance.
- **Metadata Interaction:**
  - **Reads** the `<video_id>.json` file.
  - **Enriches** the JSON by adding:
    - `num_chunks`: Total number of segments created.
    - `total_duration_seconds`: Precise duration of the original video.
    - `detection_method`: Logs whether "Scene Detection" or "Fixed X.Xs Chunking" was employed.
    - `chunks`: An array containing detailed metadata for each segment, crucial for contextual understanding:
      - `chunk_name`: Unique identifier (e.g., `username-tiktokid-Scene-001`).
      - `video_id`: Link back to the source video.
      - `start_timestamp`, `end_timestamp`: Human-readable MM:SS.fff format.
      - `chunk_number`: Sequential order (1-based).
      - `normalized_start_time`, `normalized_end_time`: Relative temporal position (0.0-1.0).
      - `chunk_duration_seconds`: Exact length of the chunk.
- **Output Files:** Saves the individual video segments (e.g., `<video_id>-Scene-001.mp4`) into the `./video-data/<video_id>/chunks/` subdirectory.

### Stage 3: Caption Generation & Video Summarization

- **Purpose:** To generate high-quality textual representations of the video's content at both granular (chunk) and holistic (summary) levels, forming the core semantic knowledge base.
- **How it Works:**
  - **Captioning (Gemini):**
    - Uses the `google-generativeai` library to interface with the **Google Gemini API** (`gemini-2.5-pro-preview-03-25` default).
    - Processes each video chunk file (`.mp4`) generated in Stage 2.
    - Uploads the chunk and prompts the multimodal model to produce a detailed, accessibility-focused caption. The prompt guides the AI to describe visuals, actions, audio, and sentiment clearly and concisely, formatted specifically for downstream NLP tasks (plain text, no timestamps).
    - Incorporates retry logic with exponential backoff for resilience against transient API issues.
  - **Summarization & Themes (OpenAI):**
    - Utilizes the `openai` library to interact with the **OpenAI API** (`gpt-4o-mini` default).
    - Aggregates all successfully generated captions chronologically.
    - Makes concurrent API calls to:
      - Generate a concise `overall_summary` capturing the video's essence.
      - Extract key `key_themes` as a comma-separated list.
- **Metadata Interaction:**
  - **Reads** the `<video_id>.json` file.
  - **Enriches** the JSON significantly by:
    - Adding the generated `caption` string (or `null` on failure) within each chunk's object in the `chunks` array.
    - Adding the top-level `overall_summary` and `key_themes` strings.
    - Recording the `summary_generated_at` timestamp.
  - Includes checks to skip generation steps if valid captions/summary already exist, preventing redundant processing.

### Stage 4: Indexing Captions

- **Purpose:** To transform the generated captions into vector embeddings and load them into a specialized vector database (Pinecone), enabling efficient semantic similarity search for the RAG system.
- **How it Works:**
  - **Client & Index Setup:** Initializes OpenAI and Pinecone clients. Ensures the target Pinecone index (default: `video-captions-index`) exists, creating it if necessary using appropriate dimensions (1536 for `text-embedding-ada-002`) and configuration (serverless, cosine metric). Manages the Pinecone index host URL, persisting it to `.env` if needed.
  - **Embedding Generation (OpenAI):**
    - Identifies which video chunk captions require indexing by checking against existing IDs in Pinecone (using `chunk_name` as the ID).
    - Calls the **OpenAI Embeddings API** (`text-embedding-ada-002` default) concurrently for all new captions to generate their vector representations efficiently.
  - **Data Structuring & Upsert (Pinecone):**
    - Packages each embedding vector with its unique ID (`chunk_name`) and essential metadata (caption text, timestamps, `video_id`, etc.). This metadata is crucial for providing context during retrieval.
    - Upserts these vector packages into the Pinecone index in batches for optimal performance. "Upsert" ensures new data is added and existing data can be updated if re-processed.
- **Metadata Interaction:**
  - **Reads** the `<video_id>.json` file.
  - **Updates** the JSON with the final status indicators:
    - Adds/updates `indexing_status` (e.g., "COMPLETED", "SKIPPED_ALREADY_INDEXED", "COMPLETED_WITH_ERRORS").
    - Adds/updates associated fields like `indexing_completed_at`, `vectors_indexed_count`, `indexing_errors`, `indexing_warnings`.
    - Sets the primary `processing_status` field to **`"FINISHED"`**, signaling that the video is fully processed and its knowledge base is ready for querying by the RAG agent.

## 6. Configuration Summary for `process_video_pipeline.py`

Key operational parameters for **this video processing script** are configurable:

- **Via `.env`:** API Keys (`GEMINI_API_KEY`, `OPENAI_API_KEY`, `PINECONE_API_KEY`), `PINECONE_INDEX_HOST`.
- **Via Constants within `process_video_pipeline.py`:** AI Model IDs (`CAPTION_MODEL_NAME`, etc.), Concurrency Limits (`CAPTION_MAX_WORKERS`, etc.), Retry Settings, Pinecone Index Details (`INDEX_NAME`, `EMBED_DIM`, `INDEXING_BATCH_SIZE`).

## 7. Pipeline Output & Next Step: Uploading to S3

A successful execution of `process_video_pipeline.py` results in the following **local** artifacts within the `./video-data/<video_id>/` directory:

1.  **Video Assets:** The original video (`<video_id>.mp4`) and its corresponding chunk files (`<video_id>-Scene-###.mp4` or similar) in the `chunks/` subdirectory.
2.  **Knowledge Manifest:** The fully enriched `<video_id>.json` metadata file, containing captions, summary, themes, timestamps, and status (`"processing_status": "FINISHED"`).
3.  **(In Pinecone):** The Pinecone vector index is populated with semantically searchable embeddings of the video's captions, ready for RAG queries.

**Making Data Accessible via S3:**

These local files, particularly the `.mp4` assets and the `.json` manifest, are essential for the main application but are not yet accessible by the deployed backend (described in `BACKEND.md`). The next crucial step is to upload them to our designated AWS S3 bucket. S3 acts as the central, accessible storage layer.

**The Upload Utility:**

A separate utility script, `video-processing-pipeline/s3_upload_all_video_data.py`, is provided specifically for this task. It is designed to be run **manually after** the processing pipeline finishes for one or more videos.

- **Function:** It efficiently uploads the entire contents of specified local `<video_id>` directories (e.g., from `./video-data/`) to the corresponding path structure within the configured S3 bucket (e.g., `s3://<your-bucket>/video-data/<video_id>/`).

- **Permissions Required:** The script needs AWS credentials with sufficient permissions to interact with S3, specifically `s3:PutObject` for the target bucket and prefix, and potentially `s3:ListBuckets` for initial verification.
- **Providing Credentials:** AWS credentials can be provided in several ways, commonly:
  - Setting environment variables: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, and optionally `AWS_SESSION_TOKEN`. These can be placed in the `.env` file.
  - Using an AWS credentials file (typically `~/.aws/credentials`).
  - Attaching an IAM role with the necessary S3 permissions to the compute environment where the script is run (e.g., an EC2 instance profile).
- **Configuration & Usage:** This script requires its own configuration (primarily the `S3_BUCKET_NAME` set via a `.env` file) and takes the path to the local base directory containing the processed videos as a command-line argument. Ensure your chosen credential method is set up correctly before running. Example usage: `python s3_upload_all_video_data.py ./video-data`

Once the upload script completes, the video assets and metadata are available in S3, allowing the backend API to retrieve them for the video feed and the `@AskAI` question-answering process outlined in the `README.md`.
