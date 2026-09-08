const SMALL_WORDS = new Set([
  'a', 'an', 'the', 'to', 'of', 'for', 'and', 'or', 'in', 'on', 'at', 'by',
  'from', 'with', 'as', 'is', 'are', 'was', 'were', 'be', 'it', 'its',
])

const ACRONYM_WORDS = new Set([
  'api', 'sql', 'http', 'https', 'json', 'csv', 'yaml', 'yml', 'xml', 'ui',
  'ux', 'css', 'html', 'ids', 'ftp', 'smtp', 'tcp', 'udp', 'dns', 'aws',
  'gcp', 'ml', 'cv', 'svc',
])

export function humanizeTopicLabel(label: string): string {
  const raw = (label ?? '').trim()
  if (!raw) return raw
  const hasUnderscore = raw.includes('_')
  const hasSpace = /\s/.test(raw)
  const hasUpper = /[A-Z]/.test(raw)
  if (!hasUnderscore && hasSpace && hasUpper) return raw
  const words = raw.replace(/_/g, ' ').split(/\s+/).filter(Boolean)
  return words
    .map((word, i) => {
      if (word.length > 1 && (word === word.toUpperCase() || ACRONYM_WORDS.has(word.toLowerCase()))) {
        return word.toUpperCase()
      }
      if (i > 0 && SMALL_WORDS.has(word.toLowerCase())) return word.toLowerCase()
      return word.charAt(0).toUpperCase() + word.slice(1)
    })
    .join(' ')
}