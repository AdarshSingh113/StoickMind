import { MutationCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router";
import { Toaster, toast } from "sonner";
import { App } from "./App";
import "./index.css";

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 30_000, refetchOnWindowFocus: true, retry: 1 } },
  // A failed action must never be silent: toast it, unless the mutation handles or shows its own error.
  mutationCache: new MutationCache({
    onError: (error, _vars, _ctx, mutation) => {
      if (mutation.options.onError || mutation.meta?.inlineError) return;
      toast.error((error as Error).message || "Something went wrong.");
    },
  }),
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
        <Toaster position="bottom-left" richColors closeButton toastOptions={{ className: "font-sans" }} />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
