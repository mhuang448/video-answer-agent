"use client";

import { useRef, useEffect } from "react";
import { VideoInfo } from "@/app/types";

interface VideoCardProps {
  video: VideoInfo;
  isActive: boolean;
}

const VideoCard = ({ video, isActive }: VideoCardProps) => {
  const videoRef = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    if (videoRef.current) {
      if (isActive) {
        videoRef.current.play().catch((error) => {
          console.error("Error playing video:", error);
        });
      } else {
        videoRef.current.pause();
        videoRef.current.currentTime = 0;
      }
    }
  }, [isActive]);

  // Format like count with K, M for thousands/millions
  // const formatLikeCount = (count: number): string => {
  //   if (count >= 1000000) {
  //     return `${(count / 1000000).toFixed(1)}M`;
  //   } else if (count >= 1000) {
  //     return `${(count / 1000).toFixed(1)}K`;
  //   }
  //   return count.toString();
  // };

  return (
    <div className="relative h-screen w-full snap-start bg-black flex items-center justify-center overflow-hidden">
      <video
        ref={videoRef}
        src={video.video_url}
        className="absolute h-full w-full object-contain"
        loop
        playsInline
        muted // Consider removing this in production for better user experience
        controls={false}
      />

      {/* Video Info - Improved layout with semi-transparent background */}
      <div className="absolute bottom-20 left-4 z-10 text-white p-3 rounded-lg bg-black/40 backdrop-blur-sm max-w-[70%]">
        <h3 className="text-lg font-semibold mb-1">
          @{video.uploader_name || "Unknown Creator"}
        </h3>
        <p className="text-sm text-gray-200 opacity-90">
          Video ID: {video.video_id.substring(0, 8)}...
        </p>
      </div>
    </div>
  );
};

export default VideoCard;
