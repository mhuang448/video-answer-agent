"use client";

import { useState } from "react";

const CommentButton = () => {
  const [isOpen, setIsOpen] = useState(false);

  const handleComment = () => {
    setIsOpen(!isOpen);
  };

  return (
    <button
      className="flex flex-col items-center"
      onClick={handleComment}
      aria-label="Comment on this video"
    >
      <div className="p-2 rounded-full text-white">
        <svg
          width="24"
          height="24"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"></path>
        </svg>
      </div>
      <span className="text-white text-sm">Comment</span>
    </button>
  );
};

export default CommentButton;
