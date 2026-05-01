"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { useStore } from "@/lib/store";
import {
  FolderOpen,
  Plus,
  MoreHorizontal,
  Globe,
  CheckCircle2,
  Loader2,
  Trash2,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { getProjectFramework, type FrameworkInfo } from "@/lib/api";

const tabs = ["All", "Completed", "Running"];

export default function ProjectsPage() {
  const { projects, deleteProject } = useStore();
  const [activeTab, setActiveTab] = useState("All");
  const [frameworks, setFrameworks] = useState<Record<string, FrameworkInfo>>({});

  // Fetch framework info for completed projects with backendIds
  useEffect(() => {
    projects.forEach((p) => {
      if (p.status === "completed" && p.backendId && !frameworks[p.id]) {
        getProjectFramework(p.backendId)
          .then((info) => {
            if (info.framework !== "unknown") {
              setFrameworks((prev) => ({ ...prev, [p.id]: info }));
            }
          })
          .catch(() => {});
      }
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projects]);

  const filtered = projects.filter((p) => {
    if (activeTab === "Completed") return p.status === "completed";
    if (activeTab === "Running") return p.status === "running";
    return true;
  });

  const formatDate = (ts: number) =>
    new Date(ts).toLocaleDateString("en-US", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    });

  return (
    <div className="p-8 max-w-5xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold tracking-tight">My Projects</h1>
        <Link
          href="/"
          className="text-sm text-muted-foreground cursor-pointer hover:text-foreground"
        >
          + New Project
        </Link>
      </div>

      {/* Tabs */}
      <div className="flex items-center gap-1 mb-8">
        {tabs.map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={cn(
              "px-4 py-1.5 rounded-full text-sm font-medium transition-colors",
              activeTab === tab
                ? "bg-foreground text-background"
                : "text-muted-foreground hover:bg-accent",
            )}
          >
            {tab}
            {tab === "All" && projects.length > 0 && (
              <span className="ml-1 text-xs opacity-60">
                ({projects.length})
              </span>
            )}
          </button>
        ))}
      </div>

      {/* Project Grid */}
      {filtered.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-24 text-center">
          <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-accent mb-4">
            <FolderOpen className="h-7 w-7 text-muted-foreground" />
          </div>
          <h3 className="text-lg font-semibold mb-2">
            {activeTab === "All" ? "No projects yet" : `No ${activeTab.toLowerCase()} projects`}
          </h3>
          <p className="text-sm text-muted-foreground mb-6 max-w-sm">
            Create your first project and it will appear here with a live
            preview.
          </p>
          <Link
            href="/"
            className="inline-flex items-center gap-2 rounded-full bg-primary text-primary-foreground px-5 py-2 text-sm font-medium hover:opacity-90 transition-opacity"
          >
            <Plus className="h-4 w-4" />
            New Project
          </Link>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5">
          {filtered.map((project) => (
            <div
              key={project.id}
              className="group rounded-xl border border-border bg-card overflow-hidden hover:shadow-md transition-shadow"
            >
              {/* Thumbnail — link to workspace */}
              <Link href={`/projects/${project.id}`}>
                <div
                  className="h-40 relative flex items-center justify-center"
                  style={{ backgroundColor: project.color }}
                >
                  <p className="text-sm font-medium text-foreground/50 px-4 text-center line-clamp-3">
                    {project.prompt}
                  </p>
                  {project.status === "completed" && (
                    <Badge className="absolute bottom-2 left-2 bg-foreground text-background text-[10px] gap-1">
                      <CheckCircle2 className="h-2.5 w-2.5" />
                      Completed
                    </Badge>
                  )}
                  {project.status === "running" && (
                    <Badge className="absolute bottom-2 left-2 bg-primary text-primary-foreground text-[10px] gap-1">
                      <Loader2 className="h-2.5 w-2.5 animate-spin" />
                      Running
                    </Badge>
                  )}
                  {frameworks[project.id] && (
                    <Badge className="absolute top-2 right-2 bg-cyan-500/20 text-cyan-300 text-[10px] border border-cyan-500/30">
                      {frameworks[project.id].display_name}
                    </Badge>
                  )}
                </div>
              </Link>
              {/* Info */}
              <div className="px-4 py-3 flex items-center justify-between">
                <Link href={`/projects/${project.id}`} className="flex-1 min-w-0">
                  <p className="text-sm font-medium truncate">{project.name}</p>
                  <p className="text-xs text-muted-foreground">
                    {formatDate(project.createdAt)}
                  </p>
                </Link>
                <button
                  onClick={() => deleteProject(project.id)}
                  className="text-muted-foreground hover:text-destructive opacity-0 group-hover:opacity-100 transition-all p-1"
                  title="Delete project"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
