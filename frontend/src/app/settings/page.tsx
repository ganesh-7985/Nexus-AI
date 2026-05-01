"use client";

import { useEffect, useState } from "react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Key, Link2, Cpu, Save, Eye, EyeOff, Loader2, CheckCircle2, Cloud } from "lucide-react";
import { checkHealth, getConfig, updateConfig } from "@/lib/api";

const PROVIDERS = [
  { value: "vertex", label: "Vertex AI (GCP credits)" },
  { value: "gemini", label: "Google Gemini (free tier)" },
  { value: "openai", label: "OpenAI" },
  { value: "anthropic", label: "Anthropic Claude" },
  { value: "azure", label: "Azure OpenAI" },
];

const MODELS: Record<string, string[]> = {
  vertex: ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash"],
  gemini: ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash"],
  openai: ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo"],
  anthropic: ["claude-3-5-sonnet-20241022", "claude-3-haiku-20240307"],
  azure: ["gpt-4o"],
};

export default function SettingsPage() {
  const [online, setOnline] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [apiType, setApiType] = useState("vertex");
  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState("gemini-1.5-flash-001");
  const [baseUrl, setBaseUrl] = useState("");
  const [showKey, setShowKey] = useState(false);
  const [hasKey, setHasKey] = useState(false);
  const [gcpProjectId, setGcpProjectId] = useState("");
  const [gcpLocation, setGcpLocation] = useState("us-central1");

  useEffect(() => {
    (async () => {
      const isOnline = await checkHealth();
      setOnline(isOnline);
      if (isOnline) {
        const cfg = await getConfig() as any;
        setApiType(cfg.api_type);
        setModel(cfg.model);
        setBaseUrl(cfg.base_url);
        setHasKey(cfg.has_key);
        if (cfg.gcp_project_id) setGcpProjectId(cfg.gcp_project_id);
        if (cfg.gcp_location) setGcpLocation(cfg.gcp_location);
      }
      setLoading(false);
    })();
  }, []);

  const handleSave = async () => {
    setSaving(true);
    setSaved(false);
    try {
      await updateConfig({
        api_type: apiType,
        api_key: apiKey || undefined,
        model,
        base_url: baseUrl || undefined,
        ...(apiType === "vertex" ? {
          gcp_project_id: gcpProjectId || undefined,
          gcp_location: gcpLocation || undefined,
        } : {}),
      } as any);
      setSaved(true);
      if (apiKey) setHasKey(true);
      setApiKey("");
      setTimeout(() => setSaved(false), 3000);
    } catch {
      alert("Failed to save. Make sure backend is running on port 8000.");
    }
    setSaving(false);
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-screen">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="p-8 max-w-3xl mx-auto space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Settings</h1>
        <p className="text-muted-foreground mt-1">
          Configure LLM provider and API key for the agent pipeline
        </p>
      </div>

      {/* Backend Status */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Link2 className="h-4 w-4" />
            Backend Status
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center gap-3">
            <span className="text-sm text-muted-foreground">
              http://localhost:8000
            </span>
            {online ? (
              <Badge
                variant="outline"
                className="text-green-600 border-green-600 gap-1"
              >
                <span className="h-1.5 w-1.5 rounded-full bg-green-500" />
                Connected
              </Badge>
            ) : (
              <Badge
                variant="outline"
                className="text-red-500 border-red-500 gap-1"
              >
                <span className="h-1.5 w-1.5 rounded-full bg-red-500" />
                Offline
              </Badge>
            )}
          </div>
          {!online && (
            <p className="text-xs text-muted-foreground mt-2">
              Start the backend: <code className="bg-accent px-1.5 py-0.5 rounded text-[11px]">cd backend && python3 main.py</code>
            </p>
          )}
        </CardContent>
      </Card>

      {/* LLM Provider */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Cpu className="h-4 w-4" />
            LLM Provider
          </CardTitle>
          <CardDescription>
            Select your AI model provider and model
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Provider select */}
          <div className="space-y-2">
            <label className="text-sm font-medium">Provider</label>
            <div className="flex flex-wrap gap-2">
              {PROVIDERS.map((p) => (
                <button
                  key={p.value}
                  onClick={() => {
                    setApiType(p.value);
                    setModel(MODELS[p.value]?.[0] || "");
                  }}
                  className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors ${
                    apiType === p.value
                      ? "border-primary bg-primary/10 text-primary"
                      : "border-border text-muted-foreground hover:border-foreground"
                  }`}
                >
                  {p.label}
                </button>
              ))}
            </div>
          </div>

          {/* Model select */}
          <div className="space-y-2">
            <label className="text-sm font-medium">Model</label>
            <div className="flex flex-wrap gap-2">
              {(MODELS[apiType] || []).map((m) => (
                <button
                  key={m}
                  onClick={() => setModel(m)}
                  className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors ${
                    model === m
                      ? "border-primary bg-primary/10 text-primary"
                      : "border-border text-muted-foreground hover:border-foreground"
                  }`}
                >
                  {m}
                </button>
              ))}
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Vertex AI GCP Settings */}
      {apiType === "vertex" && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Cloud className="h-4 w-4" />
              GCP / Vertex AI
            </CardTitle>
            <CardDescription>
              Uses your GCP credits. No API key needed — uses Application Default Credentials.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <label className="text-sm font-medium">GCP Project ID</label>
              <Input
                value={gcpProjectId}
                onChange={(e) => setGcpProjectId(e.target.value)}
                placeholder="my-gcp-project-123"
                className="max-w-md"
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">Location</label>
              <div className="flex flex-wrap gap-2">
                {["us-central1", "europe-west1", "asia-southeast1"].map((loc) => (
                  <button
                    key={loc}
                    onClick={() => setGcpLocation(loc)}
                    className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors ${
                      gcpLocation === loc
                        ? "border-primary bg-primary/10 text-primary"
                        : "border-border text-muted-foreground hover:border-foreground"
                    }`}
                  >
                    {loc}
                  </button>
                ))}
              </div>
            </div>
            <div className="rounded-lg bg-amber-50 border border-amber-200 p-3 text-xs text-amber-800 space-y-1">
              <p className="font-medium">Setup required:</p>
              <p>1. Install gcloud CLI: <code className="bg-amber-100 px-1 rounded">brew install google-cloud-sdk</code></p>
              <p>2. Login: <code className="bg-amber-100 px-1 rounded">gcloud auth application-default login</code></p>
              <p>3. Set project: <code className="bg-amber-100 px-1 rounded">gcloud config set project YOUR_PROJECT_ID</code></p>
              <p>4. Enable Vertex AI API in GCP Console</p>
            </div>
          </CardContent>
        </Card>
      )}

      {/* API Key (for non-Vertex providers) */}
      {apiType !== "vertex" && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Key className="h-4 w-4" />
              API Key
            </CardTitle>
            <CardDescription>
              {hasKey
                ? "A key is already configured. Enter a new one to replace it."
                : `Enter your ${apiType} API key`}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex items-center gap-2 max-w-md">
              <Input
                type={showKey ? "text" : "password"}
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder={hasKey ? "\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022 (key set)" : "Enter API key..."}
              />
              <Button
                variant="ghost"
                size="icon"
                onClick={() => setShowKey(!showKey)}
              >
                {showKey ? (
                  <EyeOff className="h-4 w-4" />
                ) : (
                  <Eye className="h-4 w-4" />
                )}
              </Button>
            </div>
            {apiType === "gemini" && (
              <p className="text-xs text-muted-foreground mt-2">
                Get a free key from{" "}
                <a
                  href="https://aistudio.google.com/apikey"
                  target="_blank"
                  rel="noreferrer"
                  className="underline text-primary"
                >
                  aistudio.google.com
                </a>
              </p>
            )}

            {/* Base URL (optional) */}
            <div className="mt-4 space-y-2">
              <label className="text-sm font-medium">
                Base URL{" "}
                <span className="text-xs text-muted-foreground font-normal">
                  (optional, for proxies)
                </span>
              </label>
              <Input
                value={baseUrl}
                onChange={(e) => setBaseUrl(e.target.value)}
                placeholder="Leave blank for default"
                className="max-w-md"
              />
            </div>
          </CardContent>
        </Card>
      )}

      <div className="flex justify-end gap-3">
        {saved && (
          <span className="flex items-center gap-1 text-sm text-green-600">
            <CheckCircle2 className="h-4 w-4" />
            Saved!
          </span>
        )}
        <Button onClick={handleSave} disabled={saving || !online} className="gap-2">
          {saving ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Save className="h-4 w-4" />
          )}
          Save Settings
        </Button>
      </div>
    </div>
  );
}
