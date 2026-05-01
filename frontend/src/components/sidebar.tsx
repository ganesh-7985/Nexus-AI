"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Plus,
  FolderOpen,
  Compass,
  Home,
  Smile,
  Bell,
  Settings,
  ChevronDown,
  Sparkles,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useStore } from "@/lib/store";
import { useAuth } from "@/lib/auth-context";
import { LogOut } from "lucide-react";

const navItems = [
  { href: "/new", label: "New Project", icon: Plus },
  { href: "/resources", label: "Resources", icon: Compass },
  { href: "/projects", label: "My Projects", icon: FolderOpen },
];

const bottomIcons = [
  { href: "/", icon: Home, label: "Home" },
  { href: "/settings", icon: Settings, label: "Settings" },
  { href: "#", icon: Smile, label: "Feedback" },
  { href: "#", icon: Bell, label: "Notifications" },
];

export function Sidebar() {
  const pathname = usePathname();
  const { projects } = useStore();
  const { user, signOut } = useAuth();
  const recents = projects.slice(0, 5);
  const userInitial = (user?.email?.[0] || "U").toUpperCase();

  return (
    <aside className="hidden md:flex w-[220px] flex-col bg-sidebar border-r border-sidebar-border">
      {/* Brand */}
      <div className="flex items-center gap-2 px-5 pt-4 pb-2">
        <div className="flex h-7 w-7 items-center justify-center rounded-full bg-foreground">
          <Sparkles className="h-3.5 w-3.5 text-background" />
        </div>
        <span className="text-base font-semibold tracking-tight">Nexus</span>
      </div>

      {/* Workspace Selector */}
      <div className="mx-3 mt-2 mb-3">
        <button className="flex items-center gap-2 w-full rounded-lg bg-sidebar-accent px-3 py-2 text-sm font-medium hover:bg-sidebar-accent/80 transition-colors">
          <div className="flex h-5 w-5 items-center justify-center rounded bg-sidebar-primary text-sidebar-primary-foreground text-[10px] font-bold">
            S
          </div>
          <span className="truncate text-xs">My Workspace</span>
          <ChevronDown className="h-3 w-3 ml-auto text-muted-foreground" />
        </button>
      </div>

      {/* Nav Links */}
      <nav className="px-3 space-y-0.5">
        {navItems.map((item) => {
          const isActive =
            item.href === "/"
              ? pathname === "/"
              : pathname.startsWith(item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "flex items-center gap-2.5 rounded-lg px-3 py-2 text-[13px] font-medium transition-colors",
                isActive
                  ? "bg-sidebar-accent text-sidebar-accent-foreground"
                  : "text-muted-foreground hover:bg-sidebar-accent/60 hover:text-foreground"
              )}
            >
              <item.icon className="h-4 w-4" />
              {item.label}
            </Link>
          );
        })}
      </nav>

      {/* Recents */}
      <div className="px-5 mt-6">
        <p className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider mb-2">
          Recents
        </p>
        <div className="space-y-0.5">
          {recents.length === 0 ? (
            <p className="text-xs text-muted-foreground/70 italic">
              No recent projects
            </p>
          ) : (
            recents.map((p) => (
              <Link
                key={p.id}
                href={`/projects/${p.id}`}
                className="block truncate text-xs text-muted-foreground hover:text-foreground py-1 transition-colors"
              >
                {p.name}
              </Link>
            ))
          )}
        </div>
      </div>

      {/* Spacer */}
      <div className="flex-1" />

      {/* Credits / CTA */}
      <div className="mx-3 mb-3">
        <div className="rounded-lg bg-sidebar-accent px-3 py-2.5 flex items-center gap-2.5 cursor-pointer hover:bg-sidebar-accent/80 transition-colors">
          <div className="flex h-7 w-7 items-center justify-center rounded-full bg-sidebar-accent border border-sidebar-border">
            <Sparkles className="h-3.5 w-3.5 text-sidebar-primary" />
          </div>
          <div>
            <p className="text-xs font-medium">Get Started</p>
            <p className="text-[10px] text-muted-foreground">Create your first app</p>
          </div>
        </div>
      </div>

      {/* Bottom: User profile + icon bar */}
      <div className="border-t border-sidebar-border">
        {user && (
          <div className="flex items-center gap-2 px-4 py-2">
            <div className="flex h-6 w-6 items-center justify-center rounded-full bg-violet-600 text-white text-[10px] font-bold">
              {userInitial}
            </div>
            <span className="text-xs text-muted-foreground truncate flex-1">
              {user.email}
            </span>
            <button onClick={signOut} className="text-muted-foreground hover:text-red-400 transition-colors" title="Sign out">
              <LogOut className="h-3.5 w-3.5" />
            </button>
          </div>
        )}
        <div className="flex items-center justify-between px-4 py-2">
          {bottomIcons.map((item) => (
            <Link
              key={item.label}
              href={item.href}
              className="text-muted-foreground hover:text-foreground transition-colors"
            >
              <item.icon className="h-4 w-4" />
            </Link>
          ))}
        </div>
      </div>
    </aside>
  );
}
