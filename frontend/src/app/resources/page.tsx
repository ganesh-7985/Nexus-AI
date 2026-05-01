import { BookOpen, FileText, Video, ExternalLink } from "lucide-react";

const resources = [
  {
    title: "Getting Started",
    desc: "Learn how to create your first project with Nexus AI agents",
    icon: BookOpen,
    color: "text-blue-500",
  },
  {
    title: "Documentation",
    desc: "Explore the full API reference and agent capabilities",
    icon: FileText,
    color: "text-purple-500",
  },
  {
    title: "Tutorials",
    desc: "Step-by-step guides for common project types",
    icon: Video,
    color: "text-pink-500",
  },
];

export default function ResourcesPage() {
  return (
    <div className="p-8 max-w-4xl mx-auto">
      <h1 className="text-2xl font-bold tracking-tight mb-2">Resources</h1>
      <p className="text-sm text-muted-foreground mb-8">
        Learn how to get the most out of Nexus AI
      </p>

      <div className="space-y-3">
        {resources.map((item) => (
          <div
            key={item.title}
            className="flex items-center gap-4 rounded-xl border border-border bg-card p-4 hover:shadow-sm transition-shadow cursor-pointer group"
          >
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-accent">
              <item.icon className={`h-5 w-5 ${item.color}`} />
            </div>
            <div className="flex-1">
              <p className="text-sm font-medium">{item.title}</p>
              <p className="text-xs text-muted-foreground">{item.desc}</p>
            </div>
            <ExternalLink className="h-4 w-4 text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity" />
          </div>
        ))}
      </div>
    </div>
  );
}
