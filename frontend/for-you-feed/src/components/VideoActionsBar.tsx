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
    fill="none"
    viewBox="0 0 24 24"
    strokeWidth={1.5}
    stroke="currentColor"
    className="w-6 h-6"
  >
    {" "}
    {/* Adjusted size */}
    <path
      strokeLinecap="round"
      strokeLinejoin="round"
      d="M8.625 12a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0H8.25m4.125 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0H12m4.125 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0h-.375M21 12c0 4.556-4.03 8.25-9 8.25a9.764 9.764 0 0 1-2.555-.337A5.972 5.972 0 0 1 5.41 20.97a5.969 5.969 0 0 1-.474-.065 4.48 4.48 0 0 0 .978-2.025c.09-.457-.133-.901-.467-1.226C3.93 16.178 3 14.189 3 12c0-4.556 4.03-8.25 9-8.25s9 3.694 9 8.25Z"
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
