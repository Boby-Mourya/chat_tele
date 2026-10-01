import { getWidgetLocale } from '@/lib/widget-localization';
import type { Agent, WhatsAppMessageSettings } from '@/types';

export function whatsappMessageSettings(agent: Agent): WhatsAppMessageSettings {
  const locale = getWidgetLocale(agent.language);
  const heading = agent.language === 'English' ? `Hi! Welcome to ${agent.name}.` : `${agent.name}\n${locale.welcomeTitle}`;
  return {
    welcomeEnabled: agent.appearance.whatsapp?.welcomeEnabled ?? true,
    welcomeMessage: agent.appearance.whatsapp?.welcomeMessage ?? `${heading}\n\n${agent.appearance.welcomeMessage || locale.welcomeMessage}`,
    replyTemplate: agent.appearance.whatsapp?.replyTemplate ?? '{message}',
  };
}

export function whatsappTemplateError(value: string): string | undefined {
  if (value.length > 1500) return 'Use at most 1,500 characters.';
  if (value.split('{message}').length !== 2) return 'Include {message} exactly once for the bot’s answer.';
  if (/[{}]/.test(value.replaceAll('{message}', '').replaceAll('{bot_name}', ''))) return 'Use only {message} and {bot_name} placeholders.';
}

export function validWhatsAppSettings(settings?: WhatsAppMessageSettings | null): boolean {
  if (!settings) return true;
  return !whatsappTemplateError(settings.replyTemplate)
    && (settings.welcomeMessage === null || (settings.welcomeMessage.length <= 4096 && (!settings.welcomeEnabled || Boolean(settings.welcomeMessage.trim()))));
}

export function formatWhatsAppReply(agent: Agent, message: string): string {
  const body = message.split(/(```[\s\S]*?```|`[^`\n]+`)/g).map((part, index) => index % 2
    ? part.replace(/^```[a-zA-Z][\w+-]*\r?\n/, '```\n')
    : part.replace(/\*\*(.+?)\*\*/g, '*$1*')
      .replace(/^#{1,6}[ \t]+(.+)$/gm, '*$1*')
      .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '$1: $2')).join('');
  return whatsappMessageSettings(agent).replyTemplate.replace(/\{(message|bot_name)\}/g, (_, key: string) => key === 'message' ? body : agent.name).trim();
}

export function applyWhatsAppFormatting(value: string, start: number, end: number, marker: string, kind: 'wrap' | 'line' = 'wrap') {
  if (kind === 'line') {
    start = start > 0 ? value.lastIndexOf('\n', start - 1) + 1 : 0;
    const stop = end > start && value[end - 1] === '\n' ? end - 1 : end;
    const newline = value.indexOf('\n', stop);
    end = newline < 0 ? value.length : newline;
  }
  const selected = value.slice(start, end);
  let formatted: string;
  if (kind === 'line') {
    const lines = selected.split('\n');
    const prefix = marker === '1. ' ? /^\d+\. / : marker === '> ' ? /^> / : /^- /;
    const remove = lines.every((line) => prefix.test(line));
    formatted = lines.map((line, index) => remove ? line.replace(prefix, '') : `${marker === '1. ' ? `${index + 1}. ` : marker}${line.replace(/^(?:[-*] |\d+\. |> )/, '')}`).join('\n');
  } else if ((marker === '```' || !selected.includes('\n')) && selected.startsWith(marker) && selected.endsWith(marker) && selected.length >= marker.length * 2) {
    formatted = selected.slice(marker.length, -marker.length);
  } else if (start >= marker.length && value.slice(start - marker.length, start) === marker && value.slice(end, end + marker.length) === marker) {
    start -= marker.length;
    end += marker.length;
    formatted = selected;
  } else {
    const content = selected || 'Text';
    const lines = content.split('\n');
    const remove = lines.filter((line) => line.trim()).every((line) => line.trim().startsWith(marker) && line.trim().endsWith(marker) && line.trim().length >= marker.length * 2);
    formatted = marker === '```' ? `${marker}${content}${marker}` : lines.map((line) => line.trim() ? line.replace(/^(\s*)(.*?)(\s*)$/, (_, before: string, inner: string, after: string) => before + (remove ? inner.slice(marker.length, -marker.length) : marker + inner + marker) + after) : line).join('\n');
  }
  return { value: value.slice(0, start) + formatted + value.slice(end), start, end: start + formatted.length };
}

export function whatsappChatUrl(number?: string | null): string | undefined {
  const digits = (number ?? '').replace(/\D/g, '');
  return /^[1-9]\d{6,14}$/.test(digits) ? `https://wa.me/${digits}` : undefined;
}
