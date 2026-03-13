import { formatDistanceToNow, parseISO } from 'date-fns'
import type { TicketCategory, TicketPriority, TicketStatus } from '../types'

export function timeAgo(iso: string): string {
  try {
    return formatDistanceToNow(parseISO(iso), { addSuffix: true })
  } catch {
    return iso
  }
}

export function categoryLabel(cat: TicketCategory | null): string {
  const map: Record<TicketCategory, string> = {
    refund_request: '💸 Refund',
    bug_report: '🐛 Bug',
    billing: '💳 Billing',
    question: '❓ Question',
    feature_request: '✨ Feature',
    account: '👤 Account',
    other: '📋 Other',
  }
  return cat ? map[cat] : '—'
}

export function priorityColor(p: TicketPriority | null): string {
  switch (p) {
    case 'urgent': return '#dc2626'
    case 'high': return '#ea580c'
    case 'medium': return '#7c63e8'
    case 'low': return '#16a34a'
    default: return '#7c6ea8'
  }
}

export function statusLabel(s: TicketStatus): string {
  const map: Record<TicketStatus, string> = {
    open: 'Open',
    pending: 'Pending Reply',
    in_progress: 'In Progress',
    resolved: 'Resolved',
    closed: 'Closed',
  }
  return map[s]
}

export function statusColor(s: TicketStatus): string {
  switch (s) {
    case 'open': return '#2563eb'
    case 'pending': return '#7c63e8'
    case 'in_progress': return '#ea580c'
    case 'resolved': return '#16a34a'
    case 'closed': return '#7c6ea8'
  }
}

export function languageFlag(lang: string | null): string {
  const map: Record<string, string> = {
    de: '🇩🇪', fr: '🇫🇷', it: '🇮🇹', en: '🇬🇧',
    tr: '🇹🇷', nl: '🇳🇱', es: '🇪🇸', pt: '🇵🇹',
  }
  return lang ? (map[lang] ?? '🌐') : '🌐'
}

export function initials(name: string | null | undefined): string {
  if (!name) return '?'
  return name.split(' ').map(n => n[0]).join('').toUpperCase().slice(0, 2)
}

export function tagColor(tag: string): { bg: string; color: string } {
  if (tag.includes('refund') || tag.includes('billing')) return { bg: 'rgba(79,53,210,.1)', color: '#4f35d2' }
  if (tag.includes('bug') || tag.includes('error')) return { bg: 'rgba(220,38,38,.1)', color: '#dc2626' }
  if (tag.includes('ai') || tag.includes('draft')) return { bg: 'rgba(37,99,235,.1)', color: '#2563eb' }
  return { bg: 'rgba(124,110,168,.1)', color: '#7c6ea8' }
}
