// src/components/VideoActionsBar.tsx
"use client"; // Needed for onClick handler on the button

import React from "react";

// Define Props
type VideoActionsBarProps = {
  videoId: string;
  // Add other potential props like comment count later
  commentCount?: number;
};

// Reusable Icon Component for Clarity
const CommentIcon = () => (
  <svg
    xmlns="http://www.w3.org/2000/svg"
    viewBox="0 0 24 24"
    fill="currentColor"
    className="size-6"
  >
    <path
      fillRule="evenodd"
      d="M4.804 21.644A6.707 6.707 0 0 0 6 21.75a6.721 6.721 0 0 0 3.583-1.029c.774.182 1.584.279 2.417.279 5.322 0 9.75-3.97 9.75-9 0-5.03-4.428-9-9.75-9s-9.75 3.97-9.75 9c0 2.409 1.025 4.587 2.674 6.192.232.226.277.428.254.543a3.73 3.73 0 0 1-.814 1.686.75.75 0 0 0 .44 1.223ZM8.25 10.875a1.125 1.125 0 1 0 0 2.25 1.125 1.125 0 0 0 0-2.25ZM10.875 12a1.125 1.125 0 1 1 2.25 0 1.125 1.125 0 0 1-2.25 0Zm4.875-1.125a1.125 1.125 0 1 0 0 2.25 1.125 1.125 0 0 0 0-2.25Z"
      clipRule="evenodd"
    />
  </svg>
);

const VideoActionsBar: React.FC<VideoActionsBarProps> = ({
  videoId,
  commentCount,
}) => {
  const handleCommentClick = () => {
    console.log(`Comment button clicked for video ${videoId}`);
    // TODO: Implement actual comment functionality (e.g., open modal/panel)
  };

  // Keyboard handler for accessibility
  const handleKeyDown = (event: React.KeyboardEvent<HTMLButtonElement>) => {
    if (event.key === "Enter" || event.key === " ") {
      handleCommentClick();
    }
  };

  return (
    <div className="flex flex-col items-center space-y-6">
      {" "}
      {/* Vertical stack, increased spacing */}
      {/* Comment Button */}
      <button
        onClick={handleCommentClick}
        onKeyDown={handleKeyDown}
        aria-label="View comments" // More specific label
        tabIndex={0}
        className="flex flex-col items-center justify-center text-white focus:outline-none"
      >
        <div className="w-10 h-10 flex items-center justify-center rounded-full bg-black/30 backdrop-blur-sm hover:bg-white/20 transition-colors duration-200">
          <CommentIcon />
        </div>

        {/* Comment count display - conditionally rendered */}
        {commentCount !== undefined && (
          <span className="text-xs font-semibold mt-1 text-white">
            {commentCount}
          </span>
        )}
      </button>
      {/* Future buttons (Like, Share, Bookmark) would go here */}
      {/* Example structure:
            <button className="...">
                <LikeIcon />
                <span className="...">Like Count</span>
            </button>
             */}
    </div>
  );
};

export default VideoActionsBar;
