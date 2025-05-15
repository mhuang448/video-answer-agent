# Frontend Documentation: Video Answer Agent (For You Feed)

## 1. Introduction

This document details the Next.js frontend application for the Video Answer Agent project. Its primary purpose is to provide a TikTok-style vertical video feed where users can watch videos and ask questions about their content using an AI assistant (`@AskAI`).

This frontend is built with **TypeScript**, **Next.js 14+ (App Router)**, and **Tailwind CSS**, prioritizing code clarity, maintainability, and best practices suitable for developers, including those with 1-2 years of experience.

It communicates exclusively with a separate [FastAPI backend service](../backend/BACKEND.md) to fetch video data, submit AI queries, and retrieve asynchronous results.

## 2. Technology Stack

- **Framework:** [Next.js](https://nextjs.org/) (v14+ with App Router)
- **Language:** [TypeScript](https://www.typescriptlang.org/)
- **Styling:** [Tailwind CSS](https://tailwindcss.com/)
- **State Management:** React Hooks (`useState`, `useEffect`, `useRef`, `useCallback`)
- **API Communication:** Native `fetch` API
- **Date Formatting:** `date-fns` (for user-friendly timestamps)

## 3. Project Structure (`frontend/for-you-feed/`)

```
.
├── public/             # Static assets (e.g., images, fonts)
├── src/
│   ├── app/
│   │   ├── api/        # Next.js API Routes (Backend Proxies/Handlers)
│   │   │   ├── query/
│   │   │   │   └── async/route.ts       # Proxy to backend POST /api/query/async
│   │   │   └── status/
│   │   │       └── [videoId]/route.ts # Proxy to backend GET /api/query/status/{videoId}
│   │   ├── layout.tsx   # Root layout
│   │   ├── page.tsx     # Main page (Server Component - fetches initial videos)
│   │   └── types.ts     # TypeScript types shared between frontend/backend API
│   ├── components/     # Reusable React components (Client Components)
│   │   ├── CommentSidebar.tsx # Sidebar for viewing/adding comments & AI interactions
│   │   ├── VideoActionsBar.tsx # Buttons next to video (e.g., Comment)
│   │   ├── VideoDataProvider.tsx # Utility for fetching data via Next.js API routes
│   │   ├── VideoFeed.tsx    # Main client component managing the video feed scroll/state
│   │   └── VideoPlayer.tsx  # Component for displaying and controlling a single video
│   └── lib/              # Utility functions (if any - currently minimal)
├── .env.local          # Local environment variables (e.g., API URL) - **DO NOT COMMIT**
├── next.config.mjs     # Next.js configuration
├── package.json        # Project dependencies and scripts
├── postcss.config.js   # PostCSS configuration (for Tailwind)
├── tailwind.config.ts  # Tailwind CSS configuration
└── tsconfig.json       # TypeScript configuration
```

## 4. Core Components

These are the primary building blocks of the user interface:

### a. `src/app/page.tsx` (Server Component)

- **Purpose:** The main entry point for the application route (`/`).
- **Functionality:**
  - Acts as a Next.js Server Component.
  - Fetches the initial list of videos for the "For You" feed by calling `VideoDataProvider.getForYouVideos()` during server-side rendering.
  - Passes the fetched `initialVideos` data to the `VideoFeed` client component.
- **Key Interaction:** Server-side data fetching before rendering.

### b. `src/components/VideoFeed.tsx` (Client Component)

- **Purpose:** Manages the main TikTok-style vertical scrolling feed.
- **Functionality:**
  - Receives `initialVideos` from `page.tsx`.
  - Uses CSS Scroll Snap (`snap-y snap-mandatory`) for smooth vertical scrolling between videos.
  - Employs `IntersectionObserver` to detect which video is currently most visible in the viewport (`activeVideoId`).
  - Ensures only the `active` video attempts to play automatically.
  - Renders a list of `VideoPlayer` components, one for each video.
  - Manages the state (`isCommentSidebarOpen`, `commentVideoId`) for opening/closing the `CommentSidebar`.
  - Passes down necessary props and callbacks to `VideoPlayer` and `VideoActionsBar`.
- **Key Interaction:** Manages the overall feed view, active video state, and orchestrates child components.

### c. `src/components/VideoPlayer.tsx` (Client Component)

- **Purpose:** Displays and controls a single video within the feed.
- **Functionality:**
  - Receives `videoInfo` (URL, ID, etc.) and an `isActive` prop from `VideoFeed`.
  - Uses the HTML `<video>` element to play the video.
  - Handles play/pause logic:
    - Plays automatically when `isActive` becomes true.
    - Pauses automatically when `isActive` becomes false.
    - Toggles play/pause on user click/tap or Spacebar press.
  - Displays a visual progress bar at the bottom, allowing users to seek by clicking.
  - Shows overlay icons (Play/Pause) briefly on state changes.
  - Displays basic video information (e.g., uploader username extracted from `video_id`).
- **Key Interaction:** Video playback control, progress display, responds to `isActive` state from `VideoFeed`.

### d. `src/components/VideoActionsBar.tsx` (Client Component)

- **Purpose:** Displays action buttons vertically aligned to the right of the video player.
- **Functionality:**
  - Currently contains only the "Comment" button.
  - Receives `videoId` and an `onCommentClick` callback from `VideoFeed`.
  - When the comment button is clicked, it invokes the `onCommentClick` callback, passing the `videoId`, which triggers the `VideoFeed` component to open the `CommentSidebar`.
- **Key Interaction:** Triggers the display of the `CommentSidebar`.

### e. `src/components/CommentSidebar.tsx` (Client Component)

- **Purpose:** A slide-in sidebar for viewing comments and interacting with the AI assistant.
- **Functionality:**
  - Opens when triggered by `VideoActionsBar` via `VideoFeed`.
  - Receives the relevant `videoId`.
  - **Fetching Status & Interactions:**
    - On open, it initiates polling using `setInterval`.
    - Periodically calls the Next.js API route `/api/query/status/[videoId]` (which proxies to the backend `GET /api/query/status/{video_id}`).
    - This backend endpoint returns the overall video processing status and a list of all `interactions` (Q&A pairs) for that video.
  - **Displaying Interactions:**
    - Renders the fetched interactions, showing the user's query (`@AskAI ...`) and the AI's answer once `status` is `completed`.
    - Displays loading indicators (`AskAI is thinking...`) for interactions with `status: processing`.
    - Shows error messages for interactions with `status: failed`.
    - Uses `date-fns` to display user-friendly relative timestamps (e.g., "5 minutes ago").
  - **Submitting AI Queries:**
    - Provides a `textarea` for users to input comments.
    - If the input starts with `@AskAI` (case-insensitive):
      - It performs an **optimistic update**: immediately displays the user's query in the list with a "processing" status.
      - It extracts the actual question text.
      - It sends a `POST` request to the Next.js API route `/api/query/async` (which proxies to the backend `POST /api/query/async`) with the `videoId`, `user_query`, and `user_name`.
      - This backend endpoint triggers the asynchronous RAG+MCP pipeline.
    - Handles potential submission errors.
  - **Polling Control:** Stops polling automatically when all fetched interactions for the current video are in a final state (`completed` or `failed`). Restarts polling if a new query is submitted or the sidebar is reopened for a video with pending interactions.
- **Key Interaction:** Fetches Q&A history, submits new AI queries to the backend via Next.js API routes, displays results asynchronously using polling and optimistic UI.

### f. `src/components/VideoDataProvider.tsx` (Utility/Service)

- **Purpose:** Abstracts the logic for fetching video data from the backend API.
- **Functionality:**
  - Provides the `getForYouVideos` async function.
  - This function calls the Next.js API route `/api/videos/foryou` using `fetch`.
  - The Next.js route handler (defined in a separate, non-existent file in this structure, but conceptually present or handled by `page.tsx`'s server-side fetch) would in turn call the actual backend endpoint `GET /api/videos/foryou`.
  - Uses `cache: 'no-store'` to ensure fresh data is fetched on each request (useful for getting random videos).
  - Handles basic error checking and returns an empty array on failure.
- **Key Interaction:** Provides a clean interface for components (like `page.tsx`) to get initial video data without directly dealing with `fetch` specifics. _(Note: The current implementation in `page.tsx` fetches directly, but this component represents the intended abstraction layer)._

### g. Next.js API Routes (`src/app/api/...`)

- **Purpose:** Act as simple proxies between the frontend client components and the FastAPI backend. This avoids exposing the backend URL directly to the browser and handles CORS in one place (the Next.js server).
- **Functionality:**
  - `/api/query/async/route.ts`: Receives `POST` requests from `CommentSidebar`, forwards them to the backend `POST /api/query/async`, and returns the response.
  - `/api/query/status/[videoId]/route.ts`: Receives `GET` requests from `CommentSidebar`, forwards them to the backend `GET /api/query/status/{videoId}`, and returns the response.
  - _(Implicitly)_ `/api/videos/foryou/route.ts` (or equivalent server-side fetch): Forwards `GET` requests to the backend `GET /api/videos/foryou`.
- **Key Interaction:** Securely bridge communication between the browser and the backend service.

## 5. Key Features & UX Flow

1.  **Initial Load ("For You" Feed):**
    - User accesses the application.
    - `page.tsx` (Server Component) fetches a list of 1-3 random, fully processed video URLs and metadata from the backend via `/api/videos/foryou`.
    - `VideoFeed` component renders the vertical feed.
    - The first video in the list becomes `active` and starts playing automatically via `VideoPlayer`.
2.  **Browsing:**
    - User swipes/scrolls vertically.
    - CSS Scroll Snap ensures the next/previous video smoothly snaps into place.
    - `IntersectionObserver` in `VideoFeed` detects the new active video.
    - The previously active `VideoPlayer` pauses, and the new active `VideoPlayer` starts playing.
3.  **Asking an AI Question:**
    - User taps the comment icon on the `VideoActionsBar` for the currently active video.
    - `VideoFeed` opens the `CommentSidebar`, passing the `videoId`.
    - `CommentSidebar` starts polling `/api/query/status/{videoId}` to fetch existing Q&A interactions.
    - User types a question prefixed with `@AskAI` (e.g., `@AskAI What is the main topic?`) into the `textarea`.
    - User submits the question (hits Enter or taps Send).
    - **Optimistic UI:** The `CommentSidebar` immediately displays the user's question with a "processing" status.
    - `CommentSidebar` sends a `POST` request to `/api/query/async` with the `videoId` and question.
    - The backend receives the request, adds the interaction to its state (S3 `interactions.json`), and starts the background RAG+MCP pipeline. The backend returns a `202 Accepted` response almost instantly.
4.  **Receiving the AI Answer:**
    - The `CommentSidebar` continues polling `/api/query/status/{videoId}` every few seconds.
    - Once the backend AI pipeline finishes processing the question, it updates the interaction's status to `completed` and adds the `ai_answer` in S3.
    - On the next successful poll, the `CommentSidebar` receives the updated interaction list.
    - The UI updates: the "processing" indicator for that specific question is replaced with the actual AI-generated answer. The polling might stop if all interactions are now complete.

## 6. Backend Interaction Summary

The frontend communicates with the backend via these proxied Next.js API routes:

- **`GET /api/videos/foryou` (via Next.js route/fetch):** Fetches initial video data for the feed. Called once on page load (server-side).
- **`POST /api/query/async` (via Next.js route):** Submits a new user question (`@AskAI ...`) for asynchronous processing by the backend's RAG+MCP pipeline. Called from `CommentSidebar`.
- **`GET /api/query/status/{videoId}` (via Next.js route):** Polls for the status of AI processing and retrieves all Q&A interactions for a specific video. Called periodically by `CommentSidebar`.

## 7. State Management

Client-side state is managed primarily using standard React Hooks within individual components:

- `useState`: For managing local component state like input values (`commentText`), loading/error states (`isLoading`, `error`), sidebar visibility (`isCommentSidebarOpen`), and the list of fetched/optimistic interactions.
- `useEffect`: For handling side effects, such as fetching data when the component mounts or `videoId` changes, setting up and tearing down the polling `setInterval`, and managing `IntersectionObserver`.
- `useRef`: For accessing DOM elements directly (e.g., `<video>` element in `VideoPlayer`, scroll container in `VideoFeed`), and for persisting values across renders without causing re-renders (e.g., `pollingIntervalRef`, `observers`).
- `useCallback`: To memoize functions, preventing unnecessary re-creation, especially for event handlers passed down as props or used in `useEffect` dependencies.

## 8. Styling

- **Tailwind CSS:** Used extensively for utility-first styling. Class names are applied directly in the JSX.
- **Custom Styles:** Minimal custom CSS. Tailwind's configuration (`tailwind.config.ts`) can be extended if needed.
- **Responsive Design:** Tailwind's built-in responsive modifiers (e.g., `md:`, `lg:`) should be used for adapting the layout to different screen sizes, although the current focus is mobile-first vertical video.

## 9. Setup & Running Locally

1.  **Navigate to the frontend directory:**
    ```bash
    cd frontend/for-you-feed
    ```
2.  **Install dependencies:**
    ```bash
    npm install
    # or
    yarn install
    # or
    pnpm install
    ```
3.  **Configure Environment Variables:**
    - Create a file named `.env.local` in the `frontend/for-you-feed` directory.
    - Add the URL of your **running** backend FastAPI service:
      ```plaintext
      BACKEND_API_URL=http://localhost:8000
      # Replace with your deployed backend URL if not running locally
      ```
4.  **Run the development server:**
    ```bash
    npm run dev
    # or
    yarn dev
    # or
    pnpm dev
    ```
5.  Open [http://localhost:3000](http://localhost:3000) in your browser.

**Note:** The backend FastAPI service must be running and accessible at the URL specified in `BACKEND_API_URL` for the frontend to function correctly.

## 10. Deployment

- **Platform:** Designed for easy deployment on [Vercel](https://vercel.com/).
- **Steps:**
  1.  Connect your Git repository to Vercel.
  2.  Configure the **Root Directory** in Vercel project settings to `frontend/for-you-feed`.
  3.  Set the necessary **Environment Variables** in Vercel:
      - `BACKEND_API_URL`: Point this to the **publicly accessible URL** of your deployed FastAPI backend service (e.g., your AWS App Runner URL).
- **Build Process:** Vercel automatically detects Next.js, builds the application, and deploys it.
