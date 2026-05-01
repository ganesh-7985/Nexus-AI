"use client";

import Link from "next/link";
import {
  Sparkles,
  Plus,
  Compass,
  FolderOpen,
  Home,
  Settings,
  Smile,
  Bell,
} from "lucide-react";

const navIcons = [
  { href: "/new", icon: Plus, label: "New" },
  { href: "/resources", icon: Compass, label: "Resources" },
  { href: "/projects", icon: FolderOpen, label: "Projects" },
];

const bottomIcons = [
  { href: "/", icon: Home, label: "Home" },
  { href: "/settings", icon: Settings, label: "Settings" },
  { href: "#", icon: Smile, label: "Feedback" },
  { href: "#", icon: Bell, label: "Notifications" },
];

export function WorkspaceSidebar() {
  return (
    <aside className="hidden md:flex w-12 flex-col items-center bg-sidebar border-r border-sidebar-border py-3 gap-1">
      {/* Brand */}
      <Link
        href="/"
        className="flex h-8 w-8 items-center justify-center rounded-full bg-foreground mb-3"
      >
        <Sparkles className="h-3.5 w-3.5 text-background" />
      </Link>

      {/* Nav */}
      {navIcons.map((item) => (
        <Link
          key={item.label}
          href={item.href}
          className="flex h-8 w-8 items-center justify-center rounded-lg text-muted-foreground hover:bg-sidebar-accent hover:text-foreground transition-colors"
          title={item.label}
        >
          <item.icon className="h-4 w-4" />
        </Link>
      ))}

      {/* Spacer */}
      <div className="flex-1" />

      {/* Bottom */}
      {bottomIcons.map((item) => (
        <Link
          key={item.label}
          href={item.href}
          className="flex h-8 w-8 items-center justify-center rounded-lg text-muted-foreground hover:bg-sidebar-accent hover:text-foreground transition-colors"
          title={item.label}
        >
          <item.icon className="h-4 w-4" />
        </Link>
      ))}

      {/* Avatar */}
      <div className="flex h-6 w-6 items-center justify-center rounded-full bg-sidebar-primary text-sidebar-primary-foreground text-[10px] font-bold mt-2">
        S
      </div>
    </aside>
  );
}
