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
