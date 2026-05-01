"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import dynamic from "next/dynamic";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Button } from "@/components/ui/button";
import { useStore, type ChatMessage } from "@/lib/store";
// Simulation removed — backend only
import {
  checkHealth,
  createBackendProject,
  connectPipelineWS,
  getDownloadUrl,
  getPreviewUrl,
  getPublishedUrl,
  getProjectFiles,
  publishProject,
  updateProjectFile,
  startContainer,
  stopContainer,
  getContainerStatus,
  getContainerLogs,
  getProjectFramework,
  checkContainerReady,
  getContainerViewUrl,
  type ProjectFile,
  type WSEvent,
  type ContainerStatus,
  type FrameworkInfo,
} from "@/lib/api";
import {
  Clock,
  Settings,
  Monitor,
  Globe,
  Copy,
  ExternalLink,
  MoreHorizontal,
  Send,
  Plus,
  CheckCircle2,
  Loader2,
  Sparkles,
  ChevronLeft,
  ChevronDown,
  Download,
  FileCode,
  FolderOpen,
  Code2,
  LayoutDashboard,
  Play,
  RefreshCw,
  ChevronRight,
  Save,
  Eye,
  Terminal,
  Rocket,
  Link2,
  Database,
  Search,
  Palette,
  Zap,
  Container,
  Square,
  FileText,
  AlertTriangle,
  Check,
  X,
  Edit3,
  Box,
} from "lucide-react";

const MonacoEditor = dynamic(() => import("@monaco-editor/react"), {
  ssr: false,
  loading: () => (
    <div className="flex items-center justify-center h-full bg-[#1e1e1e]">
      <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
    </div>
  ),
});

/* ── Viewer tabs ───────────────────────────────────────────────────── */
type ViewerTab = "viewer" | "editor" | "overview";

export default function ProjectWorkspacePage() {
  const params = useParams();
  const router = useRouter();
  const projectId = params.id as string;
  const { getProject, updateProject } = useStore();
  const project = getProject(projectId);

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [pipelineRunning, setPipelineRunning] = useState(false);
  const [pipelineDone, setPipelineDone] = useState(false);
  const [input, setInput] = useState("");
  const [backendOnline, setBackendOnline] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [published, setPublished] = useState(false);
  const [publishedUrl, setPublishedUrl] = useState<string>("");
  const [viewerTab, setViewerTab] = useState<ViewerTab>("viewer");
  const [files, setFiles] = useState<ProjectFile[]>([]);
  const [selectedFile, setSelectedFile] = useState<ProjectFile | null>(null);
  const [editorDirty, setEditorDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [activeAgent, setActiveAgent] = useState<string>("");
  const [showConsole, setShowConsole] = useState(false);
  const [consoleLines, setConsoleLines] = useState<string[]>([]);
  const [expandedDirs, setExpandedDirs] = useState<Set<string>>(new Set());
  const [containerStatus, setContainerStatus] = useState<ContainerStatus | null>(null);
  const [containerLoading, setContainerLoading] = useState(false);
  const [containerReady, setContainerReady] = useState(false);
  const [containerLogs, setContainerLogs] = useState("");
  const [frameworkInfo, setFrameworkInfo] = useState<FrameworkInfo | null>(null);
  const [expandedMessages, setExpandedMessages] = useState<Set<string>>(new Set());
  const [collapsedThinking, setCollapsedThinking] = useState<Set<string>>(new Set());
  const [mobilePanel, setMobilePanel] = useState<"chat" | "viewer">("chat");
  const [reviewRequest, setReviewRequest] = useState<{ agent_name: string; artifact_type: string; content: string } | null>(null);
  const [reviewEditing, setReviewEditing] = useState(false);
  const [reviewEditContent, setReviewEditContent] = useState("");
  const abortRef = useRef<(() => void) | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const iframeRef = useRef<HTMLIFrameElement>(null);

  // Check if backend is running
  useEffect(() => {
    checkHealth().then(setBackendOnline);
  }, []);

  // Sync from store on mount
  useEffect(() => {
    if (project) {
      setMessages(project.messages);
      if (project.messages.length === 1 && project.status === "running") {
        startPipeline(project.prompt, project.messages);
      } else if (project.status === "completed") {
        setPipelineDone(true);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  // Auto-scroll only when user is already near the bottom
  useEffect(() => {
    const sentinel = scrollRef.current;
    if (!sentinel) return;
    // Walk up to find the scrollable viewport
    const viewport = sentinel.closest('[data-slot="scroll-area-viewport"]') as HTMLElement | null;
    if (!viewport) {
      sentinel.scrollIntoView({ behavior: "smooth" });
      return;
    }
    const isNearBottom = viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight < 150;
    if (isNearBottom) {
      sentinel.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages]);

  /* ── Start pipeline: backend only ────────────────────────────── */
  const pipelineStartedRef = useRef(false);
  const startPipeline = useCallback(
    async (prompt: string, existingMessages: ChatMessage[]) => {
      // Guard against double-invocation (React Strict Mode)
      if (pipelineStartedRef.current) return;
      pipelineStartedRef.current = true;
      setPipelineRunning(true);
      setPipelineDone(false);
      setActiveAgent("");
      let localMsgs = [...existingMessages];

      const online = await checkHealth();
      setBackendOnline(online);

      if (online) {
        // ── Use real backend ──
        try {
          const bp = await createBackendProject(prompt, project?.name);
          updateProject(projectId, { backendId: bp.id });

          const ws = await connectPipelineWS(bp.id, (event: WSEvent) => {
            switch (event.type) {
              case "connected":
              case "pipeline_start":
                // Connection confirmed — pipeline is starting
                break;

              case "agent_start":
                setActiveAgent(event.agent_name);
                localMsgs = [
                  ...localMsgs,
                  {
                    id: `${Date.now()}-${event.agent_role}-thinking`,
                    role: "agent",
                    agentName: event.agent_name,
                    agentRole: event.agent_role as ChatMessage["agentRole"],
                    content: "",
                    thinking: true,
                    timestamp: Date.now(),
                  },
                ];
                setMessages([...localMsgs]);
                break;

              case "message": {
                // Replace the LAST thinking message (most recent agent)
                const agentLabel = event.sent_from || activeAgent;
                let thinkIdx = -1;
                for (let i = localMsgs.length - 1; i >= 0; i--) {
                  if (localMsgs[i].thinking && localMsgs[i].role === "agent") {
                    thinkIdx = i;
                    break;
                  }
                }
                if (thinkIdx >= 0) {
                  localMsgs[thinkIdx] = {
                    ...localMsgs[thinkIdx],
                    agentName: agentLabel || localMsgs[thinkIdx].agentName,
                    content: event.content,
                    thinking: false,
                  };
                } else {
                  localMsgs = [
                    ...localMsgs,
                    {
                      id: `${Date.now()}-msg`,
                      role: "agent",
                      agentName: agentLabel,
                      content: event.content,
                      timestamp: Date.now(),
                    },
                  ];
                }
                setMessages([...localMsgs]);
                break;
              }

              case "agent_done":
                // Clean up any remaining thinking messages for this agent
                localMsgs = localMsgs.map((m) =>
                  m.thinking && m.role === "agent" && m.agentName === event.agent_name
                    ? { ...m, thinking: false, content: m.content || `${event.agent_name} finished.` }
                    : m
                );
                setMessages([...localMsgs]);
                setActiveAgent("");
                break;

              case "review_request":
                setReviewRequest({
                  agent_name: (event as any).agent_name,
                  artifact_type: (event as any).artifact_type,
                  content: (event as any).content,
                });
                setReviewEditContent((event as any).content);
                break;

              case "review_auto_approved":
                setReviewRequest(null);
                localMsgs = [
                  ...localMsgs,
                  {
                    id: `${Date.now()}-auto-approved`,
                    role: "agent",
                    agentName: "System",
                    content: `Auto-approved ${(event as any).artifact_type === "WritePRD" ? "Product Requirements" : "System Design"} (no response within 5 minutes)`,
                    timestamp: Date.now(),
                  },
                ];
                setMessages([...localMsgs]);
                break;

              case "review_accepted":
                setReviewRequest(null);
                break;

              case "complete":
                pipelineStartedRef.current = false;
                setPipelineRunning(false);
                setPipelineDone(true);
                setActiveAgent("");
                updateProject(projectId, {
                  messages: localMsgs,
                  status: "completed",
                });
                // Auto-load files for editor/preview
                getProjectFiles(bp.id)
                  .then((result) => {
                    setFiles(result.files);
                    if (result.files.length > 0) setSelectedFile(result.files[0]);
                  })
                  .catch(() => {});
                // Auto-start Docker preview container
                setContainerLoading(true);
                startContainer(bp.id)
                  .then((result) => {
                    setContainerStatus(result);
                    if (result.framework) {
                      setFrameworkInfo({ framework: result.framework, display_name: result.framework });
                    }
                  })
                  .catch((e) => {
                    setContainerStatus({ status: "error", message: String(e) });
                  })
                  .finally(() => setContainerLoading(false));
                break;

              case "error":
                pipelineStartedRef.current = false;
                setPipelineRunning(false);
                setActiveAgent("");
                localMsgs = [
                  ...localMsgs,
                  {
                    id: `${Date.now()}-error`,
                    role: "agent",
                    agentName: "System",
                    content: `Error: ${event.message}`,
                    timestamp: Date.now(),
                  },
                ];
                setMessages([...localMsgs]);
                updateProject(projectId, {
                  messages: localMsgs,
                  status: "draft",
                });
                break;
            }
          }, () => {
            // onClose: unstick UI if WS closes unexpectedly
            pipelineStartedRef.current = false;
            setPipelineRunning((running) => {
              if (running) {
                setPipelineDone(false);
                setActiveAgent("");
                localMsgs = [
                  ...localMsgs,
                  {
                    id: `${Date.now()}-disconnect`,
                    role: "agent" as const,
                    agentName: "System",
                    content: "Connection lost. Check the backend server and try again.",
                    timestamp: Date.now(),
                  },
                ];
                setMessages([...localMsgs]);
                updateProject(projectId, {
                  messages: localMsgs,
                  status: "draft",
                });
              }
              return false;
            });
          });
          wsRef.current = ws;
        } catch (err: any) {
          const errMsg = err?.message || String(err);
          console.error("Pipeline backend failed:", errMsg);
          // Show all backend errors to the user instead of silently falling to simulation
          localMsgs = [
            ...localMsgs,
            {
              id: `${Date.now()}-backend-error`,
              role: "agent" as const,
              agentName: "System",
              content: `Backend error: ${errMsg}`,
              timestamp: Date.now(),
            },
          ];
          setMessages([...localMsgs]);
          pipelineStartedRef.current = false;
          setPipelineRunning(false);
          updateProject(projectId, { messages: localMsgs, status: "draft" });
        }
      } else {
        // Backend offline — show error
        localMsgs = [
          ...localMsgs,
          {
            id: `${Date.now()}-offline`,
            role: "agent" as const,
            agentName: "System",
            content: "Backend server is offline. Start the backend with `python3 main.py` in the backend/ directory.",
            timestamp: Date.now(),
          },
        ];
        setMessages([...localMsgs]);
        setPipelineRunning(false);
        updateProject(projectId, { messages: localMsgs, status: "draft" });
      }
    },
    [projectId, updateProject, project?.name],
  );


  // Send a follow-up message
  const handleSend = (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || pipelineRunning) return;
    const userMsg: ChatMessage = {
      id: `${Date.now()}-user`,
      role: "user",
      content: input.trim(),
      timestamp: Date.now(),
    };
    const next = [...messages, userMsg];
    setMessages(next);
    setInput("");
    startPipeline(input.trim(), next);
    updateProject(projectId, { messages: next, status: "running" });
  };

  // Publish handler
  const handlePublish = async () => {
    if (!project?.backendId) {
      setPublished(true);
      return;
    }
    setPublishing(true);
    try {
      const result = await publishProject(project.backendId);
      if (result.error) {
        alert(result.error);
      } else {
        setPublished(true);
        if (result.preview_url) {
          setPublishedUrl(getPublishedUrl(project.backendId));
        }
        const filesResult = await getProjectFiles(project.backendId);
        setFiles(filesResult.files);
        if (filesResult.files.length > 0 && !selectedFile) {
          setSelectedFile(filesResult.files[0]);
        }
      }
    } catch {
      alert("Publish failed. Make sure backend is running.");
    }
    setPublishing(false);
  };

  // Download handler
  const handleDownload = () => {
    if (!project?.backendId) return;
    window.open(getDownloadUrl(project.backendId), "_blank");
  };

  // Load files for editor
  const handleLoadFiles = async () => {
    if (project?.backendId && files.length === 0) {
      try {
        const result = await getProjectFiles(project.backendId);
        setFiles(result.files);
        if (result.files.length > 0) setSelectedFile(result.files[0]);
      } catch { /* ignore */ }
    }
  };

  // Save file from editor
  const handleSaveFile = async () => {
    if (!project?.backendId || !selectedFile) return;
    setSaving(true);
    try {
      await updateProjectFile(project.backendId, selectedFile.path, selectedFile.content);
      setEditorDirty(false);
      iframeRef.current?.contentWindow?.location.reload();
    } catch {
      alert("Save failed");
    }
    setSaving(false);
  };

  // File language detection for Monaco
  const getFileLanguage = (path: string): string => {
    const ext = path.split(".").pop()?.toLowerCase() || "";
    const map: Record<string, string> = {
      py: "python", js: "javascript", ts: "typescript", tsx: "typescript",
      jsx: "javascript", html: "html", css: "css", json: "json", md: "markdown",
      yaml: "yaml", yml: "yaml", xml: "xml", sql: "sql", sh: "shell",
      rs: "rust", go: "go", java: "java", cpp: "cpp", c: "c", rb: "ruby",
    };
    return map[ext] || "plaintext";
  };

  // Build file tree structure
  const buildFileTree = (fileList: ProjectFile[]) => {
    const tree: Record<string, ProjectFile[]> = {};
    const rootFiles: ProjectFile[] = [];
    for (const f of fileList) {
      const parts = f.path.split("/");
      if (parts.length === 1) {
        rootFiles.push(f);
      } else {
        const dir = parts.slice(0, -1).join("/");
        if (!tree[dir]) tree[dir] = [];
        tree[dir].push(f);
      }
    }
    return { tree, rootFiles };
  };

  const toggleDir = (dir: string) => {
    setExpandedDirs(prev => {
      const next = new Set(prev);
      next.has(dir) ? next.delete(dir) : next.add(dir);
      return next;
    });
  };

  // Copy URL to clipboard
  const handleCopyUrl = () => {
    if (publishedUrl) {
      navigator.clipboard.writeText(publishedUrl);
    }
  };

  // Review response handlers
  const handleReviewApprove = () => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "approve" }));
    }
    setReviewRequest(null);
    setReviewEditing(false);
  };

  const handleReviewModify = () => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "modify", content: reviewEditContent }));
    }
    setReviewRequest(null);
    setReviewEditing(false);
  };

  const handleReviewReject = () => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "reject" }));
    }
    setReviewRequest(null);
    setReviewEditing(false);
  };

  // Container preview handlers
  const handleStartContainer = async () => {
    if (!project?.backendId) return;
    setContainerLoading(true);
    try {
      const result = await startContainer(project.backendId);
      setContainerStatus(result);
      if (result.framework) {
        setFrameworkInfo({ framework: result.framework, display_name: result.framework });
      }
    } catch (e) {
      setContainerStatus({ status: "error", message: String(e) });
    }
    setContainerLoading(false);
  };

  const handleStopContainer = async () => {
    if (!project?.backendId) return;
    try {
      await stopContainer(project.backendId);
      setContainerStatus({ status: "stopped" });
    } catch { /* ignore */ }
  };

  const handleRefreshLogs = async () => {
    if (!project?.backendId) return;
    try {
      const { logs } = await getContainerLogs(project.backendId);
      setContainerLogs(logs);
      setConsoleLines(logs.split("\n").filter(Boolean));
    } catch { /* ignore */ }
  };

  // Detect framework when pipeline completes, auto-start Docker for JS frameworks
  useEffect(() => {
    if (pipelineDone && project?.backendId && !frameworkInfo) {
      getProjectFramework(project.backendId)
        .then((info) => {
          setFrameworkInfo(info);
          // Auto-start Docker container for frameworks that need a build step
          if (
            info.framework &&
            ["react", "vue", "nextjs"].includes(info.framework) &&
            !containerStatus?.status &&
            !containerLoading
          ) {
            handleStartContainer();
          }
        })
        .catch(() => {});
    }
  }, [pipelineDone, project?.backendId, frameworkInfo]);

  // Cleanup
  useEffect(() => {
    return () => {
      abortRef.current?.();
      wsRef.current?.close();
    };
  }, []);

  // Poll container readiness when container is running but not yet ready
  useEffect(() => {
    if (containerStatus?.status !== "running" || containerReady || !project?.backendId) return;
    let cancelled = false;
    const poll = async () => {
      while (!cancelled) {
        try {
          const result = await checkContainerReady(project.backendId!);
          if (result.ready && !cancelled) {
            setContainerReady(true);
            return;
          }
        } catch { /* ignore */ }
        await new Promise((r) => setTimeout(r, 2000));
      }
    };
    poll();
    return () => { cancelled = true; };
  }, [containerStatus?.status, containerReady, project?.backendId]);

  // Reset containerReady when container stops
  useEffect(() => {
    if (containerStatus?.status !== "running") {
      setContainerReady(false);
    }
  }, [containerStatus?.status]);

  // Auto-poll container logs when container is running
  useEffect(() => {
    if (containerStatus?.status !== "running" || !project?.backendId) return;
    const interval = setInterval(async () => {
      try {
        const { logs } = await getContainerLogs(project.backendId!);
        setContainerLogs(logs);
        setConsoleLines(logs.split("\n").filter(Boolean));
      } catch { /* ignore */ }
    }, 5000);
    return () => clearInterval(interval);
  }, [containerStatus?.status, project?.backendId]);

  if (!project) {
    return (
      <div className="flex items-center justify-center h-screen">
        <div className="text-center">
          <p className="text-muted-foreground mb-4">Project not found</p>
          <Button variant="outline" onClick={() => router.push("/")}>
            Go Home
          </Button>
        </div>
      </div>
    );
  }

  const dateStr = new Date(project.createdAt).toLocaleDateString("en-US", {
    month: "short", day: "numeric", year: "numeric",
  });

  const previewUrl = project.backendId ? getPreviewUrl(project.backendId) : "";
  const { tree: fileTree, rootFiles } = buildFileTree(files);
  const allDirs = Object.keys(fileTree).sort();

  const toggleExpanded = (id: string) => {
    setExpandedMessages((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const toggleThinkingCollapse = (id: string) => {
    setCollapsedThinking((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const TRUNCATE_LENGTH = 280;

  return (
    <div className="flex h-screen overflow-hidden">
      {/* ── Mobile panel toggle ── */}
      <div className="lg:hidden fixed top-0 left-0 right-0 z-50 flex items-center h-10 bg-background border-b border-border px-2 gap-1">
        <button
          onClick={() => setMobilePanel("chat")}
          className={`flex-1 text-xs font-medium py-1.5 rounded-md transition-colors ${
            mobilePanel === "chat" ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground"
          }`}
        >
          Chat
        </button>
        <button
          onClick={() => setMobilePanel("viewer")}
          className={`flex-1 text-xs font-medium py-1.5 rounded-md transition-colors ${
            mobilePanel === "viewer" ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground"
          }`}
        >
          Preview
        </button>
      </div>

      {/* ── Left: Chat Panel ── */}
      <div className={`flex flex-col w-full lg:w-[380px] border-r border-border bg-background min-h-0 pt-10 lg:pt-0 ${
        mobilePanel !== "chat" ? "hidden lg:flex" : "flex"
      }`}>
        {/* Chat Header */}
        <div className="flex items-center gap-3 px-4 py-3 border-b border-border">
          <button onClick={() => router.push("/")} className="text-muted-foreground hover:text-foreground transition-colors">
            <ChevronLeft className="h-4 w-4" />
          </button>
          <h2 className="text-sm font-semibold flex-1 truncate">{project.name}</h2>
          <div className="flex items-center gap-1.5">
            {backendOnline ? (
              <span className="flex items-center gap-1 text-[10px] text-green-600">
                <span className="h-1.5 w-1.5 rounded-full bg-green-500" /> Live
              </span>
            ) : (
              <span className="flex items-center gap-1 text-[10px] text-amber-500">
                <span className="h-1.5 w-1.5 rounded-full bg-amber-400" /> Sim
              </span>
            )}
          </div>
        </div>

        {/* Messages */}
        <ScrollArea className="flex-1 min-h-0">
          <div className="px-3 py-3 space-y-3">
            <div className="text-center">
              <span className="text-[10px] text-muted-foreground">{dateStr}</span>
            </div>
            {messages.map((msg) => {
              const isExpanded = expandedMessages.has(msg.id);
              const isLong = msg.content && msg.content.length > TRUNCATE_LENGTH;
              const isThinkingCollapsed = collapsedThinking.has(msg.id);

              return (
              <div key={msg.id}>
                {msg.role === "user" ? (
                  <div className="flex justify-end">
                    <div className="rounded-2xl bg-accent px-3 py-2 max-w-[90%]">
                      <p className="text-[13px] leading-relaxed">{msg.content}</p>
                    </div>
                  </div>
                ) : (
                  <div className="space-y-1.5">
                    <div className="flex items-center gap-2">
                      <div className="flex h-6 w-6 items-center justify-center rounded-full bg-primary/10 flex-shrink-0">
                        <Sparkles className="h-3 w-3 text-primary" />
                      </div>
                      <span className="text-xs font-semibold">{msg.agentName}</span>
                      {msg.agentRole && <span className="text-[10px] text-muted-foreground">• {msg.agentRole}</span>}
                    </div>
                    {msg.thinking ? (
                      /* ── Windsurf-style thinking block ── */
                      <div className="ml-8">
                        <button
                          onClick={() => toggleThinkingCollapse(msg.id)}
                          className="group flex items-center gap-1.5 w-full"
                        >
                          <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                            <div className="relative flex h-4 w-4 items-center justify-center">
                              <div className="absolute inset-0 rounded-full border-2 border-primary/30 border-t-primary animate-spin" />
                            </div>
                            <span className="font-medium">Thinking...</span>
                            <ChevronDown className={`h-3 w-3 transition-transform ${isThinkingCollapsed ? "-rotate-90" : ""}`} />
                          </div>
                        </button>
                        {!isThinkingCollapsed && (
                          <div className="mt-1.5 rounded-lg border border-border/50 bg-muted/30 px-3 py-2">
                            <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
                              <Settings className="h-3 w-3 animate-spin flex-shrink-0" />
                              <span>{msg.agentName} is working on this step...</span>
                            </div>
                          </div>
                        )}
                      </div>
                    ) : (
                      <>
                        {msg.content && !msg.checklist && (
                          <div className="ml-8">
                            <div className="rounded-lg border border-border/40 bg-muted/20 px-3 py-2">
                              <p className="text-[12px] text-muted-foreground whitespace-pre-wrap leading-relaxed break-words">
                                {isLong && !isExpanded
                                  ? msg.content.slice(0, TRUNCATE_LENGTH) + "..."
                                  : msg.content}
                              </p>
                              {isLong && (
                                <button
                                  onClick={() => toggleExpanded(msg.id)}
                                  className="mt-1.5 text-[11px] font-medium text-primary hover:text-primary/80 transition-colors"
                                >
                                  {isExpanded ? "Show less" : "Show more"}
                                </button>
                              )}
                            </div>
                          </div>
                        )}
                        {msg.checklist && (
                          <div className="ml-8 rounded-lg border border-border bg-card p-3 space-y-2">
                            <p className="text-xs font-medium text-primary">{msg.content}</p>
                            <ol className="space-y-1.5">
                              {msg.checklist.map((item, i) => (
                                <li key={i} className="flex items-start gap-2 text-xs">
                                  <span className="text-muted-foreground mt-0.5 min-w-[14px]">{i + 1}.</span>
                                  <span className="flex-1">{item.text}</span>
                                  <CheckCircle2 className={`h-3.5 w-3.5 mt-0.5 flex-shrink-0 ${item.done ? "text-primary" : "text-muted-foreground/30"}`} />
                                </li>
                              ))}
                            </ol>
                            <div className="flex gap-2 pt-1">
                              <Button variant="outline" size="sm" className="flex-1 text-[10px] h-6">Edit Plans</Button>
                              <Button size="sm" className="flex-1 text-[10px] h-6 bg-primary">Approve</Button>
                            </div>
                          </div>
                        )}
                      </>
                    )}
                  </div>
                )}
              </div>
              );
            })}
            {/* Review Request Modal */}
            {reviewRequest && (
              <div className="mx-2 rounded-xl border border-amber-500/30 bg-amber-500/5 p-4 space-y-3">
                <div className="flex items-center gap-2">
                  <FileText className="h-4 w-4 text-amber-500" />
                  <span className="text-xs font-semibold text-amber-400">
                    Review: {reviewRequest.artifact_type === "WritePRD" ? "Product Requirements" : "System Design"}
                  </span>
                  <span className="text-[10px] text-muted-foreground ml-auto">from {reviewRequest.agent_name}</span>
                </div>
                {reviewEditing ? (
                  <textarea
                    className="w-full h-48 rounded-lg border border-border bg-background p-3 text-xs font-mono resize-none focus:outline-none focus:ring-1 focus:ring-amber-500"
                    value={reviewEditContent}
                    onChange={(e) => setReviewEditContent(e.target.value)}
                  />
                ) : (
                  <div className="max-h-48 overflow-auto rounded-lg bg-background p-3 text-xs text-muted-foreground whitespace-pre-wrap font-mono border border-border">
                    {reviewRequest.content.slice(0, 3000)}
                    {reviewRequest.content.length > 3000 && "..."}
                  </div>
                )}
                <div className="flex items-center gap-2">
                  <button
                    onClick={handleReviewApprove}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-green-600 text-white text-xs font-medium hover:bg-green-500 transition-colors"
                  >
                    <Check className="h-3 w-3" /> Approve
                  </button>
                  {reviewEditing ? (
                    <button
                      onClick={handleReviewModify}
                      className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-amber-600 text-white text-xs font-medium hover:bg-amber-500 transition-colors"
                    >
                      <Check className="h-3 w-3" /> Save & Continue
                    </button>
                  ) : (
                    <button
                      onClick={() => setReviewEditing(true)}
                      className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-amber-600/20 text-amber-400 text-xs font-medium hover:bg-amber-600/30 transition-colors"
                    >
                      <Edit3 className="h-3 w-3" /> Edit
                    </button>
                  )}
                  <button
                    onClick={handleReviewReject}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-red-600/20 text-red-400 text-xs font-medium hover:bg-red-600/30 transition-colors"
                  >
                    <X className="h-3 w-3" /> Reject
                  </button>
                </div>
              </div>
            )}

            <div ref={scrollRef} />
          </div>
        </ScrollArea>

        {/* Input Bar */}
        <div className="px-4 py-3 border-t border-border">
          <form onSubmit={handleSend}>
            <div className="relative rounded-xl border border-border bg-card">
              <input
                type="text"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder={pipelineRunning ? "Agents are working..." : pipelineDone ? "Send a follow-up..." : "Describe what to build..."}
                disabled={pipelineRunning}
                className="w-full bg-transparent px-4 py-2.5 pr-16 text-sm placeholder:text-muted-foreground focus:outline-none disabled:opacity-50"
              />
              <div className="absolute right-2 top-1/2 -translate-y-1/2 flex items-center gap-1">
                <button type="button" className="text-muted-foreground hover:text-foreground p-1">
                  <Plus className="h-3.5 w-3.5" />
                </button>
                <button type="submit" disabled={!input.trim() || pipelineRunning} className="flex h-6 w-6 items-center justify-center rounded-full bg-primary text-primary-foreground disabled:opacity-40">
                  <Send className="h-3 w-3" />
                </button>
              </div>
            </div>
          </form>
        </div>
      </div>

      {/* ── Right: Main Panel with Toolbar ── */}
      <div className={`flex flex-col flex-1 min-h-0 pt-10 lg:pt-0 ${
        mobilePanel !== "viewer" ? "hidden lg:flex" : "flex"
      }`}>
        {/* ── Top Toolbar (atoms.dev style) ── */}
        <div className="flex items-center h-12 px-3 border-b border-border bg-background">
          {/* Tab Switcher */}
          <div className="flex items-center gap-0.5 bg-muted/50 rounded-lg p-0.5">
            <button
              onClick={() => setViewerTab("viewer")}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all ${
                viewerTab === "viewer"
                  ? "bg-background text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              <Eye className="h-3.5 w-3.5" />
              App Viewer
            </button>
            <button
              onClick={() => { setViewerTab("editor"); handleLoadFiles(); }}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all ${
                viewerTab === "editor"
                  ? "bg-background text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              <Code2 className="h-3.5 w-3.5" />
              Editor
            </button>
            <button
              onClick={() => setViewerTab("overview")}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all ${
                viewerTab === "overview"
                  ? "bg-background text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              <Settings className="h-3.5 w-3.5" />
              Overview
            </button>
          </div>

          {/* Toolbar icons */}
          <div className="flex items-center gap-1 ml-3">
            {viewerTab === "viewer" && (
              <button onClick={() => { try { iframeRef.current?.contentWindow?.location.reload(); } catch { if (iframeRef.current) iframeRef.current.src = iframeRef.current.src; } }} className="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-accent transition-colors" title="Refresh preview">
                <RefreshCw className="h-3.5 w-3.5" />
              </button>
            )}
            {viewerTab === "editor" && editorDirty && (
              <Button size="sm" variant="outline" className="h-7 text-xs gap-1" onClick={handleSaveFile} disabled={saving}>
                {saving ? <Loader2 className="h-3 w-3 animate-spin" /> : <Save className="h-3 w-3" />}
                Save
              </Button>
            )}
          </div>

          <div className="flex-1" />

          {/* Right side: Status + Framework + Container + Publish */}
          <div className="flex items-center gap-2">
            {/* Framework badge */}
            {frameworkInfo && frameworkInfo.framework !== "unknown" && (
              <span className="flex items-center gap-1 px-2 py-1 rounded-md bg-cyan-500/10 text-cyan-400 text-[10px] font-medium border border-cyan-500/20">
                <Box className="h-3 w-3" />
                {frameworkInfo.display_name}
              </span>
            )}

            {pipelineRunning && (
              <span className="text-xs text-primary font-medium flex items-center gap-1.5">
                <span className="h-1.5 w-1.5 rounded-full bg-primary animate-pulse" />
                {activeAgent || "Running..."}
              </span>
            )}

            {pipelineDone && project.backendId && (
              <>
                {/* Container controls */}
                {containerStatus?.status === "running" ? (
                  <Button variant="outline" size="sm" className="h-7 text-xs gap-1 border-green-500/30 text-green-400" onClick={handleStopContainer}>
                    <Square className="h-3 w-3" /> Stop Container
                  </Button>
                ) : (
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-7 text-xs gap-1"
                    onClick={handleStartContainer}
                    disabled={containerLoading}
                  >
                    {containerLoading ? <Loader2 className="h-3 w-3 animate-spin" /> : <Play className="h-3 w-3" />}
                    Docker Preview
                  </Button>
                )}

                <Button variant="outline" size="sm" className="h-7 text-xs gap-1" onClick={handleDownload}>
                  <Download className="h-3 w-3" /> Download
                </Button>
                {published && publishedUrl && (
                  <Button variant="outline" size="sm" className="h-7 text-xs gap-1" onClick={() => window.open(publishedUrl, "_blank")}>
                    <ExternalLink className="h-3 w-3" /> Open Live
                  </Button>
                )}
              </>
            )}

            <Button
              size="sm"
              className="h-7 text-xs gap-1 bg-violet-600 hover:bg-violet-700 text-white"
              disabled={!pipelineDone || publishing}
              onClick={handlePublish}
            >
              {publishing ? <Loader2 className="h-3 w-3 animate-spin" /> : <Rocket className="h-3 w-3" />}
              {published ? "Published" : "Publish"}
            </Button>
          </div>
        </div>

        {/* ── Content Area ── */}
        <div className="flex-1 overflow-hidden">
          {/* ═══ App Viewer Tab ═══ */}
          {viewerTab === "viewer" && (
            <div className="flex flex-col h-full">
              {/* URL bar */}
              {(pipelineDone || published) && previewUrl && (
                <div className="flex items-center gap-2 px-3 py-2 border-b border-border bg-muted/30">
                  <div className="flex items-center gap-2 flex-1 bg-background rounded-lg border border-border px-3 py-1.5">
                    <Globe className="h-3 w-3 text-muted-foreground" />
                    <span className="text-xs text-muted-foreground font-mono flex-1 truncate">{publishedUrl || previewUrl}</span>
                    {publishedUrl && (
                      <button onClick={handleCopyUrl} className="text-muted-foreground hover:text-foreground">
                        <Copy className="h-3 w-3" />
                      </button>
                    )}
                  </div>
                  <button onClick={() => { try { iframeRef.current?.contentWindow?.location.reload(); } catch { if (iframeRef.current) iframeRef.current.src = iframeRef.current.src; } }} className="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-accent">
                    <RefreshCw className="h-3.5 w-3.5" />
                  </button>
                  {showConsole ? (
                    <button onClick={() => setShowConsole(false)} className="text-xs text-muted-foreground hover:text-foreground">Console</button>
                  ) : (
                    <button onClick={() => setShowConsole(true)} className="text-xs text-muted-foreground hover:text-foreground">Console</button>
                  )}
                </div>
              )}

              {/* Iframe / Placeholder */}
              <div className="flex-1 relative">
                {pipelineRunning ? (
                  <div className="absolute inset-0 flex flex-col items-center justify-center bg-gradient-to-br from-background to-muted/50">
                    <Loader2 className="h-10 w-10 text-primary animate-spin mb-4" />
                    <h3 className="text-lg font-semibold mb-1">Building your app...</h3>
                    <p className="text-sm text-muted-foreground">{activeAgent ? `${activeAgent} is working...` : "Agents are working..."}</p>
                  </div>
                ) : containerLoading ? (
                  <div className="absolute inset-0 flex flex-col items-center justify-center bg-gradient-to-br from-background to-muted/50">
                    <Loader2 className="h-10 w-10 text-cyan-500 animate-spin mb-4" />
                    <h3 className="text-lg font-semibold mb-1">Building Docker container...</h3>
                    <p className="text-sm text-muted-foreground">
                      {frameworkInfo ? `Detected: ${frameworkInfo.display_name}` : "Detecting framework..."}
                    </p>
                  </div>
                ) : containerStatus?.status === "running" && project.backendId && containerReady ? (
                  <iframe
                    ref={iframeRef}
                    src={containerStatus.url || getContainerViewUrl(project.backendId)}
                    className="w-full h-full border-0"
                    title="Container Preview"
                  />
                ) : containerStatus?.status === "running" && !containerReady ? (
                  <div className="absolute inset-0 flex flex-col items-center justify-center bg-gradient-to-br from-background to-muted/50">
                    <Loader2 className="h-10 w-10 text-cyan-500 animate-spin mb-4" />
                    <h3 className="text-lg font-semibold mb-1">Container is starting up...</h3>
                    <p className="text-sm text-muted-foreground">
                      Waiting for the dev server to be ready
                    </p>
                  </div>
                ) : pipelineDone && previewUrl ? (
                  <iframe
                    ref={iframeRef}
                    src={publishedUrl || previewUrl}
                    className="w-full h-full border-0"
                    title="App Preview"
                    sandbox="allow-scripts allow-same-origin allow-forms allow-popups"
                  />
                ) : (
                  <div className="absolute inset-0 flex flex-col items-center justify-center bg-gradient-to-br from-background to-muted/50">
                    <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-primary/10 mb-4">
                      <Monitor className="h-8 w-8 text-primary" />
                    </div>
                    <h3 className="text-lg font-semibold mb-1">App Preview</h3>
                    <p className="text-sm text-muted-foreground max-w-xs text-center">
                      Your app will appear here once the agents finish building it.
                    </p>
                  </div>
                )}
              </div>

              {/* Console panel */}
              {showConsole && (
                <div className="h-40 border-t border-border bg-[#1e1e1e] overflow-auto">
                  <div className="flex items-center gap-2 px-3 py-1.5 border-b border-white/10">
                    <Terminal className="h-3 w-3 text-white/50" />
                    <span className="text-[10px] text-white/50 font-medium">Console</span>
                    {containerStatus?.status === "running" && (
                      <button onClick={handleRefreshLogs} className="ml-auto text-[10px] text-white/30 hover:text-white/60">
                        <RefreshCw className="h-3 w-3" />
                      </button>
                    )}
                  </div>
                  <div className="p-2 font-mono text-[11px] text-white/70">
                    {consoleLines.length === 0 ? (
                      <p className="text-white/30">No console output</p>
                    ) : (
                      consoleLines.map((line, i) => <p key={i}>{line}</p>)
                    )}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* ═══ Editor Tab ═══ */}
          {viewerTab === "editor" && (
            <div className="flex h-full">
              {/* File tree sidebar */}
              <div className="w-56 border-r border-border bg-[#1e1e1e] overflow-y-auto flex-shrink-0">
                <div className="p-2">
                  <p className="text-[10px] font-semibold text-white/40 uppercase tracking-wider px-2 py-1.5 mb-1">
                    Explorer
                  </p>
                  {files.length === 0 ? (
                    <p className="text-[11px] text-white/30 italic px-2">
                      {pipelineDone ? "Publish to load files" : "Files appear after build"}
                    </p>
                  ) : (
                    <>
                      {/* Directory groups */}
                      {allDirs.map((dir) => (
                        <div key={dir}>
                          <button
                            onClick={() => toggleDir(dir)}
                            className="w-full flex items-center gap-1 px-2 py-1 text-[11px] text-white/60 hover:text-white hover:bg-white/5 rounded transition-colors"
                          >
                            <ChevronRight className={`h-3 w-3 transition-transform ${expandedDirs.has(dir) ? "rotate-90" : ""}`} />
                            <FolderOpen className="h-3 w-3 text-yellow-500/70" />
                            <span className="truncate">{dir}</span>
                          </button>
                          {expandedDirs.has(dir) && fileTree[dir].map((f) => (
                            <button
                              key={f.path}
                              onClick={() => { setSelectedFile(f); setEditorDirty(false); }}
                              className={`w-full flex items-center gap-1 pl-7 pr-2 py-1 text-[11px] rounded transition-colors ${
                                selectedFile?.path === f.path
                                  ? "bg-white/10 text-white"
                                  : "text-white/50 hover:text-white hover:bg-white/5"
                              }`}
                            >
                              <FileCode className="h-3 w-3 flex-shrink-0" />
                              <span className="truncate">{f.path.split("/").pop()}</span>
                            </button>
                          ))}
                        </div>
                      ))}
                      {/* Root files */}
                      {rootFiles.map((f) => (
                        <button
                          key={f.path}
                          onClick={() => { setSelectedFile(f); setEditorDirty(false); }}
                          className={`w-full flex items-center gap-1 px-2 py-1 text-[11px] rounded transition-colors ${
                            selectedFile?.path === f.path
                              ? "bg-white/10 text-white"
                              : "text-white/50 hover:text-white hover:bg-white/5"
                          }`}
                        >
                          <FileCode className="h-3 w-3 flex-shrink-0" />
                          <span className="truncate">{f.path}</span>
                        </button>
                      ))}
                    </>
                  )}
                </div>
              </div>

              {/* Code editor */}
              <div className="flex-1 flex flex-col">
                {/* Editor tabs */}
                {selectedFile && (
                  <div className="flex items-center h-9 bg-[#252526] border-b border-[#1e1e1e]">
                    <div className="flex items-center gap-1.5 px-3 py-1.5 bg-[#1e1e1e] text-white/80 text-[11px] border-r border-[#1e1e1e]">
                      <FileCode className="h-3 w-3" />
                      {selectedFile.path.split("/").pop()}
                      {editorDirty && <span className="text-amber-400 ml-1">●</span>}
                    </div>
                    <div className="flex-1" />
                    {editorDirty && (
                      <button
                        onClick={handleSaveFile}
                        disabled={saving}
                        className="flex items-center gap-1 px-2 py-1 mr-2 text-[10px] text-white/50 hover:text-white rounded hover:bg-white/5"
                      >
                        {saving ? <Loader2 className="h-3 w-3 animate-spin" /> : <Save className="h-3 w-3" />}
                        Save
                      </button>
                    )}
                  </div>
                )}
                <div className="flex-1">
                  {selectedFile ? (
                    <MonacoEditor
                      height="100%"
                      language={getFileLanguage(selectedFile.path)}
                      value={selectedFile.content}
                      theme="vs-dark"
                      onChange={(val) => {
                        if (val !== undefined && selectedFile) {
                          setSelectedFile({ ...selectedFile, content: val });
                          setEditorDirty(true);
                        }
                      }}
                      options={{
                        fontSize: 13,
                        minimap: { enabled: true },
                        wordWrap: "on",
                        scrollBeyondLastLine: false,
                        automaticLayout: true,
                        padding: { top: 12 },
                      }}
                    />
                  ) : (
                    <div className="flex items-center justify-center h-full bg-[#1e1e1e] text-white/30">
                      <div className="text-center">
                        <Code2 className="h-10 w-10 mx-auto mb-3 opacity-30" />
                        <p className="text-sm">Select a file to edit</p>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* ═══ Overview Tab ═══ */}
          {viewerTab === "overview" && (
            <div className="p-8 overflow-auto h-full bg-gradient-to-br from-background to-muted/30">
              <div className="max-w-3xl mx-auto">
                {/* Project header */}
                <div className="flex items-start gap-4 mb-8">
                  <div className="flex h-14 w-14 items-center justify-center rounded-2xl" style={{ backgroundColor: project.color }}>
                    <Sparkles className="h-6 w-6 text-foreground/60" />
                  </div>
                  <div>
                    <h1 className="text-xl font-bold">{project.name}</h1>
                    <p className="text-sm text-muted-foreground mt-0.5">{project.prompt.slice(0, 100)}</p>
                  </div>
                </div>

                {/* Launch section */}
                <div className="mb-8">
                  <h2 className="text-lg font-semibold mb-2">Launch this app</h2>
                  <p className="text-sm text-muted-foreground mb-4">
                    Publishing makes your project live and unlocks sharing tools. You can keep editing after launch.
                  </p>
                  {!published ? (
                    <Button onClick={handlePublish} disabled={!pipelineDone || publishing} className="bg-violet-600 hover:bg-violet-700 text-white gap-2">
                      {publishing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Rocket className="h-4 w-4" />}
                      Publish App
                    </Button>
                  ) : (
                    <div className="rounded-xl border border-green-500/20 bg-green-500/5 p-4">
                      <div className="flex items-center gap-2 mb-2">
                        <CheckCircle2 className="h-5 w-5 text-green-500" />
                        <span className="font-medium text-green-700 dark:text-green-400">Published!</span>
                      </div>
                      {publishedUrl && (
                        <div className="flex items-center gap-2 mt-2">
                          <div className="flex-1 bg-background rounded-lg border border-border px-3 py-2 font-mono text-xs truncate">
                            {publishedUrl}
                          </div>
                          <Button size="sm" variant="outline" className="h-8 gap-1" onClick={handleCopyUrl}>
                            <Copy className="h-3 w-3" /> Copy
                          </Button>
                          <Button size="sm" variant="outline" className="h-8 gap-1" onClick={() => window.open(publishedUrl, "_blank")}>
                            <ExternalLink className="h-3 w-3" /> Open
                          </Button>
                        </div>
                      )}
                    </div>
                  )}
                </div>

                {/* Feature cards grid */}
                <div className="grid grid-cols-2 gap-4">
                  <div className="rounded-xl border border-border bg-card p-5 hover:shadow-md transition-shadow cursor-pointer">
                    <Zap className="h-5 w-5 text-muted-foreground mb-3" />
                    <h3 className="text-sm font-semibold mb-1">Live App Version</h3>
                    <p className="text-xs text-muted-foreground">Choose a version to go live</p>
                  </div>
                  <div className="rounded-xl border border-border bg-card p-5 hover:shadow-md transition-shadow cursor-pointer">
                    <Globe className="h-5 w-5 text-muted-foreground mb-3" />
                    <h3 className="text-sm font-semibold mb-1">Connected Domains</h3>
                    <p className="text-xs text-muted-foreground">Set a primary URL and custom domains</p>
                  </div>
                  <div className="rounded-xl border border-border bg-card p-5 hover:shadow-md transition-shadow cursor-pointer">
                    <Search className="h-5 w-5 text-muted-foreground mb-3" />
                    <h3 className="text-sm font-semibold mb-1">SEO & Social</h3>
                    <p className="text-xs text-muted-foreground">Improve how your app appears in search</p>
                  </div>
                  <div className="rounded-xl border border-border bg-card p-5 hover:shadow-md transition-shadow cursor-pointer">
                    <Database className="h-5 w-5 text-muted-foreground mb-3" />
                    <h3 className="text-sm font-semibold mb-1">Production Resources</h3>
                    <p className="text-xs text-muted-foreground">Connect database, storage and keys</p>
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
