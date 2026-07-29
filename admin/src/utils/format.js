export function formatDateTime(d) {
    if (!d)
        return '-';
    const date = typeof d === 'string' ? new Date(d) : d;
    return date.toLocaleString('zh-CN', { hour12: false });
}
export function formatDate(d) {
    if (!d)
        return '-';
    const date = typeof d === 'string' ? new Date(d) : d;
    return date.toLocaleDateString('zh-CN');
}
export function formatTime(hhmm) {
    return hhmm || '-';
}
//# sourceMappingURL=format.js.map