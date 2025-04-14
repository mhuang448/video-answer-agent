"use client";

import React, { useState, useEffect, FormEvent, useRef } from "react";
import { Interaction, StatusResponse, QueryRequest } from "@/app/types"; // Use Interaction type
import { formatDistanceToNow } from "date-fns"; // For user-friendly timestamps

// Define Props
interface CommentSidebarProps {
  isOpen: boolean;
  onClose: () => void;
  videoId: string; // To know which video comments belong to
  commentCount?: number; // Optional: passed from VideoActionsBar if available
}

// Reusable Close Icon Component
const CloseIcon = () => (
  <svg
    xmlns="http://www.w3.org/2000/svg"
    fill="none"
    viewBox="0 0 24 24"
    strokeWidth={1.5}
    stroke="currentColor"
    className="size-5"
  >
    <path
      strokeLinecap="round"
      strokeLinejoin="round"
      d="M6 18 18 6M6 6l12 12"
    />
  </svg>
);

// Reusable Send Icon for Post Button
const SendIcon = () => (
  <svg
    xmlns="http://www.w3.org/2000/svg"
    viewBox="0 0 24 24"
    fill="currentColor"
    className="size-5"
  >
    <path d="M3.478 2.404a.75.75 0 0 0-.926.941l2.432 7.905H13.5a.75.75 0 0 1 0 1.5H4.984l-2.432 7.905a.75.75 0 0 0 .926.94 60.519 60.519 0 0 0 18.445-8.986.75.75 0 0 0 0-1.218A60.517 60.517 0 0 0 3.478 2.404Z" />
  </svg>
);

// Optional: Loading Spinner Icon
const LoadingSpinner = () => (
  <svg
    className="animate-spin -ml-1 mr-2 h-4 w-4 text-gray-400 inline"
    xmlns="http://www.w3.org/2000/svg"
    fill="none"
    viewBox="0 0 24 24"
  >
    <circle
      className="opacity-25"
      cx="12"
      cy="12"
      r="10"
      stroke="currentColor"
      strokeWidth="4"
    ></circle>
    <path
      className="opacity-75"
      fill="currentColor"
      d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
    ></path>
  </svg>
);

// --- Helper Function for Text Cleaning ---
const cleanAiResponse = (text: string): string => {
  // Remove asterisks and hashtags
  return text.replace(/[*#]/g, "");
};

const CommentSidebar: React.FC<CommentSidebarProps> = ({
  isOpen,
  onClose,
  videoId,
  commentCount = 0,
}) => {
  const [commentText, setCommentText] = useState("");
  // State to hold fetched interactions
  const [interactions, setInteractions] = useState<Interaction[]>([]);
  // State for optimistic user queries (cleared on successful fetch)
  const [optimisticQueries, setOptimisticQueries] = useState<Interaction[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pollingIntervalRef = useRef<NodeJS.Timeout | null>(null);
  const isPollingActive = useRef(false); // Prevent multiple intervals
  const commentListRef = useRef<HTMLDivElement>(null); // Ref for scrolling

  useEffect(() => {
    if (isOpen) {
      console.log(`Comment sidebar opened for video: ${videoId}`);
      // Fetch comments logic would go here
      // For now, clear optimistic comments when switching videos or reopening
      setInteractions([]);
      setOptimisticQueries([]);
    }
  }, [isOpen, videoId]);

  // --- Fetching and Polling Logic ---
  const fetchStatus = async () => {
    if (!videoId) return;
    // console.log(`Polling status for video: ${videoId}`); // Log polling attempt
    setError(null);
    try {
      // Call the Next.js API route handler
      const response = await fetch(`/api/query/status/${videoId}`);
      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(
          errorData.error || `Failed to fetch status: ${response.statusText}`
        );
      }
      const data: StatusResponse = await response.json();

      // Merge optimistic updates: If a fetched interaction matches an optimistic one,
      // replace the optimistic one. Keep optimistic ones not yet fetched.
      setInteractions(data.interactions || []);
      setOptimisticQueries((prevOptimistic) =>
        prevOptimistic.filter(
          (opt) =>
            !data.interactions.some(
              (fetched) => fetched.interaction_id === opt.interaction_id
            )
        )
      );

      // Stop polling if all interactions are completed or failed
      const stillProcessing = (data.interactions || []).some(
        (i) => i.status === "processing"
      );
      if (!stillProcessing && pollingIntervalRef.current) {
        console.log(
          `Stopping polling for ${videoId} - all interactions settled.`
        );
        clearInterval(pollingIntervalRef.current);
        pollingIntervalRef.current = null;
        isPollingActive.current = false;
      }
    } catch (err) {
      // Explicitly type err as Error or unknown
      // Ensure err is treated as an Error object
      const error =
        err instanceof Error ? err : new Error(String(err ?? "Unknown error"));
      console.error("Error fetching status:", error);
      setError(error.message || "Failed to load comments and statuses.");
      // Optionally stop polling on error
      if (pollingIntervalRef.current) {
        clearInterval(pollingIntervalRef.current);
        pollingIntervalRef.current = null;
        isPollingActive.current = false;
      }
    } finally {
      // setIsLoading(false); // Don't set loading false for polling
    }
  };

  // Start polling when the sidebar opens for a videoId
  useEffect(() => {
    if (isOpen && videoId && !isPollingActive.current) {
      console.log(`Starting polling for video: ${videoId}`);
      setIsLoading(true); // Show initial loading
      fetchStatus().finally(() => setIsLoading(false)); // Fetch immediately, then set interval

      isPollingActive.current = true;
      pollingIntervalRef.current = setInterval(fetchStatus, 5000); // Poll every 5 seconds
    }

    // Cleanup polling on close or videoId change
    return () => {
      if (pollingIntervalRef.current) {
        console.log(`Clearing polling interval for ${videoId}`);
        clearInterval(pollingIntervalRef.current);
        pollingIntervalRef.current = null;
        isPollingActive.current = false;
      }
      // Reset state when sidebar closes or video changes
      setInteractions([]);
      setOptimisticQueries([]);
      setError(null);
      setIsLoading(false);
    };
  }, [isOpen, videoId]); // Dependency array ensures cleanup and restart

  // --- Comment Submission Logic ---
  const handleSubmitComment = async (e: FormEvent) => {
    e.preventDefault();
    const trimmedComment = commentText.trim();
    if (!trimmedComment) return;

    // Check for @AskAI prefix
    const askAiPrefix = "@AskAI";
    if (trimmedComment.toLowerCase().startsWith(askAiPrefix.toLowerCase())) {
      const userQuery = trimmedComment.substring(askAiPrefix.length).trim();
      if (!userQuery) {
        setError("@AskAI tag requires a question after it.");
        return; // Don't submit if query is empty
      }

      // **Optimistic Update**
      const tempId = `temp-${Date.now()}`;
      const optimisticInteraction: Interaction = {
        interaction_id: tempId,
        user_name: "User", // Placeholder - replace with actual logged-in user later
        user_query: userQuery,
        query_timestamp: new Date().toISOString(),
        status: "processing", // Start as processing optimistically
        ai_answer: undefined,
        answer_timestamp: undefined,
      };
      setOptimisticQueries((prev) => [optimisticInteraction, ...prev]);
      setCommentText(""); // Clear input
      setError(null);

      // Scroll to bottom after adding optimistic query
      setTimeout(() => {
        commentListRef.current?.scrollTo({ top: 0, behavior: "smooth" });
      }, 100);

      // **Call the Backend via Next.js API Route**
      try {
        const requestBody: QueryRequest = {
          video_id: videoId,
          user_query: userQuery,
          user_name: "User", // Replace with actual username
        };
        const response = await fetch("/api/query/async", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(requestBody),
        });

        if (!response.ok) {
          const errorData = await response.json();
          throw new Error(
            errorData.error || `Failed to submit query: ${response.statusText}`
          );
        }

        const result = await response.json();
        console.log(
          "Query submitted successfully, interaction ID:",
          result.interaction_id
        );

        // Replace optimistic interaction ID with actual ID if possible
        // (Requires backend to return the full interaction object or just the ID)
        setOptimisticQueries((prev) =>
          prev.map((opt) =>
            opt.interaction_id === tempId
              ? { ...opt, interaction_id: result.interaction_id }
              : opt
          )
        );

        // Start polling if not already active (might be needed if sidebar was just opened)
        if (!pollingIntervalRef.current && isOpen) {
          console.log("Starting polling after first @AskAI submission.");
          isPollingActive.current = true;
          pollingIntervalRef.current = setInterval(fetchStatus, 5000);
          fetchStatus(); // Fetch immediately too
        }
      } catch (err) {
        // Explicitly type err as Error or unknown
        // Ensure err is treated as an Error object
        const error =
          err instanceof Error
            ? err
            : new Error(String(err ?? "Unknown error"));
        console.error("Failed to submit @AskAI query:", error);
        setError(error.message || "Failed to send question to AI.");
        // Remove the failed optimistic query
        setOptimisticQueries((prev) =>
          prev.filter((opt) => opt.interaction_id !== tempId)
        );
      }
    } else {
      // Handle regular comments (optional - currently not saving them)
      console.log("Regular comment submitted (not saved):", trimmedComment);
      // You could add logic here to save regular comments if needed
      // For now, just clear the input
      setCommentText("");
      // Optionally show a message that only @AskAI comments are processed
      // setError("Only comments starting with @AskAI are processed currently.")
    }
  };

  // --- Input Handling ---
  const handleInputChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setCommentText(e.target.value);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmitComment(e as unknown as FormEvent);
    }
  };

  // Close with Escape key
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    if (isOpen) document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, onClose]);

  // --- Rendering Logic ---
  const combinedInteractions = [...optimisticQueries, ...interactions]
    // Simple deduplication based on interaction_id, preferring fetched over optimistic
    .reduce((acc, current) => {
      if (!acc.some((item) => item.interaction_id === current.interaction_id)) {
        acc.push(current);
      }
      return acc;
    }, [] as Interaction[])
    // Sort by timestamp descending (newest first)
    .sort(
      (a, b) =>
        new Date(b.query_timestamp).getTime() -
        new Date(a.query_timestamp).getTime()
    );

  const totalCommentCount = interactions.length; // Use fetched interaction count

  return (
    // No overlay - use a fixed sidebar that doesn't affect video brightness
    <>
      {/* Sidebar Container */}
      <aside
        className={`fixed top-0 right-0 h-full w-full max-w-md bg-black shadow-xl transform transition-transform duration-300 ease-in-out flex flex-col z-50 ${
          isOpen ? "translate-x-0" : "translate-x-full"
        }`}
        onClick={(e) => e.stopPropagation()} // Prevent closing when clicking inside sidebar
        role="dialog"
        aria-modal="true"
        aria-labelledby="comment-sidebar-title"
      >
        {/* Header - Close button moved to right side */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-800 flex-shrink-0">
          <h2
            id="comment-sidebar-title"
            className="text-lg font-semibold text-white"
          >
            Comments
            {commentCount > 0 && (
              <span className="ml-2 text-gray-400">
                {commentCount + totalCommentCount}
              </span>
            )}
          </h2>
          <button
            onClick={onClose}
            aria-label="Close comments sidebar"
            className="text-white hover:text-gray-300 focus:outline-none p-1"
            tabIndex={0}
          >
            <CloseIcon />
          </button>
        </div>

        {/* Comment List - Scrollable with improved spacing */}
        <div
          ref={commentListRef}
          className="flex-grow overflow-y-auto pt-5 px-4 scrollbar-hide"
        >
          {isLoading && (
            <div className="text-center py-10 text-gray-400">
              <LoadingSpinner /> Loading...
            </div>
          )}
          {error && (
            <div className="text-center py-6 px-4 text-red-400 bg-red-900/20 border border-red-700 rounded-md mx-4 my-4">
              Error: {error}
            </div>
          )}
          {!isLoading && combinedInteractions.length === 0 && !error && (
            <div className="text-gray-500 text-center py-16 px-6">
              <p className="text-base">No questions asked yet.</p>
              <p className="text-sm mt-1">
                Ask a question using{" "}
                <code className="bg-gray-700 px-1 py-0.5 rounded text-gray-300">
                  @AskAI
                </code>{" "}
                below!
              </p>
            </div>
          )}
          {!isLoading && combinedInteractions.length > 0 && (
            <ul className="space-y-1 pb-4">
              {combinedInteractions.map((interaction) => (
                <li
                  key={interaction.interaction_id}
                  className="px-3 py-3 rounded-lg hover:bg-gray-800/50 transition-colors duration-150"
                >
                  {/* User Query Part */}
                  <div className="flex items-start space-x-3 mb-2">
                    <div className="w-8 h-8 rounded-full bg-blue-600 flex-shrink-0 flex items-center justify-center text-white font-semibold text-sm">
                      {interaction.user_name?.charAt(0)?.toUpperCase() || "U"}
                    </div>
                    <div className="flex-1">
                      <div className="flex items-center justify-between mb-1">
                        <p className="text-sm font-semibold text-blue-300">
                          {interaction.user_name || "User"}
                        </p>
                        <p
                          className="text-xs text-gray-500"
                          title={new Date(
                            interaction.query_timestamp
                          ).toLocaleString()}
                        >
                          {formatDistanceToNow(
                            new Date(interaction.query_timestamp),
                            { addSuffix: true }
                          )}
                        </p>
                      </div>
                      <p className="text-base text-white">
                        <span className="font-medium text-blue-400">
                          @AskAI
                        </span>{" "}
                        {interaction.user_query}
                      </p>
                    </div>
                  </div>

                  {/* AI Answer Part (Conditional) */}
                  <div className="pl-11 mt-2">
                    {interaction.status === "processing" && (
                      <div className="flex items-center text-xs text-gray-400 italic">
                        <LoadingSpinner /> AskAI is thinking...
                      </div>
                    )}
                    {(interaction.status === "completed" ||
                      interaction.status === "failed") && (
                      <div className="flex items-start space-x-4 p-3 rounded-md bg-gradient-to-br from-gray-800/50 to-gray-900/60 border border-gray-700/50 shadow-sm">
                        <div className="w-8 h-8 rounded-full bg-teal-600 flex-shrink-0 flex items-center justify-center text-white font-semibold text-sm">
                          AI
                        </div>
                        <div className="flex-1">
                          <div className="flex items-center justify-between mb-1">
                            <p className="text-sm font-semibold text-teal-300">
                              AskAI
                            </p>
                            {(interaction.status === "completed" &&
                              interaction.answer_timestamp) ||
                            interaction.query_timestamp ? (
                              <p
                                className="text-xs text-gray-500"
                                title={new Date(
                                  interaction.answer_timestamp ||
                                    interaction.query_timestamp
                                ).toLocaleString()}
                              >
                                {formatDistanceToNow(
                                  new Date(
                                    interaction.answer_timestamp ||
                                      interaction.query_timestamp
                                  ),
                                  { addSuffix: true }
                                )}
                              </p>
                            ) : null}
                          </div>
                          <div className="text-base text-gray-200 whitespace-pre-wrap break-words">
                            {interaction.status === "failed"
                              ? "Sorry, I'm having trouble with that question. Please try again."
                              : cleanAiResponse(interaction.ai_answer || "")}
                          </div>
                        </div>
                      </div>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* Comment Input Form - Fixed at bottom with Post button inside */}
        <div className="px-4 pt-3 pb-4 border-t border-gray-800 flex-shrink-0 bg-black">
          {/* Display submit error */}
          {error && !isLoading && (
            <p className="text-xs text-red-400 mb-2">Error: {error}</p>
          )}
          <form
            onSubmit={handleSubmitComment}
            className="relative" // Relative to position the post button
          >
            <textarea
              value={commentText}
              onChange={handleInputChange}
              onKeyDown={handleKeyDown}
              placeholder="Ask a question: @AskAI what is..."
              aria-label="Add a comment starting with @AskAI"
              rows={2} // Reduced rows for compactness
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-4 py-2 pr-12 focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 transition-colors duration-200 resize-none text-white text-sm placeholder-gray-500 disabled:opacity-50"
              disabled={isLoading} // Disable input while initially loading
            />
            <button
              type="submit"
              disabled={!commentText.trim() || isLoading}
              aria-label="Post comment or Ask AI"
              title="Post comment or Ask AI"
              className={`absolute bottom-2 right-2 p-2 rounded-full transition-all duration-200 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-offset-gray-800 focus:ring-blue-500 ${
                commentText.trim()
                  ? "bg-blue-600 hover:bg-blue-500 text-white"
                  : "bg-gray-700 text-gray-500 cursor-not-allowed"
              } disabled:opacity-60 disabled:cursor-not-allowed`}
            >
              <SendIcon />
            </button>
          </form>
        </div>
      </aside>

      {/* Invisible click handler behind the sidebar - only shows when sidebar is open */}
      {isOpen && (
        <div
          className="fixed inset-0 z-40"
          onClick={onClose}
          aria-hidden="true"
        />
      )}
    </>
  );
};

export default CommentSidebar;
