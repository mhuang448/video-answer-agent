import LoadingSpinner from "@/components/ui/loading-spinner";

/**
 * Loading fallback component for video feed
 * Displays a centered loading spinner with a message
 */
const LoadingFallback = () => {
  return (
    <div className="h-screen w-full flex items-center justify-center bg-black text-white">
      <div className="flex flex-col items-center gap-3">
        <LoadingSpinner size="large" />
        <p className="text-lg">Loading videos...</p>
      </div>
    </div>
  );
};

export default LoadingFallback;
