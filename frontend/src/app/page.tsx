"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useStore } from "@/lib/store";
import {
  Plus,
  Cpu,
  LayoutDashboard,
  ShoppingCart,
  Gamepad2,
  Wrench,
  Globe,
  Send,
  Sparkles,
  ChevronRight,
} from "lucide-react";

const categories = [
  { label: "AI Tool", icon: Cpu },
  { label: "Internal Tool", icon: Wrench },
  { label: "SaaS", icon: Globe },
  { label: "Dashboard", icon: LayoutDashboard },
  { label: "E-commerce", icon: ShoppingCart },
  { label: "Game", icon: Gamepad2 },
];

export default function HomePage() {
  const router = useRouter();
  const { createProject, projects } = useStore();
  const [prompt, setPrompt] = useState("");

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!prompt.trim()) return;
    const project = createProject(prompt.trim());
    router.push(`/projects/${project.id}`);
  };

  return (
    <div className="flex flex-col items-center justify-center min-h-screen px-6">
      {/* Hero */}
      <div className="flex flex-col items-center text-center max-w-2xl mb-8 -mt-16">
        <div className="flex -space-x-2 mb-6">
          {[
            { initials: "PM", bg: "#a29bfe" },
            { initials: "AR", bg: "#fd79a8" },
            { initials: "EN", bg: "#00cec9" },
            { initials: "QA", bg: "#fdcb6e" },
            { initials: "PM", bg: "#6c5ce7" },
          ].map((a, i) => (
            <div
              key={i}
              className="flex h-10 w-10 items-center justify-center rounded-full border-2 border-background text-[11px] font-bold"
              style={{ backgroundColor: a.bg, color: "#fff" }}
            >
              {a.initials}
            </div>
          ))}
        </div>
        <h1 className="text-3xl md:text-4xl font-bold tracking-tight mb-2">
          Turn ideas into products that ship
        </h1>
      </div>

      {/* Prompt Input */}
      <div className="w-full max-w-xl">
        <form onSubmit={handleSubmit}>
          <div className="relative rounded-2xl border border-border bg-card shadow-sm">
            <input
              type="text"
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              placeholder="Describe what you want to build..."
              className="w-full bg-transparent px-5 pt-4 pb-12 text-sm placeholder:text-muted-foreground focus:outline-none"
            />
            <div className="absolute bottom-3 left-3 right-3 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  className="flex items-center gap-1 rounded-lg border border-border px-2.5 py-1 text-xs text-muted-foreground hover:bg-accent transition-colors"
                >
                  <Plus className="h-3 w-3" />
                </button>
                <button
                  type="button"
                  className="flex items-center gap-1.5 rounded-lg border border-border px-2.5 py-1 text-xs text-muted-foreground hover:bg-accent transition-colors"
                >
                  <Sparkles className="h-3 w-3" />
                  Theme
                </button>
              </div>
              <button
                type="submit"
                disabled={!prompt.trim()}
                className="flex h-7 w-7 items-center justify-center rounded-full bg-primary text-primary-foreground disabled:opacity-40 hover:opacity-90 transition-opacity"
              >
                <Send className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>
        </form>

        {/* Category Chips */}
        <div className="mt-5">
          <p className="text-sm font-medium text-center mb-3">
            What would you like to build?
          </p>
          <div className="flex items-center justify-center gap-2 flex-wrap">
            {categories.map((cat) => (
              <button
                key={cat.label}
                onClick={() => setPrompt(`Build a ${cat.label.toLowerCase()}`)}
                className="flex items-center gap-1.5 rounded-full border border-border bg-card px-3 py-1.5 text-xs font-medium text-muted-foreground hover:bg-accent hover:text-foreground transition-colors"
              >
                <cat.icon className="h-3 w-3" />
                {cat.label}
              </button>
            ))}
            <button className="flex items-center rounded-full border border-border bg-card px-2 py-1.5 text-xs text-muted-foreground hover:bg-accent transition-colors">
              <ChevronRight className="h-3 w-3" />
            </button>
          </div>
        </div>
      </div>

      {/* Bottom Tabs */}
      <div className="fixed bottom-0 left-[220px] right-0 flex items-center justify-center gap-6 border-t border-border bg-background/80 backdrop-blur-sm py-3">
        <Link
          href="/"
          className="text-sm font-medium text-foreground border-b-2 border-primary pb-0.5"
        >
          Discover
        </Link>
        <Link
          href="/projects"
          className="text-sm font-medium text-muted-foreground hover:text-foreground"
        >
          My Projects{projects.length > 0 && ` (${projects.length})`}
        </Link>
        <button className="text-sm font-medium text-muted-foreground hover:text-foreground">
          Templates
        </button>
      </div>
    </div>
  );
}
