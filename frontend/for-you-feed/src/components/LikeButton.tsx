"use client";

import { useState } from "react";
import { HeartIcon } from "./Icons";

interface LikeButtonProps {
  videoId: string;
  initialLikeCount: number;
}

const LikeButton = ({ videoId, initialLikeCount }: LikeButtonProps) => {
  const [liked, setLiked] = useState(false);
  const [likeCount, setLikeCount] = useState(initialLikeCount);
  const [isLoading, setIsLoading] = useState(false);

  // Format like count with K, M for thousands/millions
  const formatLikeCount = (count: number): string => {
    if (count >= 1000000) {
      return `${(count / 1000000).toFixed(1)}M`;
    } else if (count >= 1000) {
      return `${(count / 1000).toFixed(1)}K`;
    }
    return count.toString();
  };

  const handleLike = async () => {
    if (isLoading || liked) return;

    try {
      setIsLoading(true);

      // Call our Next.js API route instead of directly calling the backend
      const response = await fetch(`/api/videos/${videoId}/like`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
      });

      if (!response.ok) {
        throw new Error(`Failed to like video: ${response.statusText}`);
      }

      const data = await response.json();
      setLikeCount(data.like_count);
      setLiked(true);
    } catch (error) {
      console.error("Error liking video:", error);
      // Optionally show error notification
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <button
      className="flex flex-col items-center group"
      onClick={handleLike}
      disabled={isLoading || liked}
      aria-label={liked ? "Liked" : "Like this video"}
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          handleLike();
        }
      }}
    >
      <div
        className={`p-2 rounded-full transition-all duration-300 ${
          liked
            ? "text-red-500 scale-110"
            : "text-white hover:text-pink-200 hover:scale-105"
        }`}
      >
        <HeartIcon filled={liked} />
      </div>
      <span className="text-white text-sm font-medium">
        {formatLikeCount(likeCount)}
      </span>
    </button>
  );
};

export default LikeButton;
