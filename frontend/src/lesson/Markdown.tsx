import React from 'react'

/** Tiny markdown subset for lesson bodies: paragraphs, -/1. lists,
 * > blockquotes, **bold**, *em*, `code`. Deliberately no dependency. */

function inline(text: string): React.ReactNode[] {
  const out: React.ReactNode[] = []
  const re = /(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)/g
  let last = 0
  let match: RegExpExecArray | null
  let key = 0
  while ((match = re.exec(text)) !== null) {
    if (match.index > last) out.push(text.slice(last, match.index))
    const token = match[0]
    if (token.startsWith('**')) out.push(<strong key={key++}>{token.slice(2, -2)}</strong>)
    else if (token.startsWith('`')) out.push(<code key={key++}>{token.slice(1, -1)}</code>)
    else out.push(<em key={key++}>{token.slice(1, -1)}</em>)
    last = match.index + token.length
  }
  if (last < text.length) out.push(text.slice(last))
  return out
}

type Block =
  | { kind: 'p'; text: string }
  | { kind: 'quote'; text: string }
  | { kind: 'ul'; items: string[] }
  | { kind: 'ol'; items: string[] }

function parse(text: string): Block[] {
  const blocks: Block[] = []
  let para: string[] = []
  const flush = () => {
    if (para.length) blocks.push({ kind: 'p', text: para.join(' ') })
    para = []
  }
  for (const raw of text.split('\n')) {
    const line = raw.trim()
    if (!line) {
      flush()
      continue
    }
    const li = line.match(/^[-•]\s+(.*)$/)
    const oli = line.match(/^\d+\.\s+(.*)$/)
    if (li || oli) {
      flush()
      const kind = li ? 'ul' : 'ol'
      const item = (li ?? oli)![1]
      const lastBlock = blocks[blocks.length - 1]
      if (lastBlock && (lastBlock.kind === 'ul' || lastBlock.kind === 'ol') && lastBlock.kind === kind) {
        lastBlock.items.push(item)
      } else if (kind === 'ul') {
        blocks.push({ kind: 'ul', items: [item] })
      } else {
        blocks.push({ kind: 'ol', items: [item] })
      }
      continue
    }
    if (line.startsWith('> ')) {
      flush()
      const lastBlock = blocks[blocks.length - 1]
      if (lastBlock && lastBlock.kind === 'quote') lastBlock.text += ' ' + line.slice(2)
      else blocks.push({ kind: 'quote', text: line.slice(2) })
      continue
    }
    // continuation of a list item (indented prose) folds into the last item
    const lastBlock = blocks[blocks.length - 1]
    if (raw.startsWith('  ') && lastBlock && (lastBlock.kind === 'ul' || lastBlock.kind === 'ol') && para.length === 0) {
      lastBlock.items[lastBlock.items.length - 1] += ' ' + line
      continue
    }
    para.push(line)
  }
  flush()
  return blocks
}

export function Markdown({ text }: { text: string }) {
  return (
    <div className="md">
      {parse(text).map((b, i) => {
        if (b.kind === 'ul' || b.kind === 'ol') {
          const items = b.items.map((it, j) => <li key={j}>{inline(it)}</li>)
          return b.kind === 'ul' ? <ul key={i}>{items}</ul> : <ol key={i}>{items}</ol>
        }
        if (b.kind === 'quote') return <blockquote key={i}>{inline(b.text)}</blockquote>
        return <p key={i}>{inline(b.text)}</p>
      })}
    </div>
  )
}
