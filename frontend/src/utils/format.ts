const dateTime = new Intl.DateTimeFormat("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
});

export function formatDateTime(iso?: string | null): string {
    if (!iso) return "";
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? "" : dateTime.format(d);
}

export function timeAgo(iso?: string | null, now: number = Date.now()): string {
    if (!iso) return "";
    const seconds = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000));
    if (seconds < 60) return "just now";
    const minutes = Math.round(seconds / 60);
    if (minutes < 60) return `${minutes} min ago`;
    const hours = Math.round(minutes / 60);
    if (hours < 24) return `${hours} h ago`;
    const days = Math.round(hours / 24);
    return `${days} day${days === 1 ? "" : "s"} ago`;
}

export function formatNumber(n: number): string {
    return new Intl.NumberFormat("en-IN").format(n);
}

export function formatPercent(ratio: number): string {
    return `${Math.round(ratio * 100)}%`;
}

export function formatDuration(hours: number): string {
    if (!hours) return "n/a";
    if (hours < 1) return `${Math.round(hours * 60)} min`;
    if (hours < 48) return `${hours.toFixed(1)} h`;
    return `${(hours / 24).toFixed(1)} days`;
}
