"use client";

import { usePathname } from "next/navigation";
import { Sidebar } from "@/components/sidebar";
import { WorkspaceSidebar } from "@/components/workspace-sidebar";
import { StoreProvider } from "@/lib/store";
import { AuthProvider, useAuth } from "@/lib/auth-context";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { Loader2 } from "lucide-react";

function AuthGate({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  const pathname = usePathname();
  const router = useRouter();

  const isAuthPage = pathname === "/login" || pathname === "/signup";

  useEffect(() => {
    if (!loading && !user && !isAuthPage) {
      router.replace("/login");
    }
  }, [loading, user, isAuthPage, router]);

  if (loading) {
    return (
      <div className="flex min-h-screen w-full items-center justify-center bg-[#0a0a0a]">
        <Loader2 className="h-8 w-8 animate-spin text-violet-500" />
      </div>
    );
  }

  if (!user && !isAuthPage) return null;
  if (user && isAuthPage) {
    // Redirect authenticated users away from login/signup
    router.replace("/projects");
    return null;
  }

  return <>{children}</>;
}

function AppContent({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { user } = useAuth();

  const isAuthPage = pathname === "/login" || pathname === "/signup";

  if (isAuthPage || !user) {
    return <>{children}</>;
  }

  const isWorkspace =
    /^\/projects\/[^/]+$/.test(pathname) && pathname !== "/projects";

  return (
    <StoreProvider>
      {isWorkspace ? (
        <>
          <WorkspaceSidebar />
          <main className="flex-1 overflow-hidden">{children}</main>
        </>
      ) : (
        <>
          <Sidebar />
          <main className="flex-1 overflow-auto">{children}</main>
        </>
      )}
    </StoreProvider>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <AuthProvider>
      <AuthGate>
        <AppContent>{children}</AppContent>
      </AuthGate>
    </AuthProvider>
  );
}
