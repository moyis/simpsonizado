import { useState, useRef, useCallback, useEffect } from 'preact/hooks'
import type { SearchResult } from '../lib/types'
import { framePath } from '../lib/format'

export default function SearchBox() {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<SearchResult[]>([])
  const [searched, setSearched] = useState(false)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const fetchResults = useCallback(async (q: string) => {
    if (!q.trim()) {
      setResults([])
      setSearched(false)
      window.history.replaceState(null, '', '/')
      return
    }

    try {
      const res = await fetch(`/api/search?q=${encodeURIComponent(q)}&limit=20`)
      const data = await res.json()
      setResults(data.results ?? [])
      setSearched(true)
    } catch {
      setResults([])
      setSearched(true)
    } finally {
      window.history.replaceState(null, '', `/?q=${encodeURIComponent(q.trim())}`)
    }
  }, [])

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const initialQuery = params.get('q')
    if (initialQuery) {
      setQuery(initialQuery)
      fetchResults(initialQuery)
    }

    const handleNavSearch = (e: Event) => {
      const value = (e as CustomEvent).detail as string
      setQuery(value)

      if (timerRef.current) clearTimeout(timerRef.current)

      if (!value.trim()) {
        setResults([])
        setSearched(false)
        window.history.replaceState(null, '', '/')
        return
      }

      timerRef.current = setTimeout(() => fetchResults(value), 200)
    }

    window.addEventListener('nav-search', handleNavSearch)
    return () => {
      window.removeEventListener('nav-search', handleNavSearch)
      if (timerRef.current) clearTimeout(timerRef.current)
    }
  }, [])

  return (
    <>
      {searched && results.length === 0 && (
        <p class="text-center text-ink-muted text-lg p-8">No encontramos esa frase</p>
      )}

      {results.length > 0 && (
        <div class="grid grid-cols-2 md:grid-cols-4 gap-2 p-4">
          {results.map((r) => (
            <a
              key={`${r.episodeId}-${r.startMs}`}
              href={`/frame/${r.episodeId}/${r.startMs}?q=${encodeURIComponent(query)}`}
              class="no-underline border-2 border-transparent hover:border-primary"
            >
              <img
                src={framePath(r.episodeId, r.startMs)}
                alt={r.text}
                loading="lazy"
                class="w-full block aspect-video object-cover"
                style={`view-transition-name: frame-${r.episodeId}-${r.startMs}`}
              />
            </a>
          ))}
        </div>
      )}
    </>
  )
}
