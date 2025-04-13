import { Suspense } from "react";
import VideoFeed from "@/components/VideoFeed";
import LoadingFallback from "@/components/LoadingFallback";
import VideoDataProvider from "@/components/VideoDataProvider";

/**
 * Main page component for the For You feed
 * Uses server-side rendering for initial data fetch
 * No caching to ensure fresh videos on every refresh
 */
export default async function ForYouPage() {
  // Fetch videos server-side using our abstracted data provider
  const videos = await VideoDataProvider.getForYouVideos();

  return (
    <Suspense fallback={<LoadingFallback />}>
      <VideoFeed initialVideos={videos} />
    </Suspense>
  );
}

// Proposed changes: need to integrate this with the VideoFeed component
// import { VideoInfo } from "@/app/types"; // Adjust path as needed based on your setup
// import VideoActionsBar from "@/components/VideoActionsBar"; // Import the new component
// import React from "react";

// // --- Basic Video Player Component (Move to src/components/VideoPlayer.tsx if preferred) ---
// interface VideoPlayerProps {
//   videoUrl: string;
//   // Consider adding poster image, etc.
// }

// const VideoPlayer: React.FC<VideoPlayerProps> = ({ videoUrl }) => {
//   if (!videoUrl) {
//     return (
//       <div className="w-full h-full bg-black flex items-center justify-center text-white">
//         Video URL missing
//       </div>
//     );
//   }
//   return (
//     <video
//       className="w-full h-full object-contain" // Use object-contain to avoid cropping, or object-cover if cropping is desired
//       src={videoUrl}
//       controls // Essential for user interaction
//       loop
//       preload="metadata" // Good practice for performance
//       // autoPlay // Be cautious with autoplay, consider adding muted if enabled
//       // muted
//     >
//       Your browser does not support the video tag.
//     </video>
//   );
// };
// // --- End Video Player Component ---

// // --- Data Fetching Function ---
// // This function communicates with your Next.js API Route Handler,
// // which in turn calls the FastAPI backend.
// async function getForYouVideos(): Promise<VideoInfo[]> {
//   try {
//     // Ensure NEXT_PUBLIC_API_BASE_URL is set in your .env.local or environment variables
//     // Defaulting to localhost:3000 where the Next.js app runs, assuming the API route is relative
//     const baseUrl =
//       process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:3000";
//     const apiUrl = `${baseUrl}/api/videos/foryou`; // Path to your Next.js API route handler

//     console.log(`Fetching videos from: ${apiUrl}`); // Log the URL being fetched

//     const response = await fetch(apiUrl, {
//       method: "GET",
//       headers: {
//         "Content-Type": "application/json",
//       },
//       cache: "no-store", // Ensure fresh data for the feed, adjust as needed
//     });

//     if (!response.ok) {
//       // Log detailed error information
//       const errorText = await response.text();
//       console.error(
//         `Error fetching videos: ${response.status} ${response.statusText}`,
//         errorText
//       );
//       throw new Error(`Failed to fetch videos. Status: ${response.status}`);
//     }

//     const data: VideoInfo[] = await response.json();
//     console.log(`Successfully fetched ${data.length} videos.`);
//     return data;
//   } catch (error) {
//     console.error("Error in getForYouVideos:", error);
//     return []; // Return empty array on error to prevent crashing the page
//   }
// }

// // --- Main Page Component ---
// export default async function HomePage() {
//   const videos = await getForYouVideos();

//   // Handle case where no videos are returned
//   if (!videos || videos.length === 0) {
//     return (
//       <main className="flex min-h-screen flex-col items-center justify-center p-4 bg-black text-white">
//         <p>No videos available right now. Try again later.</p>
//         {/* Optionally add a button to retry or submit a new video */}
//       </main>
//     );
//   }

//   // For this example, we'll just render the first video found
//   // In a real app, you'd implement scrolling/swiping logic
//   const currentVideo = videos[0];

//   return (
//     <main className="flex min-h-screen flex-col items-center justify-center p-4 bg-black overflow-hidden">
//       {/* Container to center the video + actions layout */}
//       <div className="flex items-center justify-center gap-4 w-full h-full">
//         {/* Video Player Wrapper */}
//         {/* Adjust height/max-height as needed. Using vh units helps responsiveness. */}
//         {/* aspect-[9/16] enforces the vertical video format */}
//         <div className="relative aspect-[9/16] h-[calc(100vh-80px)] max-h-[800px] w-auto max-w-[calc((100vh-80px)*(9/16))] rounded-lg overflow-hidden bg-gray-900 shadow-lg">
//           {currentVideo.video_url ? (
//             <VideoPlayer videoUrl={currentVideo.video_url} />
//           ) : (
//             <div className="w-full h-full flex items-center justify-center text-white">
//               Video not available.
//             </div>
//           )}
//         </div>

//         {/* Vertical Actions Bar */}
//         <div className="flex-shrink-0">
//           {" "}
//           {/* Prevent bar from shrinking */}
//           <VideoActionsBar videoId={currentVideo.video_id} />
//         </div>
//       </div>
//     </main>
//   );
// }
